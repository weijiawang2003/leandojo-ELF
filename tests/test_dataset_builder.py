"""Tests for the verified-trace → dataset builder.

The builder's job is to refuse to fabricate next-state transitions:

  - mock records are ``"mock"`` quality (heuristic) and only included with
    ``allow_mock=True``;
  - lean-cli records are ``"theorem-level"`` (whole-file typecheck) and never
    promoted to real even though they have a ``state_after`` placeholder;
  - leandojo records are ``"real"`` only when they carry a real ``state_after``.

These tests pin those rules with hand-built synthetic JSONL fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mini_elf_lean.dataset_builder import (
    BuildFilters,
    LEAN_CLI_PLACEHOLDER,
    SplitConfig,
    _theorem_split,
    build_dataset,
    expand_inputs,
)
from mini_elf_lean.io_utils import write_jsonl


# ---- record factories ---------------------------------------------------


def _base(**over) -> dict:
    """A minimal TraceRecord-compatible dict with safe defaults; tests override."""
    rec = {
        "theorem_name": "thm_a",
        "theorem_statement": "(p : Prop) (h : p) : p",
        "state_before": "p : Prop\nh : p\n⊢ p",
        "tactic": "exact h",
        "state_after": "no goals",
        "success": True,
        "proof_finished": True,
        "num_goals_before": 1,
        "num_goals_after": 0,
        "state_changed": True,
        "backend": "leandojo",
        "source": "claude_code_agent",
        "model": "manual-file",
        "prompt_style": "diverse",
        "temperature": 0.0,
        "step_index": 0,
    }
    rec.update(over)
    return rec


def _read_jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---- positive cases ----


def test_leandojo_success_next_state_record_is_included_and_marked_real(tmp_path: Path) -> None:
    src = tmp_path / "traces.jsonl"
    write_jsonl(
        src,
        [
            _base(
                tactic="intro h",
                state_after="p q : Prop\nh : p\n⊢ q ∧ p",
                proof_finished=False,
                num_goals_after=1,
            )
        ],
    )
    out = tmp_path / "out"
    summary = build_dataset([src], out, filters=BuildFilters(backends=("leandojo",)))

    assert summary.records_included == 1
    rows = _read_jsonl(out / "next_tactic.jsonl")
    assert len(rows) == 1
    r = rows[0]
    assert r["verification_quality"] == "real"
    assert r["state_after_is_real"] is True
    assert r["state_after"] == "p q : Prop\nh : p\n⊢ q ∧ p"
    assert r["split"] in ("train", "val", "test")
    assert r["source_record_hash"]  # non-empty


def test_proof_finished_leandojo_record_keeps_no_goals_marker(tmp_path: Path) -> None:
    src = tmp_path / "traces.jsonl"
    write_jsonl(src, [_base()])  # default is exact-h finishing → state_after="no goals"
    out = tmp_path / "out"
    summary = build_dataset([src], out, filters=BuildFilters(backends=("leandojo",)))

    rows = _read_jsonl(out / "next_tactic.jsonl")
    assert len(rows) == 1
    r = rows[0]
    assert r["proof_finished"] is True
    assert r["state_after"] == "no goals"
    assert r["verification_quality"] == "real"
    assert r["state_after_is_real"] is True
    assert summary.by_verification_quality == {"real": 1}


def test_lean_cli_record_kept_as_theorem_level_not_real(tmp_path: Path) -> None:
    src = tmp_path / "traces.jsonl"
    write_jsonl(
        src,
        [
            _base(
                backend="lean-cli",
                state_after=LEAN_CLI_PLACEHOLDER,
                proof_finished=True,
                num_goals_after=0,
            )
        ],
    )
    out = tmp_path / "out"
    summary = build_dataset([src], out, filters=BuildFilters(backends=("lean-cli",)))

    rows = _read_jsonl(out / "next_tactic.jsonl")
    assert len(rows) == 1
    r = rows[0]
    assert r["backend"] == "lean-cli"
    assert r["verification_quality"] == "theorem-level"
    # CRITICAL: the placeholder string must not be promoted to a real state_after.
    assert r["state_after_is_real"] is False
    assert r["state_after"] == LEAN_CLI_PLACEHOLDER
    assert summary.by_verification_quality == {"theorem-level": 1}


# ---- exclusion cases ----


def test_failed_record_excluded_by_default_but_kept_with_flag(tmp_path: Path) -> None:
    src = tmp_path / "traces.jsonl"
    write_jsonl(
        src,
        [
            _base(
                backend="lean-cli", tactic="exact q", success=False, proof_finished=False,
                state_after=None, error="type mismatch", num_goals_after=1, state_changed=False,
            )
        ],
    )
    out = tmp_path / "out"

    # Default: failed records dropped.
    s1 = build_dataset([src], out, filters=BuildFilters(backends=("lean-cli",)))
    assert s1.records_included == 0
    assert s1.excluded["failed_excluded"] == 1

    # Opt-in: kept (still theorem-level quality, state_after_is_real=False).
    s2 = build_dataset(
        [src], tmp_path / "out2",
        filters=BuildFilters(backends=("lean-cli",), include_failed=True),
    )
    assert s2.records_included == 1
    rows = _read_jsonl(tmp_path / "out2" / "next_tactic.jsonl")
    assert rows[0]["success"] is False
    assert rows[0]["state_after_is_real"] is False
    assert rows[0]["state_after"] is None


def test_mock_record_excluded_unless_allow_mock(tmp_path: Path) -> None:
    src = tmp_path / "traces.jsonl"
    write_jsonl(src, [_base(backend="mock", state_after="no goals", tactic="rfl")])
    # Default backend allow-list doesn't include mock at all -> backend_filter excludes.
    s1 = build_dataset([src], tmp_path / "o1", filters=BuildFilters())
    assert s1.records_included == 0
    assert s1.excluded.get("backend_filter") == 1

    # Explicitly allow mock in the backend list but don't pass allow_mock -> mock_disallowed.
    s2 = build_dataset(
        [src], tmp_path / "o2",
        filters=BuildFilters(backends=("mock",), allow_mock=False),
    )
    assert s2.records_included == 0
    assert s2.excluded.get("mock_disallowed") == 1

    # With both -> included and tagged "mock" quality, state_after_is_real=False.
    s3 = build_dataset(
        [src], tmp_path / "o3",
        filters=BuildFilters(backends=("mock",), allow_mock=True),
    )
    assert s3.records_included == 1
    rows = _read_jsonl(tmp_path / "o3" / "next_tactic.jsonl")
    assert rows[0]["verification_quality"] == "mock"
    assert rows[0]["state_after_is_real"] is False


def test_duplicate_record_deduplicated_by_default(tmp_path: Path) -> None:
    src = tmp_path / "traces.jsonl"
    write_jsonl(src, [_base(), _base()])  # identical (theorem, state_before, tactic)
    s = build_dataset(
        [src], tmp_path / "out",
        filters=BuildFilters(backends=("leandojo",)),
    )
    assert s.records_included == 1
    assert s.excluded.get("duplicate") == 1


def test_no_dedup_keeps_duplicates(tmp_path: Path) -> None:
    src = tmp_path / "traces.jsonl"
    write_jsonl(src, [_base(), _base()])
    s = build_dataset(
        [src], tmp_path / "out",
        filters=BuildFilters(backends=("leandojo",), dedup=False),
    )
    assert s.records_included == 2
    rows = _read_jsonl(tmp_path / "out" / "next_tactic.jsonl")
    # Both rows share a fingerprint (legitimate: same logical transition).
    assert rows[0]["source_record_hash"] == rows[1]["source_record_hash"]


def test_length_filters(tmp_path: Path) -> None:
    src = tmp_path / "traces.jsonl"
    write_jsonl(
        src,
        [
            _base(tactic="x" * 50, state_before="s" * 50),
            _base(theorem_name="thm_b", tactic="x" * 5, state_before="s" * 5),
        ],
    )
    # Cap tactic length -> drops the long-tactic row only.
    s_tac = build_dataset(
        [src], tmp_path / "o1",
        filters=BuildFilters(backends=("leandojo",), max_tactic_len=10),
    )
    assert s_tac.records_included == 1
    assert s_tac.excluded.get("tactic_too_long") == 1

    # Cap state length -> drops the long-state row only.
    s_st = build_dataset(
        [src], tmp_path / "o2",
        filters=BuildFilters(backends=("leandojo",), max_state_len=10),
    )
    assert s_st.records_included == 1
    assert s_st.excluded.get("state_too_long") == 1


def test_proof_finished_can_be_excluded(tmp_path: Path) -> None:
    src = tmp_path / "traces.jsonl"
    write_jsonl(
        src,
        [
            _base(theorem_name="thm_a", tactic="exact h"),  # proof_finished=True default
            _base(
                theorem_name="thm_b", tactic="intro h",
                state_after="p q : Prop\nh : p\n⊢ q", proof_finished=False, num_goals_after=1,
            ),
        ],
    )
    s = build_dataset(
        [src], tmp_path / "out",
        filters=BuildFilters(backends=("leandojo",), include_proof_finished=False),
    )
    assert s.records_included == 1
    rows = _read_jsonl(tmp_path / "out" / "next_tactic.jsonl")
    assert rows[0]["proof_finished"] is False
    assert s.excluded.get("proof_finished_excluded") == 1


def test_unknown_backend_is_excluded_and_counted(tmp_path: Path) -> None:
    src = tmp_path / "traces.jsonl"
    write_jsonl(src, [_base(backend="repl-experimental")])
    s = build_dataset([src], tmp_path / "out", filters=BuildFilters(backends=("leandojo",)))
    assert s.records_included == 0
    # Unknown backends are caught BEFORE the explicit backend_filter check, so
    # the user sees the actual backend value in the reason.
    assert any(k.startswith("unknown_backend:") for k in s.excluded)


def test_leandojo_with_lean_cli_placeholder_is_refused(tmp_path: Path) -> None:
    """A leandojo record carrying the lean-cli placeholder is corrupt
    cross-contamination — we refuse rather than silently include."""
    src = tmp_path / "traces.jsonl"
    write_jsonl(src, [_base(state_after=LEAN_CLI_PLACEHOLDER)])
    s = build_dataset([src], tmp_path / "out", filters=BuildFilters(backends=("leandojo",)))
    assert s.records_included == 0
    assert s.excluded.get("unverifiable_classification") == 1


# ---- outputs ----


def test_plain_tactics_text_dedupes_and_sorts(tmp_path: Path) -> None:
    src = tmp_path / "traces.jsonl"
    write_jsonl(
        src,
        [
            _base(theorem_name="t1", tactic="rfl"),
            _base(theorem_name="t2", tactic="rfl"),  # dup tactic, diff theorem -> still 1 line
            _base(theorem_name="t3", tactic="omega"),
            _base(
                theorem_name="t4", tactic="intro h\n  exact h",  # multi-line tactic
                state_after="⊢ q", proof_finished=False,
            ),
        ],
    )
    s = build_dataset(
        [src], tmp_path / "out",
        filters=BuildFilters(backends=("leandojo",)),
    )
    lines = (tmp_path / "out" / "plain_tactics.txt").read_text(encoding="utf-8").splitlines()
    assert lines == sorted(lines)
    # 3 distinct tactics: rfl, omega, "intro h\\n  exact h" (newline escaped).
    assert "rfl" in lines and "omega" in lines
    assert "intro h\\n  exact h" in lines
    assert s.unique_tactics == 3


def test_theorem_splits_file_has_all_buckets_and_seed(tmp_path: Path) -> None:
    src = tmp_path / "traces.jsonl"
    write_jsonl(
        src,
        [_base(theorem_name=f"thm_{i}", tactic=f"tac_{i}") for i in range(20)],
    )
    s = build_dataset(
        [src], tmp_path / "out",
        filters=BuildFilters(backends=("leandojo",)),
        splits=SplitConfig(train=0.6, val=0.2, test=0.2, seed=123),
    )
    payload = json.loads((tmp_path / "out" / "theorem_splits.json").read_text("utf-8"))
    assert set(payload["train"] + payload["val"] + payload["test"]) == {f"thm_{i}" for i in range(20)}
    assert payload["seed"] == 123
    assert payload["split_fractions"] == {"train": 0.6, "val": 0.2, "test": 0.2}
    assert s.splits["train"] + s.splits["val"] + s.splits["test"] == 20


def test_summary_json_records_exclusion_reasons(tmp_path: Path) -> None:
    src = tmp_path / "traces.jsonl"
    write_jsonl(
        src,
        [
            _base(),                                   # included
            _base(),                                   # duplicate
            _base(theorem_name="m", backend="mock"),   # mock_disallowed (via default backends)
            _base(theorem_name="f", success=False, state_after=None, proof_finished=False,
                  backend="lean-cli", error="x"),       # failed_excluded
        ],
    )
    s = build_dataset([src], tmp_path / "out")
    payload = json.loads((tmp_path / "out" / "summary.json").read_text("utf-8"))
    assert payload["records_included"] == 1
    assert payload["excluded"]["duplicate"] == 1
    assert payload["excluded"]["failed_excluded"] == 1
    # Mock isn't in the default backend list at all → backend_filter.
    assert payload["excluded"]["backend_filter"] == 1


# ---- determinism + leakage ----


def test_split_assignment_is_deterministic_and_stable(tmp_path: Path) -> None:
    """Same seed -> same split for the same theorem, regardless of other input."""
    cfg = SplitConfig(seed=7)
    s1 = _theorem_split("alpha", cfg)
    s2 = _theorem_split("alpha", cfg)
    assert s1 == s2

    # Adding new theorems must NOT shift alpha's split (no leakage risk on
    # incremental builds).
    src_a = tmp_path / "a.jsonl"
    src_b = tmp_path / "b.jsonl"
    write_jsonl(src_a, [_base(theorem_name="alpha")])
    write_jsonl(src_b, [_base(theorem_name="alpha"), _base(theorem_name="beta", tactic="x")])
    out_a = build_dataset([src_a], tmp_path / "oa", filters=BuildFilters(backends=("leandojo",)))
    out_b = build_dataset([src_b], tmp_path / "ob", filters=BuildFilters(backends=("leandojo",)))
    splits_a = json.loads((tmp_path / "oa" / "theorem_splits.json").read_text("utf-8"))
    splits_b = json.loads((tmp_path / "ob" / "theorem_splits.json").read_text("utf-8"))
    a_split = next(k for k in ("train", "val", "test") if "alpha" in splits_a[k])
    b_split = next(k for k in ("train", "val", "test") if "alpha" in splits_b[k])
    assert a_split == b_split


def test_all_records_of_a_theorem_land_in_one_split(tmp_path: Path) -> None:
    src = tmp_path / "traces.jsonl"
    write_jsonl(
        src,
        [
            _base(theorem_name="multi", tactic="intro h",
                  state_after="⊢ q", proof_finished=False),
            _base(theorem_name="multi", tactic="exact h"),  # proof_finished default
        ],
    )
    build_dataset([src], tmp_path / "out", filters=BuildFilters(backends=("leandojo",)))
    rows = _read_jsonl(tmp_path / "out" / "next_tactic.jsonl")
    assert {r["split"] for r in rows} == {rows[0]["split"]}


# ---- expand_inputs helper ----


def test_expand_inputs_missing_literal_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        expand_inputs([str(tmp_path / "nope.jsonl")])


def test_expand_inputs_glob_empty_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        expand_inputs([str(tmp_path / "*.jsonl")])  # nothing in tmp_path
