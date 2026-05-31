"""Unit tests for the v12 literal-aware candidate augmentation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mini_elf_lean.literal_aware_decode import (  # noqa: E402
    SOURCE_LITERAL_ADAPT,
    SOURCE_SEQ2SEQ,
    adapt_candidates,
    compose_candidates,
)


# ---------------- canonical happy paths ----------------


def test_exact_h_4_target_13_emits_exact_h_13():
    state = "h : ∀ x : Nat, x = 6\n⊢ 13 = 6"
    adapted = adapt_candidates(["exact h 4"], state_before=state)
    assert any(a.tactic == "exact h 13" and a.source == SOURCE_LITERAL_ADAPT
               for a in adapted)


def test_exact_h_7_target_3_emits_exact_h_3():
    state = "h : ∀ x : Nat, x = 0\n⊢ 3 = 0"
    adapted = adapt_candidates(["exact h 7"], state_before=state)
    assert any(a.tactic == "exact h 3" for a in adapted)


def test_only_first_goal_literal_substituted():
    """Conservative target: the FIRST literal on the goal is used as the
    substitution target. For ``⊢ Q 5 ∨ Q 7`` the target is 5 — emitting
    a candidate for 7 would inject a wrong-literal noise candidate that
    the reranker would then have to filter out."""
    state = "h : ∀ x : Nat, P x\n⊢ Q 5 ∨ Q 7"
    adapted = adapt_candidates(["exact h 4"], state_before=state)
    tactics = {a.tactic for a in adapted}
    assert "exact h 5" in tactics
    assert "exact h 7" not in tactics


def test_source_metadata_preserved_on_adapted_candidates():
    state = "h : ∀ x : Nat, x = 0\n⊢ 13 = 0"
    adapted = adapt_candidates(["exact h 4"], state_before=state)
    for a in adapted:
        assert a.source == SOURCE_LITERAL_ADAPT
        assert a.substituted_from == 4
        assert a.substituted_to == 13
        assert a.schema == "exact_hyp_num"


# ---------------- conservative gates ----------------


def test_no_augmentation_on_rewrite_succ_style_goal_without_forall():
    # rewrite_succ state has no ∀ quantifier; literal adaptation must NOT fire.
    state = "n m : Nat\nh : n = m\n⊢ Nat.succ n = Nat.succ m"
    adapted = adapt_candidates(["rw [h]"], state_before=state)
    assert adapted == []


def test_no_augmentation_when_goal_has_no_literal():
    state = "h : ∀ x : Nat, x = x\n⊢ Nat.succ n = Nat.succ m"
    adapted = adapt_candidates(["exact h 4"], state_before=state)
    assert adapted == []


def test_no_augmentation_when_candidate_does_not_match_schema():
    state = "h : ∀ x : Nat, x = 0\n⊢ 13 = 0"
    # `exact h` (no literal) is not the schema; `exact rfl` isn't either.
    adapted = adapt_candidates(["exact h", "exact rfl"], state_before=state)
    assert adapted == []


def test_no_augmentation_when_hyp_name_is_not_in_local_context():
    # candidate names "g", but the only hyp is "h" — refuse to substitute
    state = "h : ∀ x : Nat, x = 0\n⊢ 13 = 0"
    adapted = adapt_candidates(["exact g 4"], state_before=state)
    assert adapted == []


def test_no_augmentation_when_literal_already_matches_goal():
    state = "h : ∀ x : Nat, x = 0\n⊢ 7 = 0"
    # candidate already has the right literal — no need to adapt
    adapted = adapt_candidates(["exact h 7"], state_before=state)
    assert adapted == []


def test_dotted_field_access_not_adapted():
    """Don't try to adapt ``exact h.left`` etc. — single-identifier
    schema only."""
    state = "h : ∀ x : Nat, x = 0\n⊢ 13 = 0"
    adapted = adapt_candidates(["exact h.left 4"], state_before=state)
    assert adapted == []


# ---------------- multi-arg + witness ----------------


def test_binary_forall_inst_substitutes_first_literal_only():
    """First positional arg in the candidate is replaced with the first
    goal literal; the second arg is left untouched. (We do not try to
    align two arguments to two goal literals — that's beyond v12's
    conservative scope.)"""
    state = "h : ∀ x y : Nat, x + y = y + x\n⊢ 5 + 3 = 3 + 5"
    adapted = adapt_candidates(["exact h 2 3"], state_before=state)
    tactics = {a.tactic for a in adapted}
    # goal's first literal is 5; first lit "2" should be replaced with 5
    assert "exact h 5 3" in tactics
    # We do NOT emit "exact h 3 3" (the primary-target-only heuristic
    # uses only the first goal literal).
    assert "exact h 3 3" not in tactics
    # And we do NOT touch the second arg.
    assert "exact h 5 5" not in tactics


def test_witness_schema_adapts_literal():
    state = "⊢ ∃ n : Nat, n = 13"
    # ⟨5, rfl⟩ → ⟨13, rfl⟩
    adapted = adapt_candidates(["exact ⟨5, rfl⟩"], state_before=state)
    # ⟨5, rfl⟩ already in the seen set (it's the original); so only
    # ⟨13, rfl⟩ should be emitted
    tactics = {a.tactic for a in adapted}
    assert "exact ⟨13, rfl⟩" in tactics


def test_witness_schema_no_op_when_no_forall_no_literal():
    state = "⊢ True"
    adapted = adapt_candidates(["exact ⟨5, rfl⟩"], state_before=state)
    assert adapted == []


# ---------------- dedup against originals ----------------


def test_dedup_against_original_candidates():
    state = "h : ∀ x : Nat, x = 0\n⊢ 13 = 0"
    # If model already emits the correct adapted tactic, the adapt step
    # should NOT re-emit it as an "adapted" duplicate.
    adapted = adapt_candidates(["exact h 4", "exact h 13"],
                               state_before=state)
    assert all(a.tactic != "exact h 13" for a in adapted)


def test_dedup_within_adapt_pass():
    state = "h : ∀ x : Nat, x = 0\n⊢ 13 = 0"
    # Two candidates with different stale literals but the SAME target
    # literal must produce only ONE adapted tactic.
    adapted = adapt_candidates(["exact h 4", "exact h 7"],
                               state_before=state)
    targets = [a.tactic for a in adapted]
    assert targets.count("exact h 13") == 1


# ---------------- compose ----------------


def test_compose_appends_adapted_after_originals():
    state = "h : ∀ x : Nat, x = 0\n⊢ 13 = 0"
    combined = compose_candidates(["exact h 4", "exact h 7"],
                                  state_before=state)
    tactics = [t for t, _src, _meta in combined]
    sources = [s for _t, s, _meta in combined]
    assert tactics[0] == "exact h 4"
    assert tactics[1] == "exact h 7"
    # The adapted "exact h 13" must appear AFTER the originals
    assert "exact h 13" in tactics
    adapt_index = tactics.index("exact h 13")
    assert adapt_index >= 2
    assert sources[adapt_index] == SOURCE_LITERAL_ADAPT


def test_compose_passes_through_when_no_adaptation_possible():
    state = "n m : Nat\nh : n = m\n⊢ Nat.succ n = Nat.succ m"
    combined = compose_candidates(["rw [h]", "exact congrArg Nat.succ h"],
                                  state_before=state)
    assert all(s == SOURCE_SEQ2SEQ for _t, s, _ in combined)
    assert len(combined) == 2


def test_compose_dedups_originals():
    """If the model's beam emits duplicates, compose() should drop them."""
    state = "h : ∀ x : Nat, x = 0\n⊢ 5 = 0"
    combined = compose_candidates(["exact h 4", "exact h 4"],
                                  state_before=state)
    assert [t for t, _, _ in combined].count("exact h 4") == 1


# ---------------- state_after must NEVER be accessed ----------------


def test_module_does_not_read_state_after_argument(monkeypatch):
    """The v12 contract: literal adaptation must not depend on
    ``state_after``. The function signature has no state_after argument,
    so passing one as a kwarg should raise TypeError — confirming the
    invariant statically rather than just by inspection."""
    state = "h : ∀ x : Nat, x = 0\n⊢ 13 = 0"
    import pytest
    with pytest.raises(TypeError):
        adapt_candidates(["exact h 4"], state_before=state,
                         state_after="x = 6")  # type: ignore[call-arg]
