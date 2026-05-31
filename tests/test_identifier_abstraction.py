"""Tests for the v19 identifier-abstraction module."""

from __future__ import annotations

import pytest

from mini_elf_lean.identifier_abstraction import (
    abstract_state, abstract_tactic_only, build_abstraction_map,
    concretise_or_fail, concretise_tactic, remap_tactic_across_states,
)


# --------------- round-trip ---------------------------------------------


def test_round_trip_exact_h_hp() -> None:
    state = "p q : Prop\nh : p → q\nhp : p\n⊢ q"
    abs_state, abs_tactic, am = abstract_state(state, "exact h hp")
    assert abs_tactic == "exact <HYP_IMP_0> <HYP_PROP_0>"
    out, reason = concretise_or_fail(abs_tactic, state)
    assert reason == "ok"
    assert out == "exact h hp"


def test_round_trip_intro_negation_proof() -> None:
    state = "p q : Prop\nh : p → q\nhnq : ¬q\n⊢ ¬p"
    tactic = "intro hp\n  exact hnq (h hp)"
    abs_state, abs_tactic, am = abstract_state(state, tactic)
    out, reason = concretise_or_fail(abs_tactic, state)
    assert reason == "ok"
    assert out == tactic


def test_round_trip_no_placeholders_in_tactic() -> None:
    """A tactic that uses only keywords + literals (no identifiers
    from the local context) should pass through unchanged."""
    state = "(x : Nat) : x = x"
    state_text = "x : Nat\n⊢ x = x"
    abs_s, abs_t, am = abstract_state(state_text, "rfl")
    assert abs_t == "rfl"
    out, reason = concretise_or_fail("rfl", state_text)
    assert reason == "no_placeholders"
    assert out == "rfl"


# --------------- keyword protection -------------------------------------


def test_keyword_not_substituted() -> None:
    state = "p : Prop\nhp : p\n⊢ p"
    abs_s, abs_t, _ = abstract_state(state, "exact hp")
    # 'exact' is a Lean tactic keyword and must NOT be abstracted.
    assert "exact" in abs_t
    assert abs_t == "exact <HYP_PROP_0>"


def test_intro_keyword_not_substituted() -> None:
    state = "p q : Prop\nhp : p\n⊢ q → p"
    abs_s, abs_t, _ = abstract_state(state, "intro hq\n  exact hp")
    assert abs_t.startswith("intro ")
    assert "<HYP_PROP_0>" in abs_t


# --------------- word boundary ------------------------------------------


def test_h_inside_hp_not_substituted() -> None:
    """When both `h` and `hp` are in scope, replacing `h` must NOT
    leak into `hp`."""
    state = "p : Prop\nh : p\nhp : p\n⊢ p"
    abs_s1, abs_t1, _ = abstract_state(state, "exact h")
    abs_s2, abs_t2, _ = abstract_state(state, "exact hp")
    assert abs_t1 != abs_t2
    # Specifically, 'h' is HYP_PROP_0 and 'hp' is HYP_PROP_1
    assert abs_t1 == "exact <HYP_PROP_0>"
    assert abs_t2 == "exact <HYP_PROP_1>"


def test_longest_name_first_replacement() -> None:
    """`hnp` should be replaced before `h`, so we don't end up with
    `<HYP_PROP_0>np`."""
    state = "p : Prop\nh : p\nhnp : ¬p\n⊢ False"
    abs_s, abs_t, _ = abstract_state(state, "exact hnp h")
    # h goes to HYP_PROP_0, hnp goes to HYP_NEG_0
    assert abs_t == "exact <HYP_NEG_0> <HYP_PROP_0>"


# --------------- unresolved placeholders -------------------------------


def test_concretise_unresolved_placeholder() -> None:
    state_new = "p q : Prop\nh : p → q\n⊢ q"  # no HYP_PROP — no hp/hq
    abs_tactic = "exact <HYP_IMP_0> <HYP_PROP_0>"
    out, reason = concretise_or_fail(abs_tactic, state_new)
    assert reason == "unresolved_placeholder"
    assert out is None


def test_concretise_partial_resolution_fails() -> None:
    """If even one placeholder is unresolved, the whole tactic
    is rejected (we never partially-bind)."""
    state_new = "p : Prop\nh : p → p\n⊢ p"  # no HYP_PROP
    abs_tactic = "exact <HYP_IMP_0> <HYP_PROP_0>"
    out, reason = concretise_or_fail(abs_tactic, state_new)
    assert reason == "unresolved_placeholder"


# --------------- across-state remap --------------------------------------


def test_remap_v17_to_v18_naming() -> None:
    """A tactic written against a 'training-style' state should
    re-map cleanly to a 'v18-style' state with mixed names."""
    old_state = "p q : Prop\nh : p → q\nhp : p\n⊢ q"
    new_state = "p q : Prop\nhImp : p → q\nprf : p\n⊢ q"
    out = remap_tactic_across_states("exact h hp", old_state, new_state)
    assert out == "exact hImp prf"


def test_remap_returns_none_when_unresolvable() -> None:
    old_state = "p q : Prop\nh : p → q\nhp : p\n⊢ q"
    new_state = "p q : Prop\n⊢ q"  # h and hp are gone
    out = remap_tactic_across_states("exact h hp", old_state, new_state)
    assert out is None


# --------------- abstraction map structure -------------------------------


def test_build_map_separates_categories() -> None:
    state = "p q : Prop\nh : p → q\nhp : p\nhnq : ¬q\n⊢ False"
    am = build_abstraction_map(state)
    # p, q → PROP_0, PROP_1
    assert am.get_placeholder("p") == "<PROP_0>"
    assert am.get_placeholder("q") == "<PROP_1>"
    # h → HYP_IMP_0
    assert am.get_placeholder("h") == "<HYP_IMP_0>"
    # hp → HYP_PROP_0
    assert am.get_placeholder("hp") == "<HYP_PROP_0>"
    # hnq → HYP_NEG_0
    assert am.get_placeholder("hnq") == "<HYP_NEG_0>"


def test_build_map_per_category_counters() -> None:
    state = ("p q r : Prop\n"
             "h1 : p → q\n"
             "h2 : q → r\n"
             "hp : p\n"
             "hq : q\n"
             "⊢ r")
    am = build_abstraction_map(state)
    assert am.get_placeholder("h1") == "<HYP_IMP_0>"
    assert am.get_placeholder("h2") == "<HYP_IMP_1>"
    assert am.get_placeholder("hp") == "<HYP_PROP_0>"
    assert am.get_placeholder("hq") == "<HYP_PROP_1>"


# --------------- no state_after -----------------------------------------


def test_module_has_no_state_after_signature() -> None:
    import inspect
    from mini_elf_lean import identifier_abstraction
    for name in ("abstract_state", "abstract_tactic_only",
                 "build_abstraction_map", "concretise_or_fail",
                 "concretise_tactic", "remap_tactic_across_states"):
        sig = inspect.signature(getattr(identifier_abstraction, name))
        assert "state_after" not in sig.parameters, (
            f"{name} accepts state_after")
