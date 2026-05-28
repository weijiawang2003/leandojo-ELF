"""A small *trained* tactic-prediction baseline — pure Python, no numpy/torch.

The env has no numpy / sklearn / torch, and the corpus is tiny (~256 train
rows, ~50 distinct tactics), so a heavyweight transformer is neither available
nor warranted. This is the task brief's sanctioned fallback: a classifier that
predicts the **full tactic string directly** from the input text, trained with
SGD. It is a genuine learned model — a log-linear / softmax classifier (a
1-layer network) over hashed character n-gram features — not a lookup table.

It maps  ``theorem_statement + "\\n" + state_before  ->  tactic``  and NEVER sees
``state_after`` (the :class:`~mini_elf_lean.baselines.Example` it consumes does
not even carry that field, so this is structurally guaranteed).

Why it can beat the char-ngram *retrieval* baseline on sibling families
-----------------------------------------------------------------------
Retrieval copies the single nearest neighbor's tactic; when the nearest neighbor
is a structurally-similar sibling (``and_elim_left`` vs ``and_elim_right`` differ
only in the goal line ``⊢ p`` vs ``⊢ q``), it copies the wrong tactic and the
top-5 gets crowded by other near-identical theorems. A trained classifier instead
(a) puts dedicated weight on the **goal-line features** (we hash goal-line
n-grams into a separate feature space), and (b) naturally surfaces *both* sibling
tactics (``exact h.1`` and ``exact h.2``) high in its ranking because both are
common "and-elimination" tactics in training — so pass@k (k>=2) gets credit even
when top-1 is ambiguous.

Determinism: stable hashing (``zlib.crc32``, not Python's salted ``hash``) and a
seeded shuffle make training reproducible across runs and machines.
"""

from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .baselines import Baseline, Example


# ---------------- feature extraction ----------------


def _ngrams(s: str, orders: Sequence[int]) -> List[str]:
    s = f"^{s}$"
    out: List[str] = []
    for n in orders:
        if len(s) < n:
            continue
        out.extend(s[i : i + n] for i in range(len(s) - n + 1))
    return out


def _goal_line(state_before: str) -> str:
    """The ``⊢ ...`` line of a proof state (the discriminating bit for sibling
    families). Falls back to the whole state if no turnstile is present."""
    for line in state_before.splitlines():
        if line.lstrip().startswith("⊢"):
            return line.strip()
    return state_before.strip()


@dataclass(frozen=True)
class NgramVectorizer:
    """Field-aware hashed char-n-gram features.

    Two feature fields share one hashed space but are disjoint by construction
    (the field tag is hashed in): ``F`` = full input text, ``G`` = goal line.
    The goal field gives the classifier a dedicated, high-signal view of the
    one part of the input that separates sibling families.

    Vectors are L2-normalized (``normalize=True``) so each example contributes a
    bounded gradient — without this, ~200 active binary features at ``lr=0.5``
    saturate the softmax and the loss diverges (ranking still works, but the
    model is wildly miscalibrated and the loss curve is meaningless).
    """

    dim: int = 8192
    orders: Tuple[int, ...] = (2, 3, 4)
    normalize: bool = True

    def _bucket(self, field_tag: str, gram: str) -> int:
        return zlib.crc32(f"{field_tag}\x1f{gram}".encode("utf-8")) % self.dim

    def transform(self, statement: str, state_before: str) -> Dict[int, float]:
        feats: Dict[int, float] = {}
        full = f"{statement}\n{state_before}"
        for g in _ngrams(full, self.orders):
            feats[self._bucket("F", g)] = 1.0
        for g in _ngrams(_goal_line(state_before), self.orders):
            # goal-line features get a small boost so the discriminating signal
            # isn't drowned out by the (mostly shared) full-text features.
            b = self._bucket("G", g)
            feats[b] = feats.get(b, 0.0) + 1.5
        if self.normalize and feats:
            norm = math.sqrt(sum(v * v for v in feats.values()))
            if norm > 0:
                feats = {k: v / norm for k, v in feats.items()}
        return feats


# ---------------- softmax classifier ----------------


