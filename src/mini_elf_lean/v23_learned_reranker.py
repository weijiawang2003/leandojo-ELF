"""Mini-ELF v23 — refreshed learned reranker (pure-Python LR).

Same deterministic CPU logistic-regression machinery as the v15
:class:`mini_elf_lean.learned_reranker.LearnedReranker` (reuses its
``FeatureIndex`` / ``vectorise`` / sigmoid / SGD), but over the richer
:func:`mini_elf_lean.v23_reranker_features.extract_v23_features` feature
set and trained on the v22 broad-core candidate-outcome pool.

The model stores its training ``PatternBag`` so the seen-in-train /
category-match features are reproducible at score time. It outputs
P(verified | features); the eval reorders the **original raw-name
candidates** by that probability (with a beam-rank tie-break) — it never
emits a placeholder.

Honesty: no state_after, no manual oracle, no generation change. Leakage
is the caller's responsibility (the v23 eval uses leave-one-theorem-out).
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .abstract_pattern_reranker import PatternBag
from .learned_reranker import FeatureIndex, TrainConfig, _sigmoid, vectorise
from .v23_reranker_features import extract_v23_features


def build_pattern_bag_from_rows(rows: Sequence[Mapping[str, Any]]) -> PatternBag:
    """Pattern bag from the *verified* rows only (mirrors v20's bag:
    verified tactics define the 'good shapes' distribution)."""
    from .identifier_abstraction import abstract_tactic_only
    bag = PatternBag()
    for r in rows:
        if not r.get("verified"):
            continue
        state = r.get("state_before") or ""
        cand = r.get("candidate") or ""
        if not state or not cand:
            continue
        try:
            pat, _ = abstract_tactic_only(state, cand)
        except Exception:  # pragma: no cover
            continue
        bag.add(pat, r.get("category"))
    return bag


@dataclass
class V23Reranker:
    index: FeatureIndex
    weights: List[float]
    train_config: TrainConfig
    pattern_bag: PatternBag = field(default_factory=PatternBag)
    category_features: bool = True
    train_stats: Dict[str, Any] = field(default_factory=dict)

    def features(self, row: Mapping[str, Any]) -> Dict[str, float]:
        return extract_v23_features(row, pattern_bag=self.pattern_bag,
                                    category_features=self.category_features,
                                    hashed_dim=self.train_config.hashed_dim)

    def score_row(self, row: Mapping[str, Any]) -> float:
        x = vectorise(self.features(row), self.index, extend=False)
        z = sum(self.weights[i] * v for i, v in x.items())
        return _sigmoid(z)

    def top_features(self, k: int = 25) -> List[Tuple[str, float]]:
        ranked = sorted(((self.index.id_to_name[i], w)
                         for i, w in enumerate(self.weights)),
                        key=lambda kv: kv[1], reverse=True)
        return ranked[:k] + ranked[-k:]

    # ---- persistence ----
    def save(self, out_dir: Path) -> None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "config.json").write_text(
            json.dumps(self.train_config.to_jsonable(), indent=2), encoding="utf-8")
        (out_dir / "index.json").write_text(
            json.dumps(self.index.to_jsonable(), ensure_ascii=False), encoding="utf-8")
        (out_dir / "weights.json").write_text(json.dumps(self.weights), encoding="utf-8")
        (out_dir / "pattern_bag.json").write_text(
            json.dumps(self.pattern_bag.to_json(), ensure_ascii=False), encoding="utf-8")
        (out_dir / "meta.json").write_text(
            json.dumps({"category_features": self.category_features}), encoding="utf-8")
        if self.train_stats:
            (out_dir / "train_stats.json").write_text(
                json.dumps(self.train_stats, indent=2, ensure_ascii=False),
                encoding="utf-8")

    @classmethod
    def load(cls, model_dir: Path) -> "V23Reranker":
        md = Path(model_dir)
        cfg = TrainConfig(**json.loads((md / "config.json").read_text(encoding="utf-8")))
        idx = FeatureIndex.from_dict(json.loads((md / "index.json").read_text(encoding="utf-8")))
        w = json.loads((md / "weights.json").read_text(encoding="utf-8"))
        bag = PatternBag.from_json(json.loads((md / "pattern_bag.json").read_text(encoding="utf-8")))
        catf = True
        if (md / "meta.json").exists():
            catf = bool(json.loads((md / "meta.json").read_text(encoding="utf-8")).get(
                "category_features", True))
        stats = {}
        if (md / "train_stats.json").exists():
            stats = json.loads((md / "train_stats.json").read_text(encoding="utf-8"))
        return cls(index=idx, weights=w, train_config=cfg, pattern_bag=bag,
                   category_features=catf, train_stats=stats)


def train_v23_reranker(
    rows: Sequence[Mapping[str, Any]], *,
    cfg: Optional[TrainConfig] = None,
    pattern_bag: Optional[PatternBag] = None,
    category_features: bool = True,
) -> V23Reranker:
    """Class-weighted SGD logistic regression over v23 features.
    Deterministic for a fixed ``rows`` order + ``cfg.seed``.
    ``category_features`` toggles config B (False) vs C (True)."""
    cfg = cfg or TrainConfig()
    if pattern_bag is None:
        pattern_bag = build_pattern_bag_from_rows(rows)
    rng = random.Random(cfg.seed)

    index = FeatureIndex()
    feats = [extract_v23_features(r, pattern_bag=pattern_bag,
                                  category_features=category_features,
                                  hashed_dim=cfg.hashed_dim) for r in rows]
    xs = [vectorise(f, index, extend=True) for f in feats]
    ys = [1.0 if r.get("verified") else 0.0 for r in rows]
    w = [0.0] * len(index)
    idxs = list(range(len(rows)))
    pos_w, neg_w = cfg.class_weight_positive, 1.0

    for _ in range(cfg.epochs):
        rng.shuffle(idxs)
        for i in idxs:
            xi, yi = xs[i], ys[i]
            z = sum(w[j] * v for j, v in xi.items())
            p = _sigmoid(z)
            err = p - yi
            cw = pos_w if yi == 1.0 else neg_w
            scale = cfg.lr * cw
            for j, v in xi.items():
                w[j] -= scale * err * v + cfg.lr * cfg.l2 * w[j]

    return V23Reranker(
        index=index, weights=w, train_config=cfg, pattern_bag=pattern_bag,
        category_features=category_features,
        train_stats={"n_train_rows": len(rows), "n_features": len(index),
                     "positive_fraction": sum(ys) / max(len(ys), 1),
                     "category_features": category_features,
                     "uses_state_after": False})


def order_by_score(candidates: Sequence[Mapping[str, Any]],
                   model: V23Reranker) -> List[int]:
    """Return indices best-first by P(verified); ties → lower beam_rank."""
    scored = [(i, model.score_row(c), int(c.get("beam_rank", i)))
              for i, c in enumerate(candidates)]
    scored.sort(key=lambda t: (-t[1], t[2]))
    return [t[0] for t in scored]


__all__ = ["V23Reranker", "train_v23_reranker", "order_by_score",
           "build_pattern_bag_from_rows"]
