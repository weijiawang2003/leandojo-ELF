"""Tests for v23 reranker features (Part 2) — scoring-only invariants."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.v23_reranker_features import (  # noqa: E402
    extract_v23_features, unbound_identifier_count,
)

NEG_STATE = "p : Prop\nh : p → False\n⊢ ¬p"


def test_unbound_catches_hp_not_in_context():
    # `hp` is NOT in the initial context and not bound by the candidate.
    assert unbound_identifier_count("exact False.elim (h hp)", NEG_STATE) >= 1
    # an in-scope hyp is not flagged.
    assert unbound_identifier_count("exact h", NEG_STATE) == 0


def test_locally_bound_intro_name_not_unbound():
    # `hp` introduced by `intro hp` must NOT count as unbound.
    assert unbound_identifier_count("intro hp\n  exact absurd hp h", NEG_STATE) == 0


def test_anon_constructor_names_bound():
    st = "P : Nat → Prop\nh : ∃ n, P n\n⊢ ∃ m, P m"
    assert unbound_identifier_count("cases h with\n  | intro n hn => exact ⟨n, hn⟩", st) == 0
    assert unbound_identifier_count("rcases h with ⟨n, hn⟩\n  exact ⟨n, hn⟩", st) == 0


def test_abstract_pattern_feature_present_for_valid_candidate():
    f = extract_v23_features({"candidate": "exact ⟨3, h⟩", "state_before":
                              "P : Nat → Prop\nh : P 3\n⊢ ∃ n, P n",
                              "category": "exists", "beam_rank": 0,
                              "required_operation": "destruct_exists",
                              "candidate_source": "token_seq2seq",
                              "theorem_name": "x"})
    # the pattern logcount feature exists (0 without a bag, but present)
    assert "v23_abstract_pattern_logcount" in f
    assert "v23_binds_cleanly" in f
    assert f["v23_binds_cleanly"] == 1.0  # all idents resolve


def test_negation_candidate_gets_positive_features():
    f = extract_v23_features({"candidate": "exact (h hp).elim",
                              "state_before": NEG_STATE, "category": "negation",
                              "beam_rank": 0, "required_operation": "intro_negation",
                              "candidate_source": "token_seq2seq",
                              "theorem_name": "x"})
    assert f["v23_neg_dot_elim"] == 1.0
    # negation category cue active
    assert f.get("v23_cat_negation") == 1.0


def test_features_are_scoring_only_no_placeholder():
    """The feature dict must never contain a candidate/placeholder string —
    it is numeric only (the reranker reorders raw candidates, never emits
    an abstract pattern as output)."""
    f = extract_v23_features({"candidate": "exact h.1", "state_before":
                              "p q : Prop\nh : p ∧ q\n⊢ p", "category":
                              "conjunction", "beam_rank": 0,
                              "required_operation": None,
                              "candidate_source": "token_seq2seq",
                              "theorem_name": "x"})
    assert all(isinstance(v, float) for v in f.values())
    # no feature VALUE is a string / placeholder token
    assert "__" not in "".join(str(v) for v in f.values())


def test_category_toggle_changes_feature_set():
    row = {"candidate": "intro hp\n  exact absurd hp h", "state_before": NEG_STATE,
           "category": "negation", "beam_rank": 0, "required_operation": "intro_negation",
           "candidate_source": "token_seq2seq", "theorem_name": "x"}
    plain = extract_v23_features(row, category_features=False)
    cat = extract_v23_features(row, category_features=True)
    assert "v23_cat_negation" not in plain
    assert "v23_cat_negation" in cat
    # grounding features are in BOTH
    assert "v23_unbound_ident_count" in plain and "v23_unbound_ident_count" in cat