@dataclass
class SoftmaxClassifier:
    """Multinomial logistic regression trained with plain SGD.

    Sparse weights: ``W[c]`` is a dict ``feature_id -> weight`` per class; only
    features active in an example are touched per step, so cost is
    ``O(n_examples * n_classes * active_features_per_example)`` per epoch — fine
    for this corpus in pure Python.
    """

    n_classes: int
    lr: float = 0.5
    l2: float = 1e-5
    epochs: int = 30
    seed: int = 0
    W: List[Dict[int, float]] = field(default_factory=list)
    bias: List[float] = field(default_factory=list)
    training_log: List[dict] = field(default_factory=list)

    def _init(self) -> None:
        self.W = [dict() for _ in range(self.n_classes)]
        self.bias = [0.0] * self.n_classes

    def _scores(self, feats: Dict[int, float]) -> List[float]:
        s = list(self.bias)
        for c in range(self.n_classes):
            wc = self.W[c]
            if not wc:
                continue
            acc = 0.0
            for f, v in feats.items():
                w = wc.get(f)
                if w is not None:
                    acc += w * v
            s[c] += acc
        return s

    @staticmethod
    def _softmax(scores: List[float]) -> List[float]:
        m = max(scores)
        exps = [math.exp(s - m) for s in scores]
        z = sum(exps)
        return [e / z for e in exps]

    def fit(self, X: Sequence[Dict[int, float]], y: Sequence[int]) -> "SoftmaxClassifier":
        self._init()
        rng = random.Random(self.seed)
        idx = list(range(len(X)))
        for epoch in range(self.epochs):
            rng.shuffle(idx)
            total_loss = 0.0
            for i in idx:
                feats, gold = X[i], y[i]
                probs = self._softmax(self._scores(feats))
                total_loss += -math.log(max(probs[gold], 1e-12))
                # gradient step on active features only
                for c in range(self.n_classes):
                    err = probs[c] - (1.0 if c == gold else 0.0)
                    if err == 0.0 and c != gold:
                        # tiny prob -> still update, but skip exact zeros for speed
                        pass
                    wc = self.W[c]
                    g_bias = err
                    self.bias[c] -= self.lr * g_bias
                    if err != 0.0:
                        for f, v in feats.items():
                            grad = err * v + self.l2 * wc.get(f, 0.0)
                            nw = wc.get(f, 0.0) - self.lr * grad
                            if nw == 0.0:
                                wc.pop(f, None)
                            else:
                                wc[f] = nw
            avg_loss = total_loss / max(len(X), 1)
            self.training_log.append({"epoch": epoch, "avg_cross_entropy": avg_loss})
        return self

    def predict_scores(self, feats: Dict[int, float]) -> List[float]:
        return self._scores(feats)


# ---------------- baseline wrapper ----------------


class NeuralTacticBaseline(Baseline):
    """Trained tactic classifier behind the :class:`Baseline` interface.

    ``fit`` learns ``input_text -> tactic``; ``predict`` returns the top-k
    distinct tactics by classifier score (classes ARE distinct tactic strings,
    so they are inherently deduplicated). Exposes ``training_config`` and
    ``training_log`` for the CLI to persist.
    """

    name = "neural"

    def __init__(
        self, *, dim: int = 8192, orders: Tuple[int, ...] = (2, 3, 4),
        epochs: int = 30, lr: float = 0.5, l2: float = 1e-5, seed: int = 0,
    ) -> None:
        self.vectorizer = NgramVectorizer(dim=dim, orders=orders)
        self.epochs, self.lr, self.l2, self.seed = epochs, lr, l2, seed
        self.classes: List[str] = []
        self._clf: Optional[SoftmaxClassifier] = None
        self.training_config: dict = {}
        self.training_log: List[dict] = []
        self.train_top1_acc: Optional[float] = None

    @property
    def mode(self) -> str:
        return "softmax-ngram"

    def fit(self, train: Sequence[Example]) -> "NeuralTacticBaseline":
        # NOTE: only theorem_statement / state_before / tactic are read here.
        # Example has no state_after attribute, so this baseline cannot use it.
        self.classes = sorted({e.tactic for e in train})
        cls_index = {t: i for i, t in enumerate(self.classes)}
        X = [self.vectorizer.transform(e.theorem_statement, e.state_before) for e in train]
        y = [cls_index[e.tactic] for e in train]

        self._clf = SoftmaxClassifier(
            n_classes=len(self.classes), lr=self.lr, l2=self.l2,
            epochs=self.epochs, seed=self.seed,
        ).fit(X, y)
        self.training_log = self._clf.training_log

        # final train top-1 accuracy (for the config/report)
        correct = sum(1 for feats, gold in zip(X, y)
                      if (self._argmax(self._clf.predict_scores(feats)) == gold))
        self.train_top1_acc = correct / len(X) if X else 0.0

        self.training_config = {
            "model": "softmax_logreg_char_ngram",
            "framework": "pure-python",
            "dim": self.vectorizer.dim,
            "ngram_orders": list(self.vectorizer.orders),
            "epochs": self.epochs,
            "lr": self.lr,
            "l2": self.l2,
            "seed": self.seed,
            "n_classes": len(self.classes),
            "n_train_examples": len(train),
            "train_top1_accuracy": self.train_top1_acc,
            "uses_state_after": False,
        }
        return self

    @staticmethod
    def _argmax(scores: List[float]) -> int:
        best_i, best_v = 0, float("-inf")
        for i, v in enumerate(scores):
            if v > best_v:
                best_i, best_v = i, v
        return best_i

    def predict(self, example: Example, *, k: int) -> List[str]:
        if self._clf is None or not self.classes:
            return []
        feats = self.vectorizer.transform(example.theorem_statement, example.state_before)
        scores = self._clf.predict_scores(feats)
        order = sorted(range(len(scores)), key=lambda c: -scores[c])
        # classes are distinct tactic strings -> already deduplicated.
        return [self.classes[c] for c in order[:k]]
