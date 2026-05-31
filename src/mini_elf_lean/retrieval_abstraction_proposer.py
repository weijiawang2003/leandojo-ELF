"""Mini-ELF v7 — abstraction-aware cross-family retrieval re-ranker.

The Part-1 audit showed v6 has **zero** cross-family transfer: forbidding
same-family donors drops pass@5 to 0.00 because the nearest cross-family donor's
*concrete* tactic string does not fit the target (wrong identifiers, or a tactic
shape the target's hypotheses can't support). This proposer adds the one
template-free lever left: **role-based re-concretization**.

For each donor it keeps v6's verbatim + numeric + hyp-remap candidates, and adds a
candidate built by *abstracting* the donor tactic to operation roles
(`exact absurd <prop_hyp> <neg_hyp>`) and re-binding each role slot to the
**target's** own hypotheses of that role (and `<num>` to a target goal literal).
This generalises v6's `hyp_remap` from "same type" to "same proof role", so a
donor that performs the target's operation can transfer even across families —
**when** the target actually has a hypothesis for every role the donor consumes.
It re-concretises only *flat* donor tactics (no bound-variable `<id>` slots);
multi-line `intro`/`rcases`/`obtain` blocks are kept verbatim.

Scoring is conservative (the brief's rule): a re-concretised candidate is nudged
up only when the donor's required-operation matches the target's, and penalised
otherwise. The candidate string still originates from a verified donor proof —
this is retrieval + re-binding, **not** a hand-written template, and never reads
`state_after`. The lean-cli verifier remains the sole arbiter.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .retrieval_abstraction import abstract_tactic, hyp_roles, operation_signature
from .retrieval_features import OP_UNKNOWN, StateFeatures, extract_features
from .retrieval_proposer import (
    RETRIEVAL_ADAPTED_SOURCE,
    RETRIEVAL_SOURCE,
    StructureAwareRetrievalProposer,
    _query_literals,
)

RECONCRETIZED_SOURCE = "retrieval_reconcretized"

_ROLE_PLACEHOLDER_RE = re.compile(r"<(forall|exists|neg|imp|eq|and|or|prop)_hyp>")
_NUM_PLACEHOLDER = "<num>"
# Default abstraction-specific scoring deltas (kept off the v6 weight file so v6
# results are untouched; tunable via the constructor).
_BONUS_RECONCRETIZE_OP_MATCH = 0.5
_PEN_RECONCRETIZE_OP_MISMATCH = 0.75


def reconcretize(abstract: str, role_to_names: Dict[str, List[str]],
                 goal_literal: Optional[str]) -> Optional[str]:
    """Re-bind an abstract *flat* tactic to a target's hypotheses.

    Each ``<role_hyp>`` placeholder is mapped to a target hypothesis of that role
    (distinct occurrences to distinct hyps, in order); ``<num>`` to ``goal_literal``.
    Returns ``None`` if the abstract tactic carries a bound-var ``<id>`` slot, or
    the target lacks enough hypotheses of some role, or a needed literal — i.e.
    only fully, unambiguously concretisable tactics are produced."""
    if "<id>" in abstract:
        return None  # bound-variable slot we cannot safely fill
    if _NUM_PLACEHOLDER in abstract and not goal_literal:
        return None
    # assign distinct target hyps to repeated occurrences of the same role
    used: Dict[str, int] = {}
    out_parts: List[str] = []
    pos = 0
    for m in _ROLE_PLACEHOLDER_RE.finditer(abstract):
        role = m.group(1)
        names = role_to_names.get(role, [])
        idx = used.get(role, 0)
        if idx >= len(names):
            return None  # not enough distinct target hyps of this role
        out_parts.append(abstract[pos:m.start()])
        out_parts.append(names[idx])
        used[role] = idx + 1
        pos = m.end()
    out_parts.append(abstract[pos:])
    concrete = "".join(out_parts)
    if goal_literal is not None:
        concrete = concrete.replace(_NUM_PLACEHOLDER, goal_literal)
    if "<" in concrete:  # an un-fillable placeholder remained
        return None
    return concrete


def _role_to_names(state_before: str) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for name, role in hyp_roles(state_before).items():
        out.setdefault(role, []).append(name)
    # deterministic order so re-concretisation is stable
    for role in out:
        out[role].sort()
    return out


class AbstractionAwareRetrievalProposer(StructureAwareRetrievalProposer):
    """v6 retrieval + role-based re-concretisation of cross-family donors."""

    name = "retrieval_v7_abstract"

    def __init__(self, *args, enable_reconcretize: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.enable_reconcretize = enable_reconcretize

    @property
    def mode(self) -> str:
        base = super().mode  # retrieval_v6(...)
        inner = base[len("retrieval_v6("):-1]
        bits = inner.split(",") if inner else []
        if self.enable_reconcretize:
            bits.append("reconcretize")
        return "retrieval_v7(" + ",".join(bits) + ")"

    def _candidate_variants(self, d, query_lits, query_state) -> List[Tuple[str, str, Dict[str, Any]]]:
        out = super()._candidate_variants(d, query_lits, query_state)
        if not self.enable_reconcretize:
            return out
        abstract = abstract_tactic(d.tactic, d.state_before)
        if "<" not in abstract:  # nothing to re-bind (no roles / num)
            return out
        role_to_names = _role_to_names(query_state)
        goal_lit = query_lits[0] if query_lits else None
        concrete = reconcretize(abstract, role_to_names, goal_lit)
        existing = {t for t, _s, _m in out}
        if concrete and concrete not in existing:
            out.append((concrete, RECONCRETIZED_SOURCE,
                        {"adapted": True, "adaptation_kind": "role_reconcretize",
                         "abstract": abstract}))
        return out

    def _candidate_adjustment(self, tac, adapted, tf: StateFeatures, query_lits) -> float:
        adj = super()._candidate_adjustment(tac, adapted, tf, query_lits)
        return adj  # base handles verbatim/numeric/intro/contradiction terms

    # re-concretised candidates need a donor-operation-aware nudge, which requires
    # the donor features; the parent computes the per-candidate adjustment without
    # them, so we apply the reconcretize bonus in `propose` via metadata instead.
    def propose(self, theorem_statement, state_before, *, theorem_name=None,
                pattern_family=None, max_candidates=10):
        # Reuse the parent ranking, then apply a conservative re-concretisation
        # adjustment keyed on each candidate's source/metadata + the target op.
        tf = extract_features(theorem_statement, state_before)
        cands = super().propose(theorem_statement, state_before, theorem_name=theorem_name,
                                pattern_family=pattern_family,
                                max_candidates=max(max_candidates * 3, 30))
        if not cands:
            return []
        target_op = tf.required_operation
        for c in cands:
            if c.source != RECONCRETIZED_SOURCE:
                continue
            donor_op = (c.metadata or {}).get("donor_operation")
            bump = (_BONUS_RECONCRETIZE_OP_MATCH
                    if (donor_op and target_op != OP_UNKNOWN and donor_op == target_op)
                    else -_PEN_RECONCRETIZE_OP_MISMATCH)
            c.score = (c.score or 0.0) + bump
            c.metadata = {**(c.metadata or {}), "reconcretize_bump": round(bump, 3)}
        cands.sort(key=lambda c: -(c.score or 0.0))
        # de-dup preserved by parent; just trim
        return cands[:max_candidates]
