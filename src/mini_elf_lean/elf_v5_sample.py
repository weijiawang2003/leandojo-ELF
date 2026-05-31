"""Mini-ELF v5 — proposer fusion over the v3 system.

v5 keeps the v3 system **unchanged** (symbolic planner ⊕ witness-copy ⊕ v2 flow)
and adds *data-driven candidate proposers* (retrieval / LLM / learned) in a new
tier between the symbolic sources and the flow tail. The question is whether a
proposer can supply useful candidates on planner-blind shapes — especially the
template-less `forall_inst` / `rewrite_succ` — without a hand-written rule.

Ranking tiers (per prompt):

  * **Tier 0 — symbolic (from v3, optional):** planner + witness + (when the v4
    ablation flags are on) the explicitly-labelled v4 templates. Constructed to
    typecheck; take the top slots, exactly as v3 ordered them.
  * **Tier 1 — proposers:** each :class:`~mini_elf_lean.proposer.CandidateProposer`
    in order, preserving the proposer's own ranking (retrieval keeps its
    verbatim-then-adapted, similarity-ordered list). This is the v5 contribution.
  * **Tier 2 — flow tail:** the v2 flow pool, so `pass@5` recall never drops
    below v3.

Dedup is first-source-wins, so a symbolic proof keeps its high tier even if a
proposer or the flow re-proposes the same string. With ``v3=None`` the baseline
is just the proposer tier (used for "retrieval alone").

Honest scope, unchanged: theorem-level verification only; no ``state_after`` is
read; manual-oracle candidates are never wired in here (they are audit-only).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .baselines import Baseline, Example
from .proposer import CandidateProposer

# Mirror of :data:`mini_elf_lean.elf_v1_sample.FLOW_SOURCE`; defined locally so
# this fusion module stays torch-free (the v3 model is passed in by reference).
FLOW_SOURCE = "flow_decoder"


class MiniElfV5Baseline(Baseline):
    name = "mini_elf_v5"

    def __init__(
        self,
        *,
        v3: Optional[Any] = None,
        proposers: Optional[Sequence[CandidateProposer]] = None,
        proposer_max: int = 12,
        label: Optional[str] = None,
    ) -> None:
        self.v3 = v3
        self.proposers: List[CandidateProposer] = list(proposers or [])
        self.proposer_max = proposer_max
        self._label = label

    @property
    def mode(self) -> str:
        bits: List[str] = []
        if self.v3 is not None:
            bits.append(self.v3.mode)
        bits.extend(getattr(p, "mode", p.name) for p in self.proposers)
        inner = " ⊕ ".join(bits) if bits else "empty"
        return f"v5({inner})"

    def fit(self, train: Sequence[Example]) -> "MiniElfV5Baseline":
        # v3 (if present) is pre-trained; only the data-driven proposers index train.
        for p in self.proposers:
            p.fit(train)
        return self

    # ---- candidate fusion ----

    def _proposer_items(self, example: Example, seen: set) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        family = getattr(example, "pattern_family", None)
        for p in self.proposers:
            cands = p.propose(
                example.theorem_statement, example.state_before,
                theorem_name=example.theorem_name, pattern_family=family,
                max_candidates=self.proposer_max,
            )
            for c in cands:
                if c.tactic in seen:
                    continue
                seen.add(c.tactic)
                items.append({
                    "tactic": c.tactic, "source": c.source,
                    "sample_count": 0, "reranker_score": None,
                    "score": c.score,
                    "strategy": c.metadata.get("adaptation") or c.metadata.get("strategy"),
                    "metadata": c.metadata,
                })
        return items

    def ranked_candidates(self, example: Example) -> List[Dict[str, Any]]:
        seen: set = set()
        symbolic: List[Dict[str, Any]] = []
        flow: List[Dict[str, Any]] = []
        if self.v3 is not None:
            for it in self.v3.ranked_candidates(example):
                (flow if it.get("source") == FLOW_SOURCE else symbolic).append(it)
                seen.add(it["tactic"])
        proposer_items = self._proposer_items(example, seen)
        return symbolic + proposer_items + flow

    # ---- Baseline interface ----

    def predict(self, example: Example, *, k: int) -> List[str]:
        return [it["tactic"] for it in self.ranked_candidates(example)[:k]]

    def predict_with_neighbors(
        self, example: Example, *, k: int
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        ranked = self.ranked_candidates(example)[:k]
        preds = [it["tactic"] for it in ranked]
        prov = [{"source": it.get("source"), "reranker_score": it.get("reranker_score"),
                 "sample_count": it.get("sample_count", 0), "score": it.get("score"),
                 "strategy": it.get("strategy"), "metadata": it.get("metadata", {})}
                for it in ranked]
        return preds, prov

    def distinct_candidate_count(self, example: Example) -> int:
        return len(self.ranked_candidates(example))

    def proposer_candidate_count(self, example: Example) -> int:
        return len(self._proposer_items(example, set()))
