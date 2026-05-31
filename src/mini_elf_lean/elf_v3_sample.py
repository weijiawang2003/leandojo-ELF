"""Mini-ELF v3 — candidate fusion: structured planner ⊕ Mini-ELF v2 ⊕ witness.

v3 keeps the entire v2 model (denoising AE + flow generator + verifier-aware
reranker + witness-copy) and *adds* the symbolic proof-block planner
(:mod:`mini_elf_lean.proof_planner`) as a new, high-precision candidate source.

Per prompt the v3 baseline:

  1. Generates flow-decoder candidates from the v2 model (``flow_decoder``).
  2. Generates witness-copy candidates for ∃-goals (``witness_copy``).
  3. Generates structured proof-block candidates from the planner
     (``planner_chain`` / ``planner_projection`` / ``planner_cases`` /
     ``planner_eq`` / ``planner_iff`` / ``planner_template``).
  4. Merges + deduplicates (first source wins) and ranks in tiers:

       * **Tier 0** — symbolic, high-precision: planner candidates (ordered by
         the planner's own confidence priority, ties broken by the v2 reranker
         score) followed by witness-copy candidates. These are *constructed* to
         typecheck, so they take the top slots.
       * **Tier 1** — the v2 reranked flow pool (top ``rerank_pool`` flow
         candidates by frequency + any leftover witnesses), reordered by the
         frequency-blended v2 reranker score, exactly as v2 did.
       * **Tier 2** — the remaining flow candidates in frequency order, so
         ``pass@5`` recall is never reduced relative to v2.

Why a tier policy rather than "rerank everything": v2 showed the learned
reranker **mis-calibrates off-distribution** (verified/failed scores collapse
together), so letting it order the planner's correct multi-step blocks against
flow garble would lose them. The planner is deterministic and symbolic, so its
candidates are trustworthy and go first — but the reranker score is still
recorded on every candidate for the calibration analysis.

Honest scope, unchanged: theorem-level verification only
(``state_after_is_real=false``); the planner is symbolic/heuristic, not neural
generation; this is **not** full ELF over proof states.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from .baselines import Baseline, Example
from .elf_v1_sample import FLOW_SOURCE, NN_SOURCE, MiniElfV1Baseline
from .elf_witness import WITNESS_SOURCE, witness_candidates_for
from .proof_planner import PLANNER_SOURCES, plan_candidates


class MiniElfV3Baseline(Baseline):
    """Planner-augmented fusion over a loaded :class:`MiniElfV1Baseline` (the v2
    model). ``fit`` is a no-op — the v2 model + reranker are trained offline and
    the planner is rule-based."""

    name = "mini_elf_v3"

    def __init__(
        self,
        v2: MiniElfV1Baseline,
        *,
        use_planner: bool = True,
        planner_max: int = 24,
        enable_negation_templates: bool = False,
        enable_exists_elim_templates: bool = False,
    ) -> None:
        self.v2 = v2
        self.use_planner = use_planner
        self.planner_max = planner_max
        # V4 ablation: optional, explicitly-labelled template extensions
        # (`proof_planner_v4`). Off by default so the unchanged-v3 planner-blind
        # robustness test is honest.
        self.enable_negation_templates = enable_negation_templates
        self.enable_exists_elim_templates = enable_exists_elim_templates

    @property
    def mode(self) -> str:
        bits = ["planner" if self.use_planner else "no_planner"]
        if self.enable_negation_templates:
            bits.append("v4_negation")
        if self.enable_exists_elim_templates:
            bits.append("v4_exists_elim")
        bits.append(self.v2.mode)
        return "v3(" + ",".join(bits) + ")"

    @property
    def n_samples(self) -> int:
        """Delegates to the wrapped v2 model (read by the shared generation
        stats helper)."""
        return self.v2.n_samples

    def fit(self, train) -> "MiniElfV3Baseline":  # noqa: ARG002 - pre-trained
        return self

    # ---- candidate sources ----

    def _planner_items(self, example: Example) -> List[Dict[str, Any]]:
        if not self.use_planner:
            return []
        family = getattr(example, "pattern_family", None)
        cands = list(plan_candidates(
            example.theorem_statement, example.state_before,
            pattern_family=family, max_candidates=self.planner_max,
        ))
        if self.enable_negation_templates or self.enable_exists_elim_templates:
            from .proof_planner_v4 import v4_extra_candidates
            cands += v4_extra_candidates(
                example.theorem_statement, example.state_before, pattern_family=family,
                enable_negation=self.enable_negation_templates,
                enable_exists_elim=self.enable_exists_elim_templates,
            )
        seen: set = set()
        items: List[Dict[str, Any]] = []
        for c in cands:
            if c.tactic in seen:
                continue
            seen.add(c.tactic)
            items.append({"tactic": c.tactic, "source": c.source, "strategy": c.strategy,
                          "priority": c.priority, "sample_count": 0, "reranker_score": None})
        return items

    def ranked_candidates(self, example: Example) -> List[Dict[str, Any]]:
        v2 = self.v2
        src = NN_SOURCE if v2.decode == "nn" else FLOW_SOURCE
        seen: set = set()

        # Planner claims dedup first (it is the highest-precision tier), then
        # witness, then the flow generator gets whatever is left. This keeps a
        # planner/witness-constructed proof in its high tier even when the flow
        # happened to sample the same string.
        planner_items: List[Dict[str, Any]] = []
        for it in self._planner_items(example):
            if it["tactic"] in seen:
                continue
            seen.add(it["tactic"])
            planner_items.append(it)

        witness_items: List[Dict[str, Any]] = []
        if v2.use_witness:
            family = getattr(example, "pattern_family", None)
            for tac in witness_candidates_for(example.theorem_statement, example.state_before, family):
                if tac in seen:
                    continue
                seen.add(tac)
                witness_items.append({"tactic": tac, "source": WITNESS_SOURCE,
                                      "sample_count": 0, "reranker_score": None, "strategy": None})

        flow_items: List[Dict[str, Any]] = []
        for tac, cnt in v2._flow_candidates(example.theorem_statement, example.state_before):
            if tac in seen:
                continue
            seen.add(tac)
            flow_items.append({"tactic": tac, "source": src, "sample_count": cnt,
                               "reranker_score": None, "strategy": None})

        family = getattr(example, "pattern_family", None)
        if not (v2.use_reranker and v2.reranker is not None):
            planner_items.sort(key=lambda it: (it.get("priority", 99), len(it["tactic"]), it["tactic"]))
            flow_sorted = sorted(flow_items, key=lambda it: (-it["sample_count"], it["tactic"]))
            return planner_items + witness_items + flow_sorted

        reranker = v2.reranker
        # Record reranker scores on the symbolic (tier-0) candidates for the
        # calibration analysis, but DO NOT let them reorder against flow.
        symbolic = planner_items + witness_items
        if symbolic:
            sym_scores = reranker.score_batch(
                example.theorem_statement, example.state_before,
                [it["tactic"] for it in symbolic], family=family,
            )
            for it, sc in zip(symbolic, sym_scores):
                it["reranker_score"] = float(sc)

        # Tier 1: v2's frequency-blended rerank of the flow pool.
        pool = flow_items[: v2.rerank_pool]
        tail = flow_items[v2.rerank_pool :]
        if pool:
            scores = reranker.score_batch(
                example.theorem_statement, example.state_before,
                [it["tactic"] for it in pool], family=family,
            )
            max_cnt = max((it["sample_count"] for it in pool), default=0) or 1
            for it, sc in zip(pool, scores):
                it["reranker_score"] = float(sc)
                it["_blend"] = sc + v2.rerank_blend * (it["sample_count"] / max_cnt)
            pool.sort(key=lambda it: (-it["_blend"], it["tactic"]))
            for it in pool:
                it.pop("_blend", None)

        # Tier 0: planner by (priority, reranker_score desc), then witness.
        planner_items.sort(
            key=lambda it: (it.get("priority", 99), -(it["reranker_score"] or 0.0), it["tactic"]))
        return planner_items + witness_items + pool + tail

    # ---- Baseline interface ----

    def predict(self, example: Example, *, k: int) -> List[str]:
        return [it["tactic"] for it in self.ranked_candidates(example)[:k]]

    def predict_with_neighbors(
        self, example: Example, *, k: int
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        ranked = self.ranked_candidates(example)[:k]
        preds = [it["tactic"] for it in ranked]
        prov = [{"source": it["source"], "reranker_score": it["reranker_score"],
                 "sample_count": it["sample_count"], "strategy": it.get("strategy")}
                for it in ranked]
        return preds, prov

    def distinct_flow_candidates(self, example: Example) -> int:
        return self.v2.distinct_flow_candidates(example)

    def planner_candidate_count(self, example: Example) -> int:
        return len(self._planner_items(example))

    # ---- persistence ----

    @classmethod
    def load(
        cls,
        model_dir: Path,
        *,
        n_samples: int = 64,
        steps: int = 10,
        seed: int = 0,
        use_witness: bool = True,
        use_reranker: bool = True,
        use_planner: bool = True,
        planner_max: int = 24,
        enable_negation_templates: bool = False,
        enable_exists_elim_templates: bool = False,
        device: str = "cpu",
    ) -> "MiniElfV3Baseline":
        v2 = MiniElfV1Baseline.load(
            model_dir, n_samples=n_samples, steps=steps, seed=seed,
            decode="decoder", use_witness=use_witness, use_reranker=use_reranker,
            device=device,
        )
        return cls(v2, use_planner=use_planner, planner_max=planner_max,
                   enable_negation_templates=enable_negation_templates,
                   enable_exists_elim_templates=enable_exists_elim_templates)


# Sources that the v3 fusion can emit (for source-breakdown reporting).
V3_SOURCES: Tuple[str, ...] = (FLOW_SOURCE, WITNESS_SOURCE, *PLANNER_SOURCES)
