"""Tests for the per-theorem / per-tactic / per-error corpus audit.

Hand-built synthetic record dicts so we don't have to round-trip through
JSONL — keeps the assertions precise about what the audit actually counts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mini_elf_lean.corpus_audit import (
    audit,
    audit_files,
    load_pattern_families,
    load_theorem_splits,
    normalize_error,
)


def _rec(**over) -> dict:
    base = {
        "theorem_name": "t1",
        "state_before": "⊢ p",
        "tactic": "exact h",
        "success": True,
        "error": None,
    }
    base.update(over)
    return base


# ---- normalization ----


def test_normalize_strips_unix_tempfile_path() -> None:
    err = "/tmp/mini_elf_lean_abc12.lean:2:8: error: Type mismatch\n  q has type Prop"
    assert normalize_error(err) == "error: Type mismatch"


def test_normalize_strips_windows_tempfile_path() -> None:
    err = (
        "C:\\Users\\wangw\\AppData\\Local\\Temp\\mini_elf_lean_zxc.lean:2:2: "
        "error(lean.unknownIdentifier): Unknown identifier `q`"
    )
    assert normalize_error(err) == "error(lean.unknownIdentifier): Unknown identifier `q`"


def test_normalize_handles_none_and_empty() -> None:
    assert normalize_error(None) == ""
    assert normalize_error("") == ""


# ---- per-theorem rates ----


def test_per_theorem_success_rate_and_zero_success_listing() -> None:
    recs = [
        _rec(theorem_name="alpha", tactic="rfl", success=True),
        _rec(theorem_name="alpha", tactic="exact h", success=True),
        _rec(theorem_name="alpha", tactic="exact garbage", success=False, error="x"),
        _rec(theorem_name="beta", tactic="exact h", success=False, error="x"),
        _rec(theorem_name="beta", tactic="rfl", success=False, error="y"),
        _rec(theorem_name="gamma", tactic="trivial", success=True),
    ]
    a = audit(recs)
    assert a.records_total == 6 and a.records_success == 3 and a.records_failed == 3
    assert a.overall_success_rate == pytest.approx(0.5)
    assert a.by_theorem["alpha"] == {"attempts": 3, "successes": 2,
                                     "success_rate": pytest.approx(2 / 3)}
    assert a.by_theorem["beta"]["success_rate"] == 0.0
    assert a.zero_success_theorems == ["beta"]


def test_zero_success_theorems_alphabetical_when_multiple() -> None:
    recs = [
        _rec(theorem_name="zeta", success=False, error="x"),
        _rec(theorem_name="alpha", success=False, error="x"),
        _rec(theorem_name="m", success=True),
    ]
    a = audit(recs)
    assert a.zero_success_theorems == ["alpha", "zeta"]  # sorted


# ---- per-tactic-head rates ----


def test_per_tactic_head_breaks_out_first_token_and_counts_attempts() -> None:
    recs = [
        _rec(tactic="exact h", success=True),
        _rec(tactic="exact h", success=True, theorem_name="t2", state_before="⊢ q"),
        _rec(tactic="exact garbage", success=False, error="x",
             theorem_name="t3", state_before="⊢ r"),
        _rec(tactic="rfl", success=True, theorem_name="t4", state_before="⊢ n=n"),
        _rec(tactic="rfl", success=False, error="rfl failed",
             theorem_name="t5", state_before="⊢ 0+n=n"),
    ]
    a = audit(recs)
    # exact: 3 attempts, 2 succ; rfl: 2 attempts, 1 succ.
    assert a.by_tactic_head["exact"] == {"attempts": 3, "successes": 2,
                                          "success_rate": pytest.approx(2 / 3)}
    assert a.by_tactic_head["rfl"]["success_rate"] == 0.5
    # Order is by attempts desc — exact (3) should appear before rfl (2).
    heads = list(a.by_tactic_head.keys())
    assert heads.index("exact") < heads.index("rfl")


def test_empty_tactic_string_grouped_as_empty_marker() -> None:
    a = audit([_rec(tactic="", success=False, error="x")])
    assert "<empty>" in a.by_tactic_head


# ---- duplicate detection ----


def test_duplicate_attempts_are_reported_with_count() -> None:
    recs = [
        _rec(theorem_name="t1", state_before="s", tactic="rfl", success=True),
        _rec(theorem_name="t1", state_before="s", tactic="rfl", success=False, error="x"),
        _rec(theorem_name="t1", state_before="s", tactic="rfl", success=True),
        _rec(theorem_name="t1", state_before="s", tactic="exact h", success=True),  # unique
        _rec(theorem_name="t2", state_before="s", tactic="rfl", success=True),  # different thm
    ]
    a = audit(recs)
    assert len(a.duplicate_tactic_attempts) == 1
    d = a.duplicate_tactic_attempts[0]
    assert d == {
        "theorem_name": "t1",
        "state_before_preview": "s",
        "tactic": "rfl",
        "count": 3,
    }


def test_duplicates_truncate_long_state_for_preview() -> None:
    long_state = "x" * 200
    recs = [_rec(state_before=long_state)] * 3
    a = audit(recs)
    assert a.duplicate_tactic_attempts
    preview = a.duplicate_tactic_attempts[0]["state_before_preview"]
    assert preview.endswith("...") and len(preview) == 63


# ---- error grouping ----


def test_top_errors_group_after_path_normalization() -> None:
    recs = [
        _rec(success=False, error="/tmp/mini_elf_lean_aaa.lean:2:8: error: Type mismatch\n  q"),
        _rec(success=False, error="/tmp/mini_elf_lean_bbb.lean:3:9: error: Type mismatch\n  r"),
        _rec(success=False, error="/tmp/mini_elf_lean_ccc.lean:2:8: "
                                  "error(lean.unknownIdentifier): Unknown identifier `q`"),
        _rec(success=True),  # not in errors
    ]
    a = audit(recs, top_errors=5)
    assert a.top_errors[0]["error"] == "error: Type mismatch"
    assert a.top_errors[0]["count"] == 2
    # All listed errors must be distinct after normalization.
    assert len({e["error"] for e in a.top_errors}) == len(a.top_errors)


def test_top_errors_respects_limit() -> None:
    recs = [
        _rec(success=False, error=f"/tmp/mini_elf_lean_x.lean:2:8: error: kind{i}")
        for i in range(20)
    ]
    a = audit(recs, top_errors=3)
    assert len(a.top_errors) == 3


def test_records_total_zero_yields_zero_rate_no_division_error() -> None:
    a = audit([])
    assert a.records_total == 0 and a.overall_success_rate == 0.0
    # Output dict must still be valid JSON.
    json.dumps(a.to_dict())


# ---- file loading ----


def test_audit_files_reads_jsonl_and_combines(tmp_path: Path) -> None:
    ok = tmp_path / "v.jsonl"
    bad = tmp_path / "f.jsonl"
    ok.write_text(
        json.dumps(_rec(theorem_name="t1", tactic="rfl", success=True)) + "\n",
        encoding="utf-8",
    )
    bad.write_text(
        json.dumps(_rec(theorem_name="t1", tactic="exact garbage", success=False,
                        error="/tmp/mini_elf_lean_z.lean:1:1: error: Type mismatch")) + "\n",
        encoding="utf-8",
    )
    a = audit_files([ok, bad])
    assert a.records_total == 2
    assert a.by_theorem["t1"]["successes"] == 1
    assert a.top_errors[0]["error"] == "error: Type mismatch"


def test_audit_files_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        audit_files([tmp_path / "nope.jsonl"])


# ---- pattern-family breakdown ----


def _family_records() -> list:
    # imp_identity: 2 theorems (one train, one val), and_intro: 1 theorem (test only)
    return [
        _rec(theorem_name="imp_id_p", tactic="exact h", success=True),
        _rec(theorem_name="imp_id_p", tactic="rfl", success=False, error="x"),
        _rec(theorem_name="imp_id_q", tactic="exact h", success=True),
        _rec(theorem_name="and_intro_pq", tactic="exact ⟨hp, hq⟩", success=True),
    ]


_FAMILIES = {"imp_id_p": "imp_identity", "imp_id_q": "imp_identity", "and_intro_pq": "and_intro"}


def test_by_pattern_family_aggregates_success_and_theorem_counts() -> None:
    a = audit(_family_records(), theorem_families=_FAMILIES)
    bf = a.by_pattern_family
    assert bf["imp_identity"]["n_theorems"] == 2
    assert bf["imp_identity"]["attempts"] == 3
    assert bf["imp_identity"]["successes"] == 2
    assert bf["and_intro"]["n_theorems"] == 1 and bf["and_intro"]["successes"] == 1
    # No splits supplied -> no per-split counts, no warnings.
    assert "splits" not in bf["imp_identity"]
    assert a.pattern_coverage_warnings == []


def test_pattern_family_split_distribution_and_warnings() -> None:
    splits = {"imp_id_p": "train", "imp_id_q": "val", "and_intro_pq": "test"}
    a = audit(_family_records(), theorem_families=_FAMILIES, theorem_splits=splits)
    bf = a.by_pattern_family
    # imp_identity spans train+val -> transferable, no warning.
    assert bf["imp_identity"]["splits"] == {"train": 1, "val": 1, "test": 0}
    assert bf["imp_identity"]["in_train"] and bf["imp_identity"]["in_eval"]
    # and_intro is test-only -> only-in-eval warning + per-theorem no-train warning.
    assert bf["and_intro"]["splits"] == {"train": 0, "val": 0, "test": 1}
    warns = " ".join(a.pattern_coverage_warnings)
    assert "and_intro" in warns and "only in eval" in warns
    assert "and_intro_pq" in warns and "no train theorem" in warns


def test_pattern_family_only_in_train_warns_never_evaluated() -> None:
    recs = [_rec(theorem_name="t_only_train", tactic="rfl", success=True)]
    fams = {"t_only_train": "eq_refl"}
    splits = {"t_only_train": "train"}
    a = audit(recs, theorem_families=fams, theorem_splits=splits)
    warns = " ".join(a.pattern_coverage_warnings)
    assert "eq_refl" in warns and "only in train" in warns


def test_load_pattern_families_reads_metadata(tmp_path: Path) -> None:
    p = tmp_path / "seeds.jsonl"
    p.write_text(
        "# comment\n"
        + json.dumps({"theorem_name": "t1", "metadata": {"pattern_family": "imp_identity"}}) + "\n"
        + json.dumps({"theorem_name": "t2", "metadata": {}}) + "\n"  # no family -> omitted
        + json.dumps({"theorem_name": "t3", "metadata": {"pattern_family": "and_intro"}}) + "\n",
        encoding="utf-8",
    )
    fams = load_pattern_families(p)
    assert fams == {"t1": "imp_identity", "t3": "and_intro"}


def test_load_theorem_splits_inverts_lists(tmp_path: Path) -> None:
    p = tmp_path / "splits.json"
    p.write_text(
        json.dumps({"train": ["a", "b"], "val": ["c"], "test": ["d"], "seed": 42}),
        encoding="utf-8",
    )
    s = load_theorem_splits(p)
    assert s == {"a": "train", "b": "train", "c": "val", "d": "test"}
