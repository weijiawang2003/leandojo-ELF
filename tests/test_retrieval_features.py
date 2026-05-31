"""V6 Part 7 — structured retrieval-feature tests.

Pure-Python: no torch, no Lean. Checks goal-shape / hypothesis-shape /
required-operation recognition and the left/right conjunct distinction, and that
malformed text never crashes."""

from __future__ import annotations

from mini_elf_lean.retrieval_features import (
    ATOM_GOAL,
    CONTRADICTION_GOAL,
    EQUALITY_GOAL,
    NEG_GOAL,
    OP_CONTRADICTION,
    OP_DESTRUCT_EXISTS,
    OP_INSTANTIATE_FORALL,
    OP_INTRO_NEGATION,
    OP_REWRITE,
    REWRITE_GOAL,
    extract_features,
)


def _s(*lines):
    return "\n".join(lines)


def test_forall_inst_recognized():
    f = extract_features("(h : ∀ x : Nat, x = 0) : 7 = 0", _s("h : ∀ x : Nat, x = 0", "⊢ 7 = 0"))
    assert f.has_forall_hyp
    assert f.goal_shape == EQUALITY_GOAL
    assert f.required_operation == OP_INSTANTIATE_FORALL
    assert "7" in f.numeric_literals and f.goal_literals[0] == "7"


def test_rewrite_succ_recognized():
    f = extract_features("(n m : Nat) (h : n = m) : n.succ = m.succ",
                         _s("n m : Nat", "h : n = m", "⊢ n.succ = m.succ"))
    assert f.has_eq_hyp and not f.has_forall_hyp
    assert f.goal_shape == REWRITE_GOAL
    assert f.required_operation == OP_REWRITE


def test_exists_elim_recognized():
    f = extract_features("(p : Prop) (h : ∃ _ : Nat, p) : p", _s("p : Prop", "h : ∃ _ : Nat, p", "⊢ p"))
    assert f.has_exists_hyp
    assert f.required_operation == OP_DESTRUCT_EXISTS


def test_contradiction_recognized():
    f = extract_features("(p q : Prop) (hp : p) (hnp : ¬p) : q",
                         _s("p q : Prop", "hp : p", "hnp : ¬p", "⊢ q"))
    assert f.has_neg_hyp
    assert f.goal_shape == CONTRADICTION_GOAL
    assert f.required_operation == OP_CONTRADICTION


def test_neg_goal_recognized():
    f = extract_features("(p q : Prop) (h : p → q) (hnq : ¬q) : ¬p",
                         _s("p q : Prop", "h : p → q", "hnq : ¬q", "⊢ ¬p"))
    assert f.goal_shape == NEG_GOAL
    assert f.required_operation == OP_INTRO_NEGATION


def test_conjunction_left_right_distinction():
    left = extract_features("(a b : Prop) (h : ∃ _ : Nat, a ∧ b) : a",
                            _s("a b : Prop", "h : ∃ _ : Nat, a ∧ b", "⊢ a"))
    right = extract_features("(a b : Prop) (h : ∃ _ : Nat, a ∧ b) : b",
                             _s("a b : Prop", "h : ∃ _ : Nat, a ∧ b", "⊢ b"))
    assert left.goal_conjunct_position == "left"
    assert right.goal_conjunct_position == "right"
    assert left.has_and_hyp and right.has_and_hyp


def test_top_level_conjunction_hyp_left_right():
    left = extract_features("(a b : Prop) (h : a ∧ b) : a", _s("a b : Prop", "h : a ∧ b", "⊢ a"))
    assert left.goal_conjunct_position == "left"


def test_malformed_text_does_not_crash():
    f = extract_features("", "###garbage no turnstile @@@")
    assert isinstance(f.goal_shape, str)
    f2 = extract_features(None, "")
    assert f2.goal_shape in (ATOM_GOAL,) or isinstance(f2.goal_shape, str)


def test_negation_does_not_classify_plain_atom_as_contradiction():
    f = extract_features("(p : Prop) (hp : p) : p", _s("p : Prop", "hp : p", "⊢ p"))
    assert f.goal_shape == ATOM_GOAL  # no negation hyp -> not contradiction
