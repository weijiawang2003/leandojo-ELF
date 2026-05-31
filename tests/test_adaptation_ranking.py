"""V6 Part 7 — adapted-candidate ranking tests (the F1 fix).

Pure-Python: no torch, no Lean. Checks numeric adaptation ranks the correct
adapted tactic above the verbatim donor, in goal-LHS-first order, with metadata,
and that no adaptation is produced when it is unsafe."""

from __future__ import annotations

from mini_elf_lean.baselines import Example
from mini_elf_lean.retrieval_proposer import StructureAwareRetrievalProposer


def _ex(name, stmt, state, tac):
    return Example(theorem_name=name, theorem_statement=stmt, state_before=state, tactic=tac, split="train")


FORALL = [
    _ex("forall_inst_3_0", "(h : ∀ x : Nat, x = 0) : 3 = 0", "h : ∀ x : Nat, x = 0\n⊢ 3 = 0", "exact h 3"),
    _ex("forall_inst_7_0", "(h : ∀ x : Nat, x = 0) : 7 = 0", "h : ∀ x : Nat, x = 0\n⊢ 7 = 0", "exact h 7"),
]


def test_adapted_ranks_above_verbatim():
    v6 = StructureAwareRetrievalProposer().fit(FORALL)
    cands = v6.propose("(h : ∀ x : Nat, x = 6) : 13 = 6", "h : ∀ x : Nat, x = 6\n⊢ 13 = 6",
                       theorem_name="forall_inst_13_6")
    tacs = [c.tactic for c in cands]
    assert tacs[0] == "exact h 13"                       # adapted, correct LHS literal
    assert tacs.index("exact h 13") < tacs.index("exact h 3")  # above the stale verbatim
    assert cands[0].metadata["adapted"] is True
    assert cands[0].metadata["adaptation_kind"] == "numeric"
    assert cands[0].metadata["donor_tactic"] in ("exact h 3", "exact h 7")


def test_lhs_literal_first():
    v6 = StructureAwareRetrievalProposer().fit(FORALL)
    cands = v6.propose("(h : ∀ x : Nat, x = 4) : 9 = 4", "h : ∀ x : Nat, x = 4\n⊢ 9 = 4",
                       theorem_name="forall_inst_9_4")
    tacs = [c.tactic for c in cands]
    # 9 is the goal LHS (the witness); it must rank before the RHS literal 4.
    assert tacs[0] == "exact h 9"
    assert tacs.index("exact h 9") < tacs.index("exact h 4")


def test_no_adapt_pref_still_orders_lhs_first_via_tiebreak():
    v6 = StructureAwareRetrievalProposer(enable_adapt_preference=False).fit(FORALL)
    cands = v6.propose("(h : ∀ x : Nat, x = 4) : 9 = 4", "h : ∀ x : Nat, x = 4\n⊢ 9 = 4",
                       theorem_name="forall_inst_9_4")
    # even without the explicit stale penalty, the adapted-first + generation-order
    # tie-break keeps the correct literal on top.
    assert cands[0].tactic == "exact h 9"


def test_no_adaptation_when_no_numeric():
    rewrite = [_ex("rewrite_succ_nm", "(n m : Nat) (h : n = m) : n.succ = m.succ",
                   "n m : Nat\nh : n = m\n⊢ n.succ = m.succ", "rw [h]")]
    v6 = StructureAwareRetrievalProposer().fit(rewrite)
    cands = v6.propose("(a b : Nat) (h : a = b) : a.succ = b.succ",
                       "a b : Nat\nh : a = b\n⊢ a.succ = b.succ", theorem_name="rewrite_succ_ab")
    assert cands[0].tactic == "rw [h]"
    assert all(not c.metadata.get("adapted") for c in cands)  # nothing to adapt


def test_numeric_disabled_no_adapted():
    v6 = StructureAwareRetrievalProposer(enable_numeric_adapt=False).fit(FORALL)
    cands = v6.propose("(h : ∀ x : Nat, x = 6) : 13 = 6", "h : ∀ x : Nat, x = 6\n⊢ 13 = 6",
                       theorem_name="forall_inst_13_6")
    assert all(not c.metadata.get("adapted") for c in cands)
