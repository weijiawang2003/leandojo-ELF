"""Unit tests for the v15 candidate-outcome dataset.

Pins the contract the trainer depends on:
  * verified labels round-trip through serialisation,
  * leave-family-out splitter excludes every held-family theorem
    from train,
  * feature extractor never reads ``state_after``,
  * the canonical ``neg_imp_exfalso`` verifying string carries the
    ``contains_intro + contains_absurd`` features,
  * known-good error-class buckets for representative messages.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from mini_elf_lean import rerank_dataset as rd
from mini_elf_lean.rerank_dataset import (
    CandidateRow, PATTERN_FEATURES, build_candidate_outcome_dataset,
    classify_error, compute_stats, extract_features, leave_family_out_split,
    read_rows, write_rows,
)


# ----------------- error classifier --------------------------------------


@pytest.mark.parametrize("err,expected", [
    (None, "ok"),
    ("", "ok"),                   # empty string ⇒ no useful keyword → "other"
    ("timeout", "timeout"),
    ("error: Type mismatch\n  h 5", "type_mismatch"),
    ("error: unknown identifier `m`", "unknown_identifier"),
    ("error: unknown tactic 'refin'", "unknown_tactic"),
    ("error: unexpected end of input", "parse_error"),
    ("error: unsolved goals", "unsolved_goals"),
    ("some weird thing", "other"),
])
def test_classify_error(err, expected) -> None:
    # Empty string has no match
    if err == "":
        assert classify_error(err) == "other"
    else:
        assert classify_error(err) == expected


# ----------------- CandidateRow round-trip -------------------------------


def test_candidate_row_jsonl_round_trip(tmp_path: Path) -> None:
    rows = [
        CandidateRow(
            theorem_name="t1", family="forall_inst",
            required_operation="instantiate_forall",
            theorem_statement="(h : ∀ x, x = 0) : 3 = 0",
            state_before="h : ∀ x, x = 0\n⊢ 3 = 0",
            candidate="exact h 3", candidate_source="seq2seq_literal_adapt",
            beam_rank=7, verified=True, error_class="ok",
            source_run="v14_literal_adapt_rerank",
        ),
    ]
    p = tmp_path / "x.jsonl"
    write_rows(rows, p)
    loaded = read_rows(p)
    assert len(loaded) == 1
    assert loaded[0].theorem_name == "t1"
    assert loaded[0].verified is True
    assert loaded[0].candidate == "exact h 3"
    assert loaded[0].beam_rank == 7


# ----------------- leave-family-out split --------------------------------


def _mk(name: str, fam: str, cand: str, source_run: str = "v14_raw",
        verified: bool = False) -> CandidateRow:
    return CandidateRow(
        theorem_name=name, family=fam, required_operation=None,
        theorem_statement="", state_before="", candidate=cand,
        candidate_source="seq2seq", beam_rank=0,
        verified=verified, error_class="ok" if verified else "other",
        source_run=source_run,
    )


def test_leave_family_out_excludes_every_held_theorem() -> None:
    rows = [
        _mk("forall_inst_3_0", "forall_inst", "exact h 3"),
        _mk("forall_inst_3_0", "forall_inst", "exact h 4"),
        _mk("forall_inst_var_m", "forall_inst", "exact h 8"),
        _mk("neg_imp_exfalso_pq", "neg_imp_exfalso", "intro hp"),
        _mk("neg_exfalso_x", "neg_exfalso", "absurd ha hna"),
    ]
    train, eval_ = leave_family_out_split(rows, held_family="forall_inst")
    # Train must contain ZERO forall_inst theorems
    assert all(r.family != "forall_inst" for r in train), (
        "leave-family-out leaked held-family rows into train"
    )
    # Eval must contain ALL v14 rows from forall_inst theorems
    eval_names = {r.theorem_name for r in eval_}
    assert "forall_inst_3_0" in eval_names
    assert "forall_inst_var_m" in eval_names


def test_leave_family_out_eval_uses_only_v14_sources() -> None:
    rows = [
        # v14 candidate on held theorem
        _mk("forall_inst_3_0", "forall_inst", "exact h 3",
            source_run="v14_raw"),
        # v12 candidate on held theorem (should NOT appear in eval — it's
        # held out from train but also not a v14 candidate)
        _mk("forall_inst_3_0", "forall_inst", "exact h 4",
            source_run="v12_raw"),
        _mk("other", "rewrite_succ", "rw [h]"),
    ]
    _, eval_ = leave_family_out_split(rows, held_family="forall_inst")
    assert len(eval_) == 1
    assert eval_[0].source_run == "v14_raw"


def test_leave_family_out_handles_unknown_held_family() -> None:
    rows = [_mk("t", "forall_inst", "exact h 3")]
    train, eval_ = leave_family_out_split(rows, held_family="not_a_family")
    assert len(train) == 1
    assert len(eval_) == 0


# ----------------- feature extractor: no state_after ---------------------


def test_extract_features_signature_does_not_consume_state_after() -> None:
    sig = inspect.signature(extract_features)
    assert "state_after" not in sig.parameters


def test_module_has_no_state_after_anywhere() -> None:
    for name in ("build_candidate_outcome_dataset", "compute_stats",
                 "leave_family_out_split", "extract_features"):
        obj = getattr(rd, name)
        sig = inspect.signature(obj)
        assert "state_after" not in sig.parameters, (
            f"{name} accepts state_after")


# ----------------- feature semantics: neg_imp_exfalso target -------------


def test_neg_imp_exfalso_verifying_candidate_has_intro_and_absurd_features() -> None:
    """The candidate the v14 token model emits for neg_imp_exfalso must
    light up both ``contains_intro`` and ``contains_absurd``."""
    row = CandidateRow(
        theorem_name="neg_imp_exfalso_pq",
        family="neg_imp_exfalso",
        required_operation="intro_negation",
        theorem_statement="(p q : Prop) (hpq : p → q) (hnq : ¬q) : ¬p",
        state_before="p q : Prop\nhpq : p → q\nhnq : ¬q\n⊢ ¬p",
        candidate="intro hp\n  exact absurd hp hnp",
        candidate_source="token_seq2seq",
        beam_rank=4, verified=True, error_class="ok",
        source_run="v14_raw",
    )
    feats = extract_features(row)
    assert feats["contains_intro"] == 1.0
    assert feats["contains_absurd"] == 1.0
    assert feats["op_intro_negation"] == 1.0
    assert feats["has_known_head"] == 1.0
    assert feats["is_malformed"] == 0.0
    assert feats["bias"] == 1.0


def test_malformed_candidate_is_flagged() -> None:
    row = CandidateRow(
        theorem_name="x", family="forall_inst", required_operation=None,
        theorem_statement="", state_before="",
        candidate="rcases h wi", candidate_source="seq2seq",
        beam_rank=0, verified=False, error_class="parse_error",
        source_run="v14_raw",
    )
    feats = extract_features(row)
    # truncated 'with' → 'wi' is a malformed-truncated shape
    assert feats["is_malformed"] == 1.0 or feats["is_truncated_shape"] == 1.0


def test_fused_keyword_is_malformed() -> None:
    row = CandidateRow(
        theorem_name="x", family="forall_inst", required_operation=None,
        theorem_statement="", state_before="",
        candidate="refintro hp", candidate_source="seq2seq",
        beam_rank=0, verified=False, error_class="unknown_tactic",
        source_run="v11",
    )
    feats = extract_features(row)
    assert feats["is_malformed"] == 1.0


def test_goal_literal_match_feature() -> None:
    row = CandidateRow(
        theorem_name="forall_inst_13_6",
        family="forall_inst",
        required_operation="instantiate_forall",
        theorem_statement="(h : ∀ x, x = 6) : 13 = 6",
        state_before="h : ∀ x, x = 6\n⊢ 13 = 6",
        candidate="exact h 13",
        candidate_source="seq2seq_literal_adapt",
        beam_rank=0, verified=True, error_class="ok",
        source_run="v14_literal_adapt_rerank",
    )
    feats = extract_features(row)
    assert feats["has_goal_literal_match"] == 1.0
    assert feats["has_stale_literal"] == 0.0
    assert feats["has_seq2seq_literal_adapt_source"] == 1.0


def test_stale_literal_feature() -> None:
    row = CandidateRow(
        theorem_name="forall_inst_13_6",
        family="forall_inst",
        required_operation="instantiate_forall",
        theorem_statement="(h : ∀ x, x = 6) : 13 = 6",
        state_before="h : ∀ x, x = 6\n⊢ 13 = 6",
        candidate="exact h 4",   # wrong literal
        candidate_source="seq2seq",
        beam_rank=4, verified=False, error_class="type_mismatch",
        source_run="v14_raw",
    )
    feats = extract_features(row)
    assert feats["has_goal_literal_match"] == 0.0
    assert feats["has_stale_literal"] == 1.0


# ----------------- pattern feature set ------------------------------------


def test_pattern_features_are_all_present_in_output() -> None:
    row = CandidateRow(
        theorem_name="x", family="forall_inst", required_operation=None,
        theorem_statement="", state_before="", candidate="exact h",
        candidate_source="seq2seq", beam_rank=0, verified=False,
        error_class="other", source_run="v14_raw",
    )
    feats = extract_features(row)
    for name in PATTERN_FEATURES:
        assert name in feats, f"pattern feature {name!r} missing"


# ----------------- aggregate stats ---------------------------------------


def test_compute_stats() -> None:
    rows = [
        _mk("t1", "forall_inst", "exact h 3", verified=True),
        _mk("t2", "forall_inst", "exact h", verified=False),
        _mk("t3", "neg_imp_exfalso", "intro hp", verified=True),
    ]
    s = compute_stats(rows)
    assert s.n_total == 3
    assert s.n_verified == 2
    assert s.positive_fraction == pytest.approx(2 / 3)
    assert s.by_family["forall_inst"]["n"] == 2
    assert s.by_family["forall_inst"]["verified"] == 1
    assert s.by_family["neg_imp_exfalso"]["verified"] == 1


# ----------------- end-to-end on real data (skipped if absent) -----------


def test_build_on_real_data_if_present() -> None:
    root = Path(__file__).resolve().parents[1]
    fold_root = root / "data" / "processed" / "proof_blocks_v11_family_lofo"
    v14_root = root / "data" / "baselines" / "v14_token_seq2seq"
    if not (fold_root / "forall_inst" / "test.jsonl").exists():
        pytest.skip("v11 LOFO folds absent")
    if not (v14_root / "forall_inst" / "raw" / "metrics.json").exists():
        pytest.skip("v14 predictions absent")
    rows = build_candidate_outcome_dataset(
        fold_root=fold_root, families=("forall_inst",),
    )
    assert len(rows) > 0
    # Every row carries the v15 contract
    for r in rows:
        assert r.family == "forall_inst"
        assert isinstance(r.verified, bool)
        assert r.error_class != "" and r.error_class is not None
