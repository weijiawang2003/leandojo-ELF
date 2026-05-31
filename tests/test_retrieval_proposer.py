"""V5 Part 7 — retrieval proof-block proposer tests.

Pure-Python: no torch, no Lean. Checks retrieval reuse, numeric-literal
adaptation (the `forall_inst` mechanism), hypothesis remap, the leakage guard,
and that adaptation can be ablated off."""

from __future__ import annotations

from mini_elf_lean.baselines import Example
from mini_elf_lean.proposer import ProposedCandidate
from mini_elf_lean.retrieval_proposer import (
    RETRIEVAL_ADAPTED_SOURCE,
    RETRIEVAL_SOURCE,
    RetrievalProofBlockProposer,
    _numeric_variants,
    _query_literals,
)


def _ex(name, stmt, state, tac):
    return Example(theorem_name=name, theorem_statement=stmt, state_before=state, tactic=tac, split="train")


FORALL_DONORS = [
    _ex("forall_inst_7_0", "(h : ∀ x : Nat, x = 0) : 7 = 0", "h : ∀ x : Nat, x = 0\n⊢ 7 = 0", "exact h 7"),
    _ex("forall_inst_3_0", "(h : ∀ x : Nat, x = 0) : 3 = 0", "h : ∀ x : Nat, x = 0\n⊢ 3 = 0", "exact h 3"),
]
REWRITE_DONORS = [
    _ex("rewrite_succ_nm", "(n m : Nat) (h : n = m) : n.succ = m.succ",
        "n m : Nat\nh : n = m\n⊢ n.succ = m.succ", "rw [h]"),
    _ex("rewrite_succ_nm", "(n m : Nat) (h : n = m) : n.succ = m.succ",
        "n m : Nat\nh : n = m\n⊢ n.succ = m.succ", "exact congrArg Nat.succ h"),
]


def test_query_literals_goal_first():
    assert _query_literals("h : ∀ x : Nat, x = 2\n⊢ 5 = 2") == ["5", "2"]


def test_numeric_variants_single_literal():
    assert _numeric_variants("exact h 7", ["5", "2"], 4) == ["exact h 5", "exact h 2"]
    # projections are not literals -> donor with two distinct literals is skipped
    assert _numeric_variants("exact h 7 8", ["5"], 4) == []


def test_retrieval_returns_typed_candidates():
    r = RetrievalProofBlockProposer().fit(REWRITE_DONORS)
    cands = r.propose("(a b : Nat) (h : a = b) : a.succ = b.succ",
                      "a b : Nat\nh : a = b\n⊢ a.succ = b.succ", theorem_name="rewrite_succ_ab")
    assert cands and all(isinstance(c, ProposedCandidate) for c in cands)
    tacs = [c.tactic for c in cands]
    assert "rw [h]" in tacs  # verbatim reuse, hyp name constant
    assert all(c.source in (RETRIEVAL_SOURCE, RETRIEVAL_ADAPTED_SOURCE) for c in cands)


def test_numeric_adaptation_solves_forall_inst():
    r = RetrievalProofBlockProposer().fit(FORALL_DONORS)
    cands = r.propose("(h : ∀ x : Nat, x = 2) : 5 = 2", "h : ∀ x : Nat, x = 2\n⊢ 5 = 2",
                      theorem_name="forall_inst_5_2")
    adapted = [c for c in cands if c.source == RETRIEVAL_ADAPTED_SOURCE]
    assert "exact h 5" in [c.tactic for c in adapted]
    assert all(c.metadata.get("adaptation") == "numeric" for c in adapted)


def test_adaptation_off_yields_no_adapted():
    r = RetrievalProofBlockProposer(enable_numeric_adapt=False, enable_hyp_remap=False).fit(FORALL_DONORS)
    cands = r.propose("(h : ∀ x : Nat, x = 2) : 5 = 2", "h : ∀ x : Nat, x = 2\n⊢ 5 = 2",
                      theorem_name="forall_inst_5_2")
    assert all(c.source == RETRIEVAL_SOURCE for c in cands)


def test_leakage_guard_excludes_self():
    r = RetrievalProofBlockProposer().fit(FORALL_DONORS)
    # query IS forall_inst_7_0 -> that donor must not be retrieved
    cands = r.propose("(h : ∀ x : Nat, x = 0) : 7 = 0", "h : ∀ x : Nat, x = 0\n⊢ 7 = 0",
                      theorem_name="forall_inst_7_0")
    assert all(c.metadata.get("neighbor_theorem") != "forall_inst_7_0" for c in cands)


def test_hyp_remap_variant():
    donor = [_ex("d", "(p : Prop) (hh : p) : p", "p : Prop\nhh : p\n⊢ p", "exact hh")]
    r = RetrievalProofBlockProposer().fit(donor)
    cands = r.propose("(p : Prop) (hp : p) : p", "p : Prop\nhp : p\n⊢ p", theorem_name="q")
    tacs = [c.tactic for c in cands]
    assert "exact hp" in tacs  # hh : p remapped to query's hp : p


def test_max_candidates_enforced():
    r = RetrievalProofBlockProposer().fit(FORALL_DONORS + REWRITE_DONORS)
    cands = r.propose("(h : ∀ x : Nat, x = 2) : 5 = 2", "h : ∀ x : Nat, x = 2\n⊢ 5 = 2",
                      theorem_name="z", max_candidates=3)
    assert len(cands) <= 3


def test_empty_index_returns_empty():
    assert RetrievalProofBlockProposer().fit([]).propose("x", "y") == []
