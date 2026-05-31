"""v26 Mathlib specialist corpus tests: verifier-parser unit tests (no Lean)
plus produced-artifact invariants."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mini_elf_lean.mathlib_verifier import BatchMathlibVerifier, MATHLIB_IMPORT

ROOT = Path(__file__).resolve().parents[1]
VERIFIED = ROOT / "data" / "traces" / "v26_mathlib_specialist_verified.jsonl"
FAILED = ROOT / "data" / "traces" / "v26_mathlib_specialist_failed.jsonl"
SUMMARY = ROOT / "data" / "processed" / "v26_mathlib_specialist" / "summary.json"


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---- verifier parser/attribution unit tests (Lean-free) ---- #

def test_render_emits_example_per_candidate_with_sentinels():
    v = BatchMathlibVerifier.__new__(BatchMathlibVerifier)  # avoid __init__/lake
    v.imports = []
    src, ranges = BatchMathlibVerifier._render(v, [
        ("t0", "(n : Nat) : n + 0 = n", "rfl"),
        ("t1", "(p : Prop) (h : p) : p", "exact h"),
    ])
    lines = src.splitlines()
    starts = [s for (_i, s, _e) in ranges]
    assert starts == sorted(starts) and len(set(starts)) == 2  # strictly increasing, unique
    for (_i, s, _e) in ranges:
        assert lines[s - 1].startswith("example ")
    assert any("True.intro" in ln for ln in lines)  # sentinel present


def test_attribute_greatest_start_leq_line():
    # candidates start at lines 2 and 8; a leaked diag at line 6 (between them,
    # i.e. on a sentinel) must blame candidate 0, not candidate 1.
    starts = [2, 8]
    diags = [(3, "error: foo"), (6, "error: leaked"), (9, "error: bar")]
    att = BatchMathlibVerifier._attribute(starts, diags)
    assert att[0] == ["error: foo", "error: leaked"]
    assert att[1] == ["error: bar"]


def test_attribute_ignores_preamble_diagnostics():
    att = BatchMathlibVerifier._attribute([5], [(1, "error: import"), (6, "error: real")])
    assert att[0] == ["error: real"]


def test_pick_error_prefers_root_cause_over_unsolved_goals():
    msgs = ["error: unsolved goals", "error: (lean.unknownIdentifier): Unknown identifier `f`"]
    assert "Unknown identifier" in BatchMathlibVerifier._pick_error(msgs)
    assert BatchMathlibVerifier._pick_error([]) is None
    assert BatchMathlibVerifier._pick_error(["error: unsolved goals"]) == "error: unsolved goals"


def test_parse_diagnostics_extracts_lines_for_this_file():
    v = BatchMathlibVerifier.__new__(BatchMathlibVerifier)
    stderr = ("/tmp/foo_abc.lean:4:7: error: unsolved goals\n"
              "n : ℕ\n⊢ n + 0 = n\n"
              "/tmp/foo_abc.lean:6:0: warning: declaration uses 'sorry'\n"
              "/other/path.lean:9:0: error: not ours\n")
    diags = BatchMathlibVerifier._parse_diagnostics(v, "/tmp/foo_abc.lean", "", stderr)
    lines = [ln for ln, _m in diags]
    assert 4 in lines and 6 in lines  # error + sorry-warning for our file
    assert 9 not in lines             # other file excluded


# ---- produced-artifact invariants ---- #

@pytest.mark.skipif(not VERIFIED.exists(), reason="corpus not generated")
def test_verified_rows_have_required_metadata():
    rows = _read(VERIFIED)
    assert len(rows) >= 150  # target 150-300
    needed = {"theorem_name", "theorem_statement", "state_before", "tactic",
              "category", "expected_skill", "proof_head", "uses_simp",
              "uses_mathlib_lemma", "uses_set", "uses_order", "mathlib"}
    for r in rows:
        assert needed <= set(r)
        assert r["verified"] is True and r["mathlib"] is True
        assert r["imports"] == [MATHLIB_IMPORT]
        assert "state_after" not in r  # never present


@pytest.mark.skipif(not VERIFIED.exists(), reason="corpus not generated")
def test_corpus_covers_target_categories_including_set_and_order():
    rows = _read(VERIFIED)
    cats = {r["category"] for r in rows}
    assert {"set", "nat", "list", "logic", "bool_option", "function"} <= cats
    assert sum(1 for r in rows if r["category"] == "set") >= 20  # the v25 gap
    assert sum(1 for r in rows if r["expected_skill"] == "order") >= 10


@pytest.mark.skipif(not (VERIFIED.exists() and SUMMARY.exists()), reason="corpus not generated")
def test_summary_counts_consistent_and_no_true_coverage_gaps():
    rows = _read(VERIFIED)
    s = json.loads(SUMMARY.read_text())
    assert s["n_candidates_verified"] == len(rows)
    assert s["n_zero_lean_success_theorems"] == 0  # every novel theorem has a proof
    assert s["uses_state_after"] is False and s["uses_manual_oracle"] is False


@pytest.mark.skipif(not FAILED.exists(), reason="corpus not generated")
def test_failed_rows_are_not_verified():
    for r in _read(FAILED):
        assert r["verified"] is False
