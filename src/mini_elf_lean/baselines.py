"""Tiny tactic-prediction baselines for the theorem-level lean-cli dataset.

This is *not* a state-transition model. The processed dataset's ``state_after``
is the lean-cli placeholder (``state_after_is_real=false``) so we never use it
as a target — every baseline here predicts ``tactic`` from
``(theorem_statement, state_before)`` only.

Two real baselines + one diagnostic:

  - :class:`MajorityBaseline` — predict the top-k most frequent training
    tactics, regardless of input. Surprisingly strong on small corpora; the
    floor anything else must beat.
  - :class:`RetrievalBaseline` — score training examples by similarity to the
    input text and return the deduplicated tactics of the nearest neighbors.
    Uses :mod:`sklearn`'s TF-IDF + cosine when available; falls back to a
    pure-Python char-3-gram cosine when not.
  - :func:`oracle_verified_lookup` — the diagnostic upper bound: for each
    ``(theorem_name, state_before)`` pair, the set of tactics known to be
    verified somewhere in the dataset. A baseline cannot do better than
    "predicts ⊇ at least one element of oracle[row]".

Theorem-level no-leakage is the load-bearing invariant: split assignment is
already by ``theorem_name`` in the dataset, but :func:`load_dataset_split`
double-checks it and the retrieval baseline only ever sees training rows.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from .io_utils import read_jsonl

logger = logging.getLogger(__name__)


# ---------------- data loading ----------------


@dataclass(frozen=True)
class Example:
    """One processed-dataset row reduced to what baselines actually use."""

    theorem_name: str
    theorem_statement: str
    state_before: str
    tactic: str
    split: str

    @property
    def text(self) -> str:
        """Input text the retrieval baseline scores against. We keep this
        identical for training and inference so train/eval representations
        cannot drift."""
        return f"{self.theorem_statement}\n{self.state_before}"


def load_dataset(path: Path) -> List[Example]:
    """Load every row of a processed ``next_tactic.jsonl`` as :class:`Example`."""
    out: List[Example] = []
    for raw in read_jsonl(path):
        out.append(
            Example(
                theorem_name=raw["theorem_name"],
                theorem_statement=raw["theorem_statement"],
                state_before=raw["state_before"],
                tactic=raw["tactic"],
                split=raw["split"],
            )
        )
    return out


def load_dataset_split(
    path: Path, split: str
) -> Tuple[List[Example], List[Example]]:
    """Return ``(train_examples, eval_examples)`` from one processed dataset.

    ``split`` selects the eval portion (``"train"``/``"val"``/``"test"``). The
    train portion is always the dataset's ``train`` rows. We also assert no
    theorem-name overlap between the returned bags — the dataset builder is
    supposed to guarantee this, but we re-check rather than trust by faith.
    """
    if split not in ("train", "val", "test"):
        raise ValueError(f"split must be train|val|test, got {split!r}")
    all_examples = load_dataset(path)
    train = [e for e in all_examples if e.split == "train"]
    if split == "train":
        # Debug mode: caller asked for train-on-train. We still return distinct
        # objects so the eval loop doesn't accidentally mutate the train set.
        return train, list(train)
    eval_ = [e for e in all_examples if e.split == split]
    train_names = {e.theorem_name for e in train}
    eval_names = {e.theorem_name for e in eval_}
    overlap = train_names & eval_names
    if overlap:
        raise RuntimeError(
            f"Dataset leakage: theorem(s) appear in both train and {split}: {sorted(overlap)}. "
            "The dataset builder is supposed to split by theorem_name."
        )
    return train, eval_


def oracle_verified_lookup(examples: Iterable[Example]) -> Dict[Tuple[str, str], FrozenSet[str]]:
    """Verified-tactic set per ``(theorem_name, state_before)``. Aggregated
    across the *whole* dataset so an eval row gets credit for any verified
    alternate. ``Example`` rows must already be filtered to successful records
    (the processed dataset is by default)."""
    bag: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    for e in examples:
        bag[(e.theorem_name, e.state_before)].add(e.tactic)
    return {k: frozenset(v) for k, v in bag.items()}


# ---------------- baselines ----------------


class Baseline:
    """Minimal interface. ``fit`` consumes training examples; ``predict``
    returns up to ``k`` ranked tactic strings (deduplicated)."""

    name: str = "baseline"

    def fit(self, train: Sequence[Example]) -> "Baseline":  # pragma: no cover - interface
        raise NotImplementedError

    def predict(self, example: Example, *, k: int) -> List[str]:  # pragma: no cover - interface
        raise NotImplementedError


class MajorityBaseline(Baseline):
    """Predict the top-k most frequent training tactics, ignoring input.

    Ties are broken alphabetically so the output is stable across runs and
    platforms (Python's :class:`collections.Counter` does not promise tie order).
    """

    name = "majority"

    def __init__(self) -> None:
        self._ranked: List[str] = []

    def fit(self, train: Sequence[Example]) -> "MajorityBaseline":
        counts = Counter(e.tactic for e in train)
        # (-count, tactic) sorts by count desc, then tactic asc — deterministic.
        self._ranked = [tac for tac, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        return self

    def predict(self, example: Example, *, k: int) -> List[str]:
        return list(self._ranked[:k])


# ---- retrieval ----

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _char_trigrams(s: str) -> Counter:
    """Overlapping character 3-grams, with explicit start/end padding so very
    short strings still produce features. Lowercased for case-insensitive match.
    """
    s = f"  {s.lower()}  "
    if len(s) < 3:
        return Counter()
    return Counter(s[i : i + 3] for i in range(len(s) - 2))


def _cosine_from_counters(a: Counter, b: Counter, *, b_norm: float) -> float:
    """Cosine between two sparse :class:`Counter` vectors. ``b_norm`` is the
    L2 norm of ``b`` (precomputed in :class:`RetrievalBaseline.fit`)."""
    if not a or not b or b_norm == 0.0:
        return 0.0
    # Iterate the smaller dict.
    if len(a) > len(b):
        a, b = b, a
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    if dot == 0.0:
        return 0.0
    a_norm = math.sqrt(sum(v * v for v in a.values()))
    return dot / (a_norm * b_norm) if a_norm else 0.0


@dataclass
class _RetrievalIndexCharNgram:
    """Pure-Python fallback. Stores per-train-example 3-gram count Counters
    and their L2 norms; scoring is sparse-dot-product cosine."""

    counters: List[Counter] = field(default_factory=list)
    norms: List[float] = field(default_factory=list)
    tactics: List[str] = field(default_factory=list)
    theorem_names: List[str] = field(default_factory=list)


class RetrievalBaseline(Baseline):
    """k-NN over training texts: for each eval example, fetch the most similar
    training rows and return their tactics, deduplicated in rank order.

    Uses :class:`sklearn.feature_extraction.text.TfidfVectorizer` + cosine when
    sklearn is available (the standard choice). When it is not — true for this
    repo's WSL venv right now — we fall back to a tiny pure-Python char-3-gram
    cosine. The fallback is *only* meant to be a sensible baseline-of-a-baseline
    over the small theorem-level corpus; it is not a substitute for a real
    encoder on a large dataset.
    """

    name = "retrieval"

    def __init__(self, *, neighbors: int = 16, prefer_sklearn: bool = True) -> None:
        # `neighbors` is how many train rows we score before deduping tactics.
        # Bigger -> more chance the dedup'd top-k is filled out by alternates.
        self.neighbors = max(neighbors, 1)
        self._mode: str = "uninit"  # "sklearn" | "char-ngram" | "uninit"
        self._train_tactics: List[str] = []
        self._train_theorem_names: List[str] = []
        # sklearn mode state
        self._vectorizer = None
        self._train_matrix = None
        # char-ngram mode state
        self._ng_index: _RetrievalIndexCharNgram = _RetrievalIndexCharNgram()

        self._sklearn_available = False
        if prefer_sklearn:
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: F401
                from sklearn.metrics.pairwise import cosine_similarity  # noqa: F401

                self._sklearn_available = True
            except ImportError:
                self._sklearn_available = False

    @property
    def mode(self) -> str:
        return self._mode

    def fit(self, train: Sequence[Example]) -> "RetrievalBaseline":
        self._train_tactics = [e.tactic for e in train]
        self._train_theorem_names = [e.theorem_name for e in train]

        if not train:
            self._mode = "char-ngram"  # harmless; predict will just return []
            self._ng_index = _RetrievalIndexCharNgram()
            return self

        if self._sklearn_available:
            from sklearn.feature_extraction.text import TfidfVectorizer

            self._vectorizer = TfidfVectorizer(
                analyzer="char_wb", ngram_range=(2, 4), min_df=1, sublinear_tf=True,
            )
            self._train_matrix = self._vectorizer.fit_transform(e.text for e in train)
            self._mode = "sklearn"
        else:
            counters = [_char_trigrams(e.text) for e in train]
            norms = [math.sqrt(sum(v * v for v in c.values())) for c in counters]
            self._ng_index = _RetrievalIndexCharNgram(
                counters=counters, norms=norms,
                tactics=self._train_tactics,
                theorem_names=self._train_theorem_names,
            )
            self._mode = "char-ngram"
        return self

    def predict(self, example: Example, *, k: int) -> List[str]:
        if not self._train_tactics:
            return []
        scores = self._score(example.text)
        # Argsort desc by score (stable for ties).
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        seen: set = set()
        out: List[str] = []
        for i in order[: max(self.neighbors, k)]:
            tac = self._train_tactics[i]
            if tac in seen:
                continue
            seen.add(tac)
            out.append(tac)
            if len(out) >= k:
                break
        return out

    def predict_with_neighbors(
        self, example: Example, *, k: int
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Same as :meth:`predict` but also returns the source neighbor info for
        each emitted tactic. Used by the eval module to attach provenance to the
        predictions JSONL output."""
        scores = self._score(example.text)
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        seen: set = set()
        tactics: List[str] = []
        provenance: List[Dict[str, Any]] = []
        for i in order[: max(self.neighbors, k)]:
            tac = self._train_tactics[i]
            if tac in seen:
                continue
            seen.add(tac)
            tactics.append(tac)
            provenance.append(
                {
                    "source_theorem": self._train_theorem_names[i],
                    "score": float(scores[i]),
                }
            )
            if len(tactics) >= k:
                break
        return tactics, provenance

    # ---- internal scoring ----

    def _score(self, text: str) -> List[float]:
        if self._mode == "sklearn":
            from sklearn.metrics.pairwise import cosine_similarity

            q = self._vectorizer.transform([text])
            return cosine_similarity(q, self._train_matrix)[0].tolist()
        # char-ngram
        q = _char_trigrams(text)
        return [
            _cosine_from_counters(q, c, b_norm=n)
            for c, n in zip(self._ng_index.counters, self._ng_index.norms)
        ]


# ---------------- helpers ----------------


def split_summary(train: Sequence[Example], eval_: Sequence[Example]) -> Dict[str, Any]:
    """Cheap diagnostic dict the CLI prints + records in metrics.json."""
    train_names = {e.theorem_name for e in train}
    eval_names = {e.theorem_name for e in eval_}
    return {
        "n_train_examples": len(train),
        "n_eval_examples": len(eval_),
        "n_train_theorems": len(train_names),
        "n_eval_theorems": len(eval_names),
        "theorem_intersection": sorted(train_names & eval_names),  # must be []
    }
