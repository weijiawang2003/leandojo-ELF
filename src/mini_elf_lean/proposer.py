"""Mini-ELF v5 — a common *candidate-proposer* interface.

v4 proved the v3 symbolic planner is a closed catalog: off-library proof shapes
(`forall_inst`, `rewrite_succ`, …) collapse to `pass@5` 0.096, and the only way
to recover them was hand-authoring a template per shape (whack-a-mole). v5 asks
whether a *data-driven* proposer (retrieval / LLM / learned) can produce useful
proof blocks **without** a per-shape template.

To compare candidate sources cleanly, every source is wrapped behind one
interface:

  * :class:`ProposedCandidate` — a typed candidate (``tactic`` + ``source`` +
    optional ``score`` + ``metadata``).
  * :class:`CandidateProposer` — ``propose(theorem_statement, state_before, …)``
    returns a ranked list of :class:`ProposedCandidate`; ``fit(train)`` is a
    no-op for stateless proposers and trains the index for retrieval/learned.

Concrete proposers:

  * :class:`ExistingFlowProposer`  — the Mini-ELF v2 flow generator.
  * :class:`PlannerProposer`       — the v3 symbolic planner (unchanged).
  * :class:`WitnessProposer`       — the symbolic witness-copy augmenter.
  * :class:`ManualCandidateProposer` — the hand-authored corpus candidates,
    **oracle/audit only** (never counted as a model result).
  * :class:`~mini_elf_lean.llm_proposer.LLMProposer` — optional, API-key-gated.
  * :class:`~mini_elf_lean.retrieval_proposer.RetrievalProofBlockProposer` —
    train-free example reuse + light adaptation.

Honest scope, unchanged: theorem-level verification only
(``state_after_is_real=false``); no ``state_after`` is ever read; these are
prototypes of the *generation loop*, not full ELF over proof states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Source labels. Symbolic/existing sources reuse the established labels so the
# v5 source-breakdown lines up with v1–v4 reporting. ``FLOW_SOURCE`` mirrors
# :data:`mini_elf_lean.elf_v1_sample.FLOW_SOURCE` but is defined locally to keep
# this interface module torch-free (the flow generator is held by reference, not
# imported here).
from .elf_witness import WITNESS_SOURCE, witness_candidates_for
from .proof_planner import plan_candidates

FLOW_SOURCE = "flow_decoder"
MANUAL_ORACLE_SOURCE = "manual_oracle"


@dataclass
class ProposedCandidate:
    """One proposed tactic plus provenance. ``score`` is the proposer's own
    confidence (higher = better) or ``None`` when a proposer has no meaningful
    ordering signal. ``metadata`` carries source-specific detail (neighbour
    theorem, adaptation kind, planner strategy, …) for the audit trail."""

    tactic: str
    source: str
    score: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class CandidateProposer:
    """Common interface. Subclasses override :meth:`propose`; :meth:`fit` is a
    no-op unless the proposer needs a training index."""

    #: Stable name used in reporting / config strings.
    name: str = "proposer"

    def fit(self, train: Sequence[Any]) -> "CandidateProposer":
        """Consume training examples (rows with ``.theorem_statement`` /
        ``.state_before`` / ``.tactic``). Stateless proposers ignore it."""
        return self

    def propose(
        self,
        theorem_statement: str,
        state_before: str,
        *,
        theorem_name: Optional[str] = None,
        pattern_family: Optional[str] = None,
        max_candidates: int = 10,
    ) -> List[ProposedCandidate]:  # pragma: no cover - interface
        raise NotImplementedError


def dedup_candidates(cands: Sequence[ProposedCandidate]) -> List[ProposedCandidate]:
    """Deduplicate by tactic string, **first occurrence wins** so the
    higher-priority source keeps the candidate (and its provenance). Order is
    preserved."""
    seen: set = set()
    out: List[ProposedCandidate] = []
    for c in cands:
        if c.tactic in seen:
            continue
        seen.add(c.tactic)
        out.append(c)
    return out


# ---------------- existing / symbolic source wrappers ----------------


class ExistingFlowProposer(CandidateProposer):
    """Wrap the Mini-ELF v2 flow generator (``flow_decoder`` candidates).

    Holds an already-loaded :class:`~mini_elf_lean.elf_v1_sample.MiniElfV1Baseline`
    (the v2 model); ``score`` is the flow sample frequency."""

    name = "flow"

    def __init__(self, v2: Any) -> None:
        self.v2 = v2

    def propose(
        self,
        theorem_statement: str,
        state_before: str,
        *,
        theorem_name: Optional[str] = None,
        pattern_family: Optional[str] = None,
        max_candidates: int = 10,
    ) -> List[ProposedCandidate]:
        out: List[ProposedCandidate] = []
        for tac, cnt in self.v2._flow_candidates(theorem_statement, state_before):
            out.append(ProposedCandidate(tactic=tac, source=FLOW_SOURCE,
                                         score=float(cnt), metadata={"sample_count": int(cnt)}))
            if len(out) >= max_candidates:
                break
        return out


class PlannerProposer(CandidateProposer):
    """Wrap the v3 symbolic planner **unchanged** (`proof_planner.plan_candidates`)."""

    name = "planner"

    def __init__(self, planner_max: int = 24) -> None:
        self.planner_max = planner_max

    def propose(
        self,
        theorem_statement: str,
        state_before: str,
        *,
        theorem_name: Optional[str] = None,
        pattern_family: Optional[str] = None,
        max_candidates: int = 10,
    ) -> List[ProposedCandidate]:
        cands = plan_candidates(
            theorem_statement, state_before,
            pattern_family=pattern_family, max_candidates=self.planner_max,
        )
        out = [
            ProposedCandidate(
                tactic=c.tactic, source=c.source,
                score=-float(c.priority),  # lower priority = more confident
                metadata={"strategy": c.strategy, "priority": c.priority},
            )
            for c in cands
        ]
        return out[:max_candidates]


class WitnessProposer(CandidateProposer):
    """Wrap the symbolic witness-copy augmenter (`elf_witness`)."""

    name = "witness"

    def propose(
        self,
        theorem_statement: str,
        state_before: str,
        *,
        theorem_name: Optional[str] = None,
        pattern_family: Optional[str] = None,
        max_candidates: int = 10,
    ) -> List[ProposedCandidate]:
        tacs = witness_candidates_for(theorem_statement, state_before, pattern_family)
        return [ProposedCandidate(tactic=t, source=WITNESS_SOURCE, score=None)
                for t in tacs[:max_candidates]]


class ManualCandidateProposer(CandidateProposer):
    """Serve the hand-authored corpus candidates for a theorem.

    **Oracle / audit only** — never counted as a model result (the unified eval
    keeps it out of every reported configuration). Useful as an upper bound and
    for verifying the verification path. Reads a manual-candidates JSONL keyed by
    ``theorem_name`` (the same files the collector consumes)."""

    name = "manual_oracle"

    def __init__(self, candidates_path: str | Path) -> None:
        from .io_utils import read_jsonl
        self._by_name: Dict[str, List[str]] = {}
        path = Path(candidates_path)
        if path.exists():
            for row in read_jsonl(path):
                name = row.get("theorem_name")
                cands = row.get("candidates") or []
                if name and cands:
                    self._by_name.setdefault(name, []).extend(cands)

    def propose(
        self,
        theorem_statement: str,
        state_before: str,
        *,
        theorem_name: Optional[str] = None,
        pattern_family: Optional[str] = None,
        max_candidates: int = 10,
    ) -> List[ProposedCandidate]:
        if theorem_name is None:
            return []
        seen: set = set()
        out: List[ProposedCandidate] = []
        for t in self._by_name.get(theorem_name, []):
            if t in seen:
                continue
            seen.add(t)
            out.append(ProposedCandidate(tactic=t, source=MANUAL_ORACLE_SOURCE, score=None))
            if len(out) >= max_candidates:
                break
        return out


# ---------------- lazy re-exports (defined in their own modules) ----------------
# RetrievalProofBlockProposer / LLMProposer import this module for their base
# classes, so importing them eagerly here would be a circular import (and would
# break when *they* are imported first). PEP-562 module __getattr__ defers the
# import until the name is actually accessed, by which point this module is fully
# initialised — `from mini_elf_lean.proposer import LLMProposer` still works.

def __getattr__(name: str):  # noqa: D401
    if name == "RetrievalProofBlockProposer":
        from .retrieval_proposer import RetrievalProofBlockProposer
        return RetrievalProofBlockProposer
    if name == "StructureAwareRetrievalProposer":
        from .retrieval_proposer import StructureAwareRetrievalProposer
        return StructureAwareRetrievalProposer
    if name == "LLMProposer":
        from .llm_proposer import LLMProposer
        return LLMProposer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ProposedCandidate",
    "CandidateProposer",
    "dedup_candidates",
    "ExistingFlowProposer",
    "PlannerProposer",
    "WitnessProposer",
    "ManualCandidateProposer",
    "RetrievalProofBlockProposer",
    "StructureAwareRetrievalProposer",
    "LLMProposer",
    "MANUAL_ORACLE_SOURCE",
]
