"""Mini-ELF v4 — *optional, explicitly-labelled* planner template extensions.

This module is the **controlled template-addition ablation** (V4 Part 5). It is
**not** folded into the v3 planner (`proof_planner.py`, which stays unchanged for
the honest planner-blind robustness test). It adds two new symbolic template
families, each behind its own flag and its own source label, so the *marginal*
value of extending symbolic coverage can be measured per family:

  * ``planner_negation`` — ex-falso / contradiction (`absurd`, `(h x).elim`,
    `contradiction`), contrapositive `¬`-goals, ex-falso inside an implication,
    double-negation introduction, and negation inside a `∨`-case-split.
  * ``planner_exists_elim`` — destructure a `∃`-hypothesis (`rcases`/`obtain`)
    and discharge the goal from the bound body.

Both reuse the v3 parser + backward prover (`parse_planner_state`, `_Prover`), so
they construct only proofs the prover can justify. The point of the ablation is
honesty: these are *more hand-written templates*, measuring engineered symbolic
coverage — **not** learned reasoning. Theorem-level; never reads ``state_after``.
"""

from __future__ import annotations

import dataclasses
from typing import List, Optional, Tuple

from .proof_planner import (
    PlannerCandidate,
    _CASE_POOL,
    _Prover,
    _app,
    _block,
    _classify_prop,
    _depth0_find,
    _existing_identifiers,
    _fresh_names,
    _norm,
    _peel_arrows,
    _wrap,
    parse_planner_state,
)

PLANNER_NEGATION = "planner_negation"
PLANNER_EXISTS_ELIM = "planner_exists_elim"
V4_TEMPLATE_SOURCES: Tuple[str, ...] = (PLANNER_NEGATION, PLANNER_EXISTS_ELIM)


# ---------------- negation / contradiction ----------------


def _false_terms(state, extra_terms: List[Tuple[str, str]]) -> List[Tuple[str, str, str]]:
    """All ways to derive ``False`` from the hypotheses (+ ``extra_terms``).

    Returns ``(false_proof, witness_proof, neg_name)`` tuples: a negation
    hypothesis ``neg_name : ¬X`` (or ``X → False``) applied to a proof
    ``witness_proof`` of ``X`` yields ``false_proof : False``."""
    combined = [(h.name, h.type) for h in state.hyps] + list(extra_terms)
    negs: List[Tuple[str, str]] = []
    for name, ty in combined:
        t = ty.strip()
        if t.startswith("¬"):
            negs.append((name, t[1:].strip()))
        else:
            kind, parts = _classify_prop(t)
            if kind == "imp" and parts and _norm(parts[1]) == "False":
                negs.append((name, parts[0]))
    prover = _Prover(state, extra_terms=extra_terms)
    out: List[Tuple[str, str, str]] = []
    seen: set = set()
    for tname, X in negs:
        for px, _ in prover.prove(X):
            ft = _app(tname, px)
            if ft not in seen:
                seen.add(ft)
                out.append((ft, px, tname))
    return out


def negation_candidates(state) -> List[PlannerCandidate]:
    out: List[PlannerCandidate] = []
    goal = state.goal.strip()

    # (a) ¬-goal: intro the inner prop, then derive False.
    if goal.startswith("¬"):
        inner = goal[1:].strip()
        nm = _fresh_names(1, _existing_identifiers(state))[0]
        for ft, _px, _t in _false_terms(state, [(nm, inner)]):
            out.append(PlannerCandidate(_block(f"intro {nm}", f"exact {ft}"),
                                        PLANNER_NEGATION, "neg_contrapositive", 34))
            out.append(PlannerCandidate(f"exact fun {nm} => {ft}",
                                        PLANNER_NEGATION, "neg_contrapositive_lambda", 35))
        return out

    # (b) implication goal whose antecedents make the context contradictory.
    ants, _cons = _peel_arrows(goal)
    if ants:
        names = _fresh_names(len(ants), _existing_identifiers(state))
        extra = list(zip(names, ants))
        fts = _false_terms(state, extra)
        ns = " ".join(names)
        for ft, px, t in fts:
            out.append(PlannerCandidate(_block(f"intro {ns}", f"exact ({ft}).elim"),
                                        PLANNER_NEGATION, "neg_imp_exfalso", 36))
            out.append(PlannerCandidate(_block(f"intro {ns}", f"exact absurd {_wrap(px)} {t}"),
                                        PLANNER_NEGATION, "neg_imp_absurd", 37))
        if fts:
            out.append(PlannerCandidate(_block(f"intro {ns}", "contradiction"),
                                        PLANNER_NEGATION, "neg_imp_contradiction", 38))
        if out:
            return out

    # (c) plain ex-falso for an arbitrary current goal.
    fts = _false_terms(state, [])
    for ft, px, t in fts:
        out.append(PlannerCandidate(f"exact ({ft}).elim", PLANNER_NEGATION, "exfalso_elim", 16))
        out.append(PlannerCandidate(f"exact False.elim ({ft})", PLANNER_NEGATION, "exfalso_false_elim", 17))
        out.append(PlannerCandidate(f"exact absurd {_wrap(px)} {t}", PLANNER_NEGATION, "exfalso_absurd", 16))
    if fts:
        out.append(PlannerCandidate("contradiction", PLANNER_NEGATION, "exfalso_contradiction", 15))

    # (d) negation inside a ∨-case-split (one branch is contradictory).
    out.extend(_neg_or_cases(state))
    return out


