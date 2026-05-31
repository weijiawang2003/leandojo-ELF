"""Tests for the v19 local-context parser."""

from __future__ import annotations

import pytest

from mini_elf_lean.local_context import (
    TypeCategory, classify_type, context_token_signature, parse_state,
)


# --------------- classifier sanity ---------------------------------------


@pytest.mark.parametrize("type_str,expected", [
    ("Prop", TypeCategory.PROP),
    ("Nat", TypeCategory.NAT),
    ("Bool", TypeCategory.BOOL),
    ("Type", TypeCategory.TYPE),
    ("Type u", TypeCategory.TYPE),
    ("Type 1", TypeCategory.TYPE),
    ("List α", TypeCategory.LIST),
    ("List Nat", TypeCategory.LIST),
    ("p", TypeCategory.HYP_PROP),
    ("α", TypeCategory.HYP_PROP),
    ("¬p", TypeCategory.NEGATION),
    ("¬(p ∧ q)", TypeCategory.NEGATION),
    ("p → q", TypeCategory.IMPLICATION),
    ("p -> q", TypeCategory.IMPLICATION),
    ("a = b", TypeCategory.EQUALITY),
    ("n.succ = m.succ", TypeCategory.EQUALITY),
    ("p ∧ q", TypeCategory.CONJUNCTION),
    ("p ∨ q", TypeCategory.DISJUNCTION),
    ("b = true ∨ b = false", TypeCategory.DISJUNCTION),
    ("∀ x, p x", TypeCategory.FORALL),
    ("∃ n : Nat, n = 3", TypeCategory.EXISTS),
])
def test_classify(type_str: str, expected: TypeCategory) -> None:
    assert classify_type(type_str) == expected, (
        f"classify_type({type_str!r}) = "
        f"{classify_type(type_str)} (expected {expected.value})")


def test_classify_empty_is_unknown() -> None:
    assert classify_type("") is TypeCategory.UNKNOWN


def test_classify_handles_unicode_identifiers() -> None:
    assert classify_type("α") is TypeCategory.HYP_PROP
    assert classify_type("β") is TypeCategory.HYP_PROP


# --------------- state parser --------------------------------------------


def test_parse_simple_implication_context() -> None:
    state = "p q : Prop\nh : p → q\nhp : p\n⊢ q"
    ctx = parse_state(state)
    assert [h.name for h in ctx.hypotheses] == ["p", "q", "h", "hp"]
    assert ctx.find("h").category is TypeCategory.IMPLICATION
    assert ctx.find("hp").category is TypeCategory.HYP_PROP
    assert ctx.find("p").category is TypeCategory.PROP
    assert ctx.goal == "q"


def test_parse_mixed_names_no_crash() -> None:
    state = ("p q : Prop\n"
             "hImp : p → q\n"
             "prf : p\n"
             "⊢ q")
    ctx = parse_state(state)
    assert ctx.find("hImp").category is TypeCategory.IMPLICATION
    assert ctx.find("prf").category is TypeCategory.HYP_PROP


def test_parse_greek_identifiers() -> None:
    state = "α : Type\nxs : List α\n⊢ xs ++ [] = xs"
    ctx = parse_state(state)
    assert ctx.find("α").category is TypeCategory.TYPE
    assert ctx.find("xs").category is TypeCategory.LIST


def test_parse_nat_bool_binders() -> None:
    ctx_n = parse_state("n m : Nat\nh : n = m\n⊢ m = n")
    assert ctx_n.find("n").category is TypeCategory.NAT
    assert ctx_n.find("m").category is TypeCategory.NAT
    assert ctx_n.find("h").category is TypeCategory.EQUALITY

    ctx_b = parse_state("b : Bool\n⊢ b = true ∨ b = false")
    assert ctx_b.find("b").category is TypeCategory.BOOL
    assert ctx_b.goal_category is TypeCategory.DISJUNCTION


def test_parse_equality_hypothesis() -> None:
    state = "n m : Nat\nh : n = m\n⊢ m = n"
    ctx = parse_state(state)
    assert ctx.find("h").category is TypeCategory.EQUALITY


def test_parse_empty_state_returns_empty_context() -> None:
    ctx = parse_state("")
    assert ctx.hypotheses == []
    assert ctx.goal == ""


def test_parse_handles_no_turnstile() -> None:
    ctx = parse_state("p : Prop")
    assert ctx.find("p") is not None
    assert ctx.goal == ""


def test_parse_drops_malformed_lines_silently() -> None:
    # Pathological state — should not raise
    ctx = parse_state("xxx no colon here\n⊢ q")
    # Malformed lines are skipped.
    assert ctx.goal == "q"


# --------------- multi-name binder ---------------------------------------


def test_parse_multi_name_binder_splits() -> None:
    """`p q : Prop` should produce two separate hypotheses."""
    ctx = parse_state("p q : Prop\n⊢ p")
    assert [h.name for h in ctx.hypotheses] == ["p", "q"]
    assert all(h.category is TypeCategory.PROP for h in ctx.hypotheses)


# --------------- context signature ---------------------------------------


def test_signature_equality() -> None:
    """States with the same category sequence get the same signature."""
    a = parse_state("p q : Prop\nh : p → q\nhp : p\n⊢ q")
    b = parse_state("α β : Prop\nf : α → β\nx : α\n⊢ β")
    assert context_token_signature(a) == context_token_signature(b)


def test_signature_differs_when_categories_differ() -> None:
    a = parse_state("p q : Prop\nh : p → q\n⊢ q")
    b = parse_state("p q : Prop\nh : p ∧ q\n⊢ q")
    assert context_token_signature(a) != context_token_signature(b)


# --------------- no state_after ------------------------------------------


def test_parse_signature_has_no_state_after_param() -> None:
    import inspect
    sig = inspect.signature(parse_state)
    assert "state_after" not in sig.parameters
