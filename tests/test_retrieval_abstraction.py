"""Unit tests for the v7 operation-abstraction primitives (torch-free, no Lean)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mini_elf_lean.retrieval_abstraction import (  # noqa: E402
    abstract_tactic,
    hyp_roles,
    operation_signature,
    signatures_match,
    tactic_head,
)

# Representative planner-blind states.
FORALL_STATE = "h : ∀ n : Nat, f n = n\n⊢ f 13 = 13"
EQ_STATE = "a b : Nat\nh : a = b\n⊢ Nat.succ a = Nat.succ b"
EXISTS_STATE = "h : ∃ n : Nat, p n ∧ q n\n⊢ p 0"
NEG_STATE = "p q : Prop\nhp : p\nhnp : ¬p\n⊢ q"


def test_hyp_roles_classifies_by_type():
    assert hyp_roles(FORALL_STATE)["h"] == "forall"
    assert hyp_roles(EQ_STATE)["h"] == "eq"
    assert hyp_roles(EXISTS_STATE)["h"] == "exists"
    roles = hyp_roles(NEG_STATE)
    assert roles["hp"] == "prop"
    assert roles["hnp"] == "neg"
    # `n : Nat` / `p : Prop` style binders are NOT proof hypotheses.
    assert "a" not in hyp_roles(EQ_STATE)


def test_abstract_exact_h_13():
    # brief example: exact h 13 -> exact <forall_hyp> <num>
    assert abstract_tactic("exact h 13", FORALL_STATE) == "exact <forall_hyp> <num>"
    sig = operation_signature("exact h 13", FORALL_STATE)
    assert sig.head == "exact"
    assert sig.roles == frozenset({"forall"})
    assert sig.has_num is True


def test_abstract_rw_eq():
    # brief example: rw [h] -> rw [<eq_hyp>]
    assert abstract_tactic("rw [h]", EQ_STATE) == "rw [<eq_hyp>]"
    sig = operation_signature("rw [h]", EQ_STATE)
    assert sig.head == "rw"
    assert sig.roles == frozenset({"eq"})
    assert sig.has_num is False


def test_abstract_rcases_exists():
    # brief example: rcases h with ⟨x, hx⟩ -> mentions <exists_hyp>
    out = abstract_tactic("rcases h with ⟨n, hn⟩\n  exact ⟨n, hn⟩", EXISTS_STATE)
    assert "<exists_hyp>" in out
    assert tactic_head("rcases h with ⟨n, hn⟩") == "rcases"
    sig = operation_signature("rcases h with ⟨n, hn⟩", EXISTS_STATE)
    assert "exists" in sig.roles


def test_same_operation_signatures_match():
    # Two structurally different ex-falso tactics share one operation signature.
    a = operation_signature("exact absurd hp hnp", NEG_STATE)
    b = operation_signature("exact (hnp hp).elim", NEG_STATE)
    assert a.key() == b.key()
    assert signatures_match(a, b)
    # strict (exact-string) match is False — they differ structurally.
    assert not signatures_match(a, b, strict=True)


def test_unrelated_operations_do_not_match():
    a = operation_signature("exact h 13", FORALL_STATE)   # instantiate a ∀
    b = operation_signature("rw [h]", EQ_STATE)           # rewrite an eq
    assert a.key() != b.key()
    assert not signatures_match(a, b)


def test_forall_inst_literals_share_one_signature():
    # All `exact h N` collapse to the same key regardless of the literal — that
    # is exactly what lets a numeric-adapted candidate be retrieved cross-literal.
    keys = {operation_signature(f"exact h {n}", FORALL_STATE).key() for n in (3, 5, 7, 9, 13)}
    assert len(keys) == 1


def test_abstraction_never_raises_on_garbage():
    for bad in ("", "   ", "exact", "🙂 ⟨⟩ := foo.bar 9", "intro\n\nrw [["):
        abstract_tactic(bad, "garbage\nstate")  # must not raise


# ---- role-based re-concretisation (the v7 cross-family lever) ----

from mini_elf_lean.retrieval_abstraction_proposer import reconcretize, _role_to_names  # noqa: E402


def test_reconcretize_binds_roles_to_target_hyps():
    # donor proof abstracted to roles, re-bound to THIS target's hypotheses
    out = reconcretize("exact absurd <prop_hyp> <neg_hyp>", _role_to_names(NEG_STATE), None)
    assert out == "exact absurd hp hnp"


def test_reconcretize_fills_numeric_slot_from_goal():
    out = reconcretize("exact <forall_hyp> <num>", _role_to_names(FORALL_STATE), "13")
    assert out == "exact h 13"


def test_reconcretize_returns_none_when_role_absent():
    # target NEG_STATE has no equality hypothesis -> cannot fill <eq_hyp>
    assert reconcretize("rw [<eq_hyp>]", _role_to_names(NEG_STATE), None) is None


def test_reconcretize_returns_none_with_boundvar_slot():
    # a bound-variable <id> slot cannot be safely filled -> abstain
    assert reconcretize("exact fun <id> => <id> <prop_hyp>", _role_to_names(NEG_STATE), None) is None


def test_reconcretize_returns_none_without_needed_literal():
    assert reconcretize("exact <forall_hyp> <num>", _role_to_names(FORALL_STATE), None) is None