def _neg_or_cases(state) -> List[PlannerCandidate]:
    out: List[PlannerCandidate] = []
    binder = _fresh_names(1, _existing_identifiers(state), _CASE_POOL)[0]
    goal = state.goal

    def branch(disjunct: str) -> Optional[str]:
        pr = _Prover(state, extra_terms=[(binder, disjunct)])
        ps = pr.prove(goal)
        if ps:
            return f"exact {ps[0][0]}"
        fts = _false_terms(state, [(binder, disjunct)])
        if fts:
            return f"exact ({fts[0][0]}).elim"
        return None

    for h in state.or_hyps:
        if h.parts is None:
            continue
        a, b = h.parts
        ba, bb = branch(a), branch(b)
        if ba and bb:
            out.append(PlannerCandidate(
                _block(f"cases {h.name} with", f"| inl {binder} => {ba}", f"| inr {binder} => {bb}"),
                PLANNER_NEGATION, "neg_or_cases", 40))
            out.append(PlannerCandidate(
                _block(f"rcases {h.name} with {binder} | {binder}", ba, bb),
                PLANNER_NEGATION, "neg_or_rcases", 41))
    return out


# ---------------- exists elimination ----------------


def _exists_body(ty: str) -> Optional[str]:
    """Body of an existential type: ``∃ _ : Nat, p ∧ q`` -> ``p ∧ q``."""
    t = ty.strip()
    if not (t.startswith("∃") or t.startswith("Exists")):
        return None
    idx = _depth0_find(t, ",")
    if idx < 0:
        return None
    return t[idx + 1:].strip()


def _proj_terms(name: str, ty: str, depth: int = 3) -> List[Tuple[str, str]]:
    """``(term, type)`` for ``name : ty`` plus every conjunction projection of it
    (so a destructured body ``hb : p ∧ q`` yields ``hb.1 : p``, ``hb.2 : q``)."""
    out = [(name, ty)]
    kind, parts = _classify_prop(ty)
    if kind == "and" and parts and depth > 0:
        lhs, rhs = parts
        out += _proj_terms(f"{name}.1", lhs, depth - 1)
        out += _proj_terms(f"{name}.2", rhs, depth - 1)
    return out


def exists_elim_candidates(state) -> List[PlannerCandidate]:
    out: List[PlannerCandidate] = []
    goal = state.goal.strip()
    if goal.startswith("∃") or goal.startswith("Exists"):
        return out  # goal-side ∃ stays with witness-copy
    nvar, hb = _fresh_names(2, _existing_identifiers(state))
    for h in state.hyps:
        body = _exists_body(h.type)
        if body is None:
            continue
        # Prove from the destructured body only — drop the ∃-hyp from the prover's
        # view so its mis-parsed `.1/.2` projections (the text parser reads
        # `∃ _, p ∧ q` as a top-level `∧`) cannot shadow the real body proof.
        sub = dataclasses.replace(state, hyps=[hh for hh in state.hyps if hh.name != h.name])
        ps = _Prover(sub, extra_terms=_proj_terms(hb, body)).prove(goal)
        if not ps:
            continue
        proof = ps[0][0]
        out.append(PlannerCandidate(
            _block(f"rcases {h.name} with ⟨{nvar}, {hb}⟩", f"exact {proof}"),
            PLANNER_EXISTS_ELIM, "exists_elim_rcases", 30))
        out.append(PlannerCandidate(
            _block(f"obtain ⟨{nvar}, {hb}⟩ := {h.name}", f"exact {proof}"),
            PLANNER_EXISTS_ELIM, "exists_elim_obtain", 31))
    return out


# ---------------- public entry ----------------


def v4_extra_candidates(
    theorem_statement: Optional[str], state_before: str,
    *, pattern_family: Optional[str] = None,
    enable_negation: bool = False, enable_exists_elim: bool = False,
    max_candidates: int = 12,
) -> List[PlannerCandidate]:
    """Optional v4 template candidates, deduplicated + priority-ordered. Empty
    unless a flag is set (the ablation enables one family at a time)."""
    if not (enable_negation or enable_exists_elim):
        return []
    state = parse_planner_state(theorem_statement, state_before, pattern_family=pattern_family)
    cands: List[PlannerCandidate] = []
    if enable_negation:
        cands.extend(negation_candidates(state))
    if enable_exists_elim:
        cands.extend(exists_elim_candidates(state))
    best = {}
    for c in cands:
        prev = best.get(c.tactic)
        if prev is None or c.priority < prev.priority:
            best[c.tactic] = c
    return sorted(best.values(), key=lambda c: (c.priority, len(c.tactic), c.tactic))[:max_candidates]
