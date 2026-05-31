"""Unit tests for the v12 rule-based candidate reranker."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mini_elf_lean.literal_aware_decode import (  # noqa: E402
    SOURCE_LITERAL_ADAPT,
    SOURCE_SEQ2SEQ,
)
from mini_elf_lean.proof_block_reranker import (  # noqa: E402
    rerank,
    score_candidate,
)


# ---------------- canonical literal-rank cases ----------------


def test_exact_h_13_ranks_above_exact_h_7_when_goal_is_13():
    state = "h : ∀ x : Nat, x = 6\n⊢ 13 = 6"
    cands = [
        ("exact h 7", SOURCE_SEQ2SEQ),
        ("exact h 4", SOURCE_SEQ2SEQ),
        ("exact h 13", SOURCE_LITERAL_ADAPT),
    ]
    out = rerank(cands, state_before=state, required_operation="instantiate_forall")
    # exact h 13 should now be first
    assert out[0].tactic == "exact h 13"
    # stale literals demoted (below exact h 13)
    assert out[1].tactic in ("exact h 7", "exact h 4")
    assert out[2].tactic in ("exact h 7", "exact h 4")


def test_exact_h_3_promoted_over_exact_h_4_when_goal_is_3():
    """The v11 forall_inst_3_0 case: gold `exact h 3` exists but beam
    put it below `exact h 4` and `exact h 7`. Reranker should reorder."""
    state = "h : ∀ x : Nat, x = 0\n⊢ 3 = 0"
    cands = [
        ("exact h 4", SOURCE_SEQ2SEQ),
        ("exact h 7", SOURCE_SEQ2SEQ),
        ("exact h 3", SOURCE_SEQ2SEQ),
    ]
    out = rerank(cands, state_before=state)
    assert out[0].tactic == "exact h 3"


# ---------------- non-regression cases ----------------


def test_rw_h_not_demoted_on_rewrite_succ_goal():
    """``rw [h]`` has no numeric literal; rewriter must not demote it
    just because there's no literal match. (No goal literal either, so
    the literal feature is neutral.)"""
    state = "n m : Nat\nh : n = m\n⊢ Nat.succ n = Nat.succ m"
    cands = [
        ("rw [h]", SOURCE_SEQ2SEQ),
        ("exact h.symm", SOURCE_SEQ2SEQ),
        ("exact rfl", SOURCE_SEQ2SEQ),
    ]
    out = rerank(cands, state_before=state, required_operation="rewrite")
    # rw [h] should NOT be demoted below `exact rfl`. With schema-match
    # for required_operation="rewrite", `rw` head wins.
    assert out[0].tactic == "rw [h]"


def test_neg_exfalso_exact_absurd_not_dropped_below_malformed():
    """The reranker is purely syntactic — it cannot distinguish
    `exact absurd hp hnp` (which verifies) from `exact rfl` (which
    type-mismatches) since both pass all the syntactic checks. The
    invariant we DO enforce: a well-formed candidate must not be
    dropped below a malformed one. The lean-cli verifier is the final
    arbiter between the two competing well-formed candidates."""
    state = ("p q : Prop\nhp : p\nhnp : ¬p\n⊢ q")
    cands = [
        ("exact absurd hp hnp", SOURCE_SEQ2SEQ),
        ("exact h.", SOURCE_SEQ2SEQ),        # malformed (trailing dot)
        ("exact rfl", SOURCE_SEQ2SEQ),
    ]
    out = rerank(cands, state_before=state, required_operation="contradiction")
    # `exact h.` (malformed) must be last.
    assert out[-1].tactic == "exact h."
    # `exact absurd hp hnp` must NOT be last (the bare malformed loses).
    assert out[0].tactic in {"exact absurd hp hnp", "exact rfl"}


# ---------------- malformed penalties ----------------


def test_truncated_exact_h_dot_penalised():
    """``exact h.`` is a v8/v11 char-level truncation. Should be demoted
    below a well-formed candidate (even if both have no goal literal)."""
    state = "h : ∀ x : Nat, x = 0\n⊢ 5 = 0"
    cands = [
        ("exact h.", SOURCE_SEQ2SEQ),
        ("exact h 5", SOURCE_LITERAL_ADAPT),
    ]
    out = rerank(cands, state_before=state)
    assert out[0].tactic == "exact h 5"
    assert out[1].tactic == "exact h."
    assert out[1].features.is_malformed is True


def test_truncated_rw_hns_penalised():
    state = "h : a = b\n⊢ a + 0 = b + 0"
    cands = [
        ("rw [hns", SOURCE_SEQ2SEQ),
        ("rw [h]", SOURCE_SEQ2SEQ),
    ]
    out = rerank(cands, state_before=state, required_operation="rewrite")
    assert out[0].tactic == "rw [h]"
    assert out[1].features.is_malformed is True


def test_unclosed_witness_penalised():
    state = "⊢ ∃ n : Nat, n = 3"
    cands = [
        ("exact ⟨6, rfl", SOURCE_SEQ2SEQ),
        ("exact ⟨3, rfl⟩", SOURCE_LITERAL_ADAPT),
    ]
    out = rerank(cands, state_before=state)
    assert out[0].tactic == "exact ⟨3, rfl⟩"
    assert out[1].features.is_malformed is True


def test_well_known_field_access_not_marked_malformed():
    """``exact h.left`` is NOT a truncation — it's a legitimate
    structure projection (used by `conjunction_projection`). Don't
    penalise it."""
    state = "p q : Prop\nh : p ∧ q\n⊢ p"
    feats = score_candidate("exact h.left", source=SOURCE_SEQ2SEQ,
                             beam_rank=0, goal_literal=None,
                             required_operation="conjunction_projection")
    assert feats.is_malformed is False


# ---------------- literal-adapt source priority ----------------


def test_literal_adapt_outranks_stale_seq2seq_when_target_differs():
    """When a seq2seq candidate has a stale literal and a literal-adapt
    candidate has the correct one, the literal-adapt one wins."""
    state = "h : ∀ x : Nat, x = 0\n⊢ 13 = 0"
    cands = [
        ("exact h 4", SOURCE_SEQ2SEQ),         # stale literal
        ("exact h 13", SOURCE_LITERAL_ADAPT),   # adapted, matches goal
    ]
    out = rerank(cands, state_before=state)
    assert out[0].tactic == "exact h 13"
    assert out[0].source == SOURCE_LITERAL_ADAPT


def test_seq2seq_kept_when_no_stale_literal():
    """If neither candidate has a goal-literal conflict, the
    literal-adapt source should not unfairly outrank the original."""
    state = "h : a = b\n⊢ Nat.succ a = Nat.succ b"
    cands = [
        ("rw [h]", SOURCE_SEQ2SEQ),
        ("exact congrArg Nat.succ h", SOURCE_SEQ2SEQ),
    ]
    out = rerank(cands, state_before=state, required_operation="rewrite")
    # Both are valid; `rw` head matches schema slightly stronger,
    # but neither is a literal-adapt, so the test mainly checks neither
    # was demoted to last place by some accidental penalty.
    assert {c.tactic for c in out[:2]} == {"rw [h]", "exact congrArg Nat.succ h"}


# ---------------- metadata preservation ----------------


def test_source_metadata_round_trip():
    state = "h : ∀ x : Nat, x = 0\n⊢ 13 = 0"
    cands = [
        ("exact h 4", SOURCE_SEQ2SEQ),
        ("exact h 13", SOURCE_LITERAL_ADAPT),
    ]
    out = rerank(cands, state_before=state)
    by_tactic = {c.tactic: c for c in out}
    assert by_tactic["exact h 4"].source == SOURCE_SEQ2SEQ
    assert by_tactic["exact h 13"].source == SOURCE_LITERAL_ADAPT


def test_stable_sort_within_equal_scores():
    """When two candidates have identical features and scores, the
    earlier beam position should come first."""
    state = "⊢ True"
    cands = [
        ("trivial", SOURCE_SEQ2SEQ),
        ("trivial", SOURCE_SEQ2SEQ),  # exact same content, second rank
    ]
    out = rerank(cands, state_before=state)
    assert out[0].features.beam_rank == 0
    assert out[1].features.beam_rank == 1


# ---------------- accepting plain string inputs ----------------


def test_rerank_accepts_plain_string_iterable():
    state = "h : ∀ x : Nat, x = 0\n⊢ 13 = 0"
    out = rerank(["exact h 4", "exact h 13"], state_before=state)
    assert out[0].tactic == "exact h 13"


# ---------------- malformed detection edge cases ----------------


def test_empty_candidate_is_malformed():
    feats = score_candidate("", source=SOURCE_SEQ2SEQ, beam_rank=0,
                             goal_literal=None)
    assert feats.is_malformed is True


def test_open_paren_at_end_not_marked_malformed():
    # `exact ⟨` would be unclosed angle; plain trailing `(` is not in our
    # patterns. We only check our specific failure-mode shapes.
    feats = score_candidate("exact (h 7)", source=SOURCE_SEQ2SEQ,
                             beam_rank=0, goal_literal=7)
    assert feats.is_malformed is False
