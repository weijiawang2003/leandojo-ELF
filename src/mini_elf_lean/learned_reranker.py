"""Mini-ELF v15 — pure-Python logistic regression for candidate reranking.

Deterministic CPU-only logistic regression trained on
:class:`mini_elf_lean.rerank_dataset.CandidateRow` rows. Features come
from :func:`mini_elf_lean.rerank_dataset.extract_features`. Class
weighting handles the ~8 % positive rate without resampling.

The model is intentionally simple so we can:
  1. **Inspect** it (top weights are interpretable feature names —
     no embedding lookup, no hidden layer).
  2. **Train fast** on CPU (1779 rows × ~280 features = a 0.5-second
     SGD).
  3. **Save / load** as plain JSON (no torch state_dict).
  4. **Predict** in a fraction of a millisecond per candidate.

No sklearn dependency, no torch dependency — this is mini-ELF style
(the project's neural_baseline.py is also pure-Python LR).

Honest scope (v15 brief):
  * No state_after anywhere.
  * No manual oracle (rows come from lean-verified caches only).
  * No v10 leakage (the dataset builder routes via v11 LOFO folds).
  * No full theorem proving (this changes ranking, not generation).
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .rerank_dataset import CandidateRow, extract_features


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


@dataclass
class TrainConfig:
    """Hyperparameters for the pure-Python LR. All defaults pick what
    worked best in offline sweeps on the v15 dataset."""

    epochs: int = 200
    lr: float = 0.5
    l2: float = 1e-3
    class_weight_positive: float = 6.0  # ~ inverse of positive frequency
    seed: int = 0
    hashed_dim: int = 256  # passed to extract_features

    def to_jsonable(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Feature ↔ index mapping
# --------------------------------------------------------------------------- #


class FeatureIndex:
    """Maps feature names (strings) to dense integer ids.

    Built from the *training set only*. At inference time, OOV feature
    names are silently dropped (the model just has no weight for them).
    """

    def __init__(self) -> None:
        self.name_to_id: Dict[str, int] = {}
        self.id_to_name: List[str] = []

    def add(self, name: str) -> int:
        i = self.name_to_id.get(name)
        if i is not None:
            return i
        i = len(self.id_to_name)
        self.name_to_id[name] = i
        self.id_to_name.append(name)
        return i

    def get(self, name: str) -> Optional[int]:
        return self.name_to_id.get(name)

    def __len__(self) -> int:
        return len(self.id_to_name)

    def to_jsonable(self) -> Dict[str, Any]:
        return {"id_to_name": self.id_to_name}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "FeatureIndex":
        out = cls()
        for n in d["id_to_name"]:
            out.add(n)
        return out


# --------------------------------------------------------------------------- #
# Vectorisation
# --------------------------------------------------------------------------- #


def vectorise(features: Mapping[str, float], index: FeatureIndex,
              *, extend: bool = False) -> Dict[int, float]:
    """Turn a feature dict into a sparse {id: value} map. If
    ``extend=True`` (train time), unseen feature names get added to
    ``index``; otherwise they are dropped (eval time)."""
    out: Dict[int, float] = {}
    for name, v in features.items():
        if extend:
            i = index.add(name)
        else:
            i = index.get(name)
            if i is None:
                continue
        out[i] = v
    return out


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


@dataclass
class LearnedReranker:
    """Linear logistic regression on sparse {feature_id: value}
    vectors. Bias is implicit via the ``bias`` feature emitted by
    ``extract_features``."""

    index: FeatureIndex
    weights: List[float]
    train_config: TrainConfig
    train_history: List[Dict[str, Any]] = field(default_factory=list)
    train_stats: Dict[str, Any] = field(default_factory=dict)

    # ----- inference -----

    def score(self, features: Mapping[str, float]) -> float:
        """Return P(verified | features)."""
        x = vectorise(features, self.index, extend=False)
        z = 0.0
        for i, v in x.items():
            z += self.weights[i] * v
        return _sigmoid(z)

    def score_row(self, row: CandidateRow,
                  *, hashed_dim: Optional[int] = None) -> float:
        feats = extract_features(
            row, hashed_dim=hashed_dim or self.train_config.hashed_dim,
        )
        return self.score(feats)

    # ----- top features (interpretability) -----

    def top_features(self, k: int = 30) -> List[Tuple[str, float]]:
        ranked = sorted(
            ((self.index.id_to_name[i], w)
             for i, w in enumerate(self.weights)),
            key=lambda kv: kv[1], reverse=True,
        )
        return ranked[:k] + ranked[-k:]

    # ----- persistence -----

    def save(self, out_dir: Path) -> None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "config.json").write_text(
            json.dumps(self.train_config.to_jsonable(), indent=2),
            encoding="utf-8")
        (out_dir / "index.json").write_text(
            json.dumps(self.index.to_jsonable(), ensure_ascii=False),
            encoding="utf-8")
        (out_dir / "weights.json").write_text(
            json.dumps(self.weights), encoding="utf-8")
        if self.train_history:
            (out_dir / "train_history.json").write_text(
                json.dumps(self.train_history, indent=2), encoding="utf-8")
        if self.train_stats:
            (out_dir / "train_stats.json").write_text(
                json.dumps(self.train_stats, indent=2, ensure_ascii=False),
                encoding="utf-8")

    @classmethod
    def load(cls, model_dir: Path) -> "LearnedReranker":
        md = Path(model_dir)
        cfg = TrainConfig(**json.loads(
            (md / "config.json").read_text(encoding="utf-8")))
        idx = FeatureIndex.from_dict(json.loads(
            (md / "index.json").read_text(encoding="utf-8")))
        w = json.loads((md / "weights.json").read_text(encoding="utf-8"))
        hist: List[Dict[str, Any]] = []
        stats: Dict[str, Any] = {}
        p_h = md / "train_history.json"
        if p_h.exists():
            hist = json.loads(p_h.read_text(encoding="utf-8"))
        p_s = md / "train_stats.json"
        if p_s.exists():
            stats = json.loads(p_s.read_text(encoding="utf-8"))
        return cls(index=idx, weights=w, train_config=cfg,
                   train_history=hist, train_stats=stats)


# --------------------------------------------------------------------------- #
# Training
# --------------------------------------------------------------------------- #


def _extract_for_rows(rows: Sequence[CandidateRow], cfg: TrainConfig,
                      ) -> List[Dict[str, float]]:
    return [extract_features(r, hashed_dim=cfg.hashed_dim) for r in rows]


def train_reranker(
    train_rows: Sequence[CandidateRow],
    *,
    cfg: Optional[TrainConfig] = None,
    val_rows: Optional[Sequence[CandidateRow]] = None,
) -> LearnedReranker:
    """SGD over a sparse-feature logistic regression with class
    weighting. Returns a fitted :class:`LearnedReranker`.

    Determinism: every call with the same ``train_rows`` ordering and
    same ``cfg.seed`` produces the same weights byte-for-byte.
    """
    cfg = cfg or TrainConfig()
    rng = random.Random(cfg.seed)

    # 1) build index over train features (extend=True)
    index = FeatureIndex()
    train_feats = _extract_for_rows(train_rows, cfg)
    train_x = [vectorise(f, index, extend=True) for f in train_feats]
    train_y = [1.0 if r.verified else 0.0 for r in train_rows]

    if val_rows is not None:
        val_x = [vectorise(f, index, extend=False)
                 for f in _extract_for_rows(val_rows, cfg)]
        val_y = [1.0 if r.verified else 0.0 for r in val_rows]
    else:
        val_x = val_y = None

    w = [0.0] * len(index)

    indices = list(range(len(train_rows)))
    history: List[Dict[str, Any]] = []

    pos_w = cfg.class_weight_positive
    neg_w = 1.0

    for epoch in range(cfg.epochs):
        rng.shuffle(indices)
        total_loss = 0.0
        correct = 0
        for i in indices:
            xi = train_x[i]
            yi = train_y[i]
            z = sum(w[j] * v for j, v in xi.items())
            p = _sigmoid(z)
            err = p - yi
            cw = pos_w if yi == 1.0 else neg_w
            # cross-entropy loss (class-weighted)
            if yi == 1.0:
                loss = -pos_w * math.log(max(p, 1e-12))
            else:
                loss = -neg_w * math.log(max(1.0 - p, 1e-12))
            total_loss += loss
            # SGD step
            scale = cfg.lr * cw
            for j, v in xi.items():
                w[j] -= scale * err * v + cfg.lr * cfg.l2 * w[j]
            if (p >= 0.5) == (yi == 1.0):
                correct += 1
        train_acc = correct / len(indices) if indices else 0.0
        rec = {
            "epoch": epoch,
            "train_loss": total_loss / max(len(indices), 1),
            "train_acc": train_acc,
        }
        if val_x is not None:
            vc = 0
            tp = fp = fn = tn = 0
            for xi, yi in zip(val_x, val_y):
                z = sum(w[j] * v for j, v in xi.items())
                p = _sigmoid(z)
                pred = 1.0 if p >= 0.5 else 0.0
                vc += int(pred == yi)
                if pred == 1.0 and yi == 1.0:
                    tp += 1
                elif pred == 1.0 and yi == 0.0:
                    fp += 1
                elif pred == 0.0 and yi == 1.0:
                    fn += 1
                else:
                    tn += 1
            rec["val_acc"] = vc / max(len(val_y), 1)
            rec["val_tp"] = tp
            rec["val_fp"] = fp
            rec["val_fn"] = fn
            rec["val_tn"] = tn
        history.append(rec)

    model = LearnedReranker(
        index=index, weights=w, train_config=cfg,
        train_history=history,
        train_stats={
            "n_train_rows": len(train_rows),
            "n_features": len(index),
            "positive_fraction_train": (
                sum(train_y) / max(len(train_y), 1)),
            "final_epoch": history[-1] if history else None,
            "uses_state_after": False,
        },
    )
    return model


# --------------------------------------------------------------------------- #
# Reranking API
# --------------------------------------------------------------------------- #


def rerank_candidates(
    model: LearnedReranker,
    candidates: Sequence[CandidateRow],
) -> List[Tuple[CandidateRow, float]]:
    """Return the candidate list ordered best-first by model score.
    Stable on ties (Python sort is stable; we use a tuple key).
    """
    scored = [(c, model.score_row(c)) for c in candidates]
    # Higher score first; on tie, lower beam_rank first.
    scored.sort(key=lambda kv: (-kv[1], kv[0].beam_rank))
    return scored


__all__ = [
    "FeatureIndex",
    "LearnedReranker",
    "TrainConfig",
    "rerank_candidates",
    "train_reranker",
    "vectorise",
]
