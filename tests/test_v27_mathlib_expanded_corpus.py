"""v27 Part 4 — expanded corpus artifact invariants (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIED = ROOT / "data" / "traces" / "v27_mathlib_expanded_verified.jsonl"
FAILED = ROOT / "data" / "traces" / "v27_mathlib_expanded_failed.jsonl"
SUMMARY = ROOT / "data" / "processed" / "v27_mathlib_specialist" / "expanded_summary.json"
INTEGRITY = ROOT / "data" / "baselines" / "v27_corpus_integrity" / "report.json"

pytestmark = pytest.mark.skipif(not VERIFIED.exists(), reason="v27 corpus not generated")


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_verified_rows_metadata_and_no_state_after():
    rows = _read(VERIFIED)
    assert len(rows) >= 150  # 150-300 target
    needed = {"theorem_name", "theorem_statement", "state_before", "tactic", "category",
              "expected_skill", "theorem_family", "proof_head", "uses_simp", "uses_aesop",
              "uses_omega", "uses_set", "uses_order", "mathlib", "source"}
    for r in rows:
        assert needed <= set(r)
        assert r["verified"] is True and r["mathlib"] is True
        assert r["source"] == "v27_mathlib_expanded"
        assert r["imports"] == ["import Mathlib"]
        assert "state_after" not in r
        assert r["theorem_name"].startswith("v27_")


def test_corpus_set_and_order_expanded():
    rows = _read(VERIFIED)
    cats = {r["category"] for r in rows}
    assert {"set", "order", "nat", "list", "logic", "bool_option", "function"} <= cats
    assert sum(1 for r in rows if r["category"] == "set") >= 40   # Set is the gap; heavy
    assert sum(1 for r in rows if r["category"] == "order") >= 20  # new dedicated order block


def test_failed_rows_not_verified():
    for r in _read(FAILED):
        assert r["verified"] is False


def test_summary_no_true_coverage_gaps_and_honesty_flags():
    s = json.loads(SUMMARY.read_text())
    assert s["n_candidates_verified"] == len(_read(VERIFIED))
    assert s["n_zero_lean_success_theorems"] == 0  # every theorem has >=1 Lean-accepted proof
    assert s["uses_state_after"] is False and s["uses_manual_oracle"] is False


@pytest.mark.skipif(not INTEGRITY.exists(), reason="integrity report not generated")
def test_corpus_integrity_sound():
    r = json.loads(INTEGRITY.read_text())
    assert r["integrity_ok"] is True
    assert r["n_verified_regressions"] == 0
    assert r["n_gold_mismatches"] == 0
    assert r["verified_still_pass"] == r["n_verified"]
