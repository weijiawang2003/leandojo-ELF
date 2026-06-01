"""v28 Part 2 — expanded corpus artifact invariants (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIED = ROOT / "data" / "traces" / "v28_mathlib_expanded_verified.jsonl"
FAILED = ROOT / "data" / "traces" / "v28_mathlib_expanded_failed.jsonl"
SUMMARY = ROOT / "data" / "processed" / "v28_mathlib_specialist" / "expanded_summary.json"

pytestmark = pytest.mark.skipif(not VERIFIED.exists(), reason="v28 corpus not generated")


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_verified_rows_metadata_and_no_state_after():
    rows = _read(VERIFIED)
    assert len(rows) >= 250  # 250-500 target
    needed = {"theorem_name", "theorem_statement", "state_before", "tactic", "category",
              "expected_skill", "theorem_family", "proof_head", "uses_simp", "uses_ext",
              "uses_aesop", "uses_omega", "uses_set", "uses_order", "uses_finset",
              "uses_mathlib_lemma", "mathlib", "source"}
    for r in rows:
        assert needed <= set(r)
        assert r["verified"] is True and r["mathlib"] is True
        assert r["source"] == "v28_mathlib_expanded"
        assert r["imports"] == ["import Mathlib"]
        assert "state_after" not in r
        assert r["theorem_name"].startswith("v28_")


def test_corpus_adds_finset_and_keeps_set_order():
    rows = _read(VERIFIED)
    cats = {r["category"] for r in rows}
    assert {"set", "order", "finset", "nat", "list", "logic", "function"} <= cats
    # new Finset category present with nontrivial volume
    assert sum(1 for r in rows if r["category"] == "finset") >= 20
    # set & order still dense
    assert sum(1 for r in rows if r["category"] == "set") >= 80
    assert sum(1 for r in rows if r["category"] == "order") >= 30


def test_residual_families_densified():
    rows = _read(VERIFIED)
    fams = [r["theorem_family"] for r in rows]
    # the v27 residual families now have multiple siblings
    for fam in ("mem_iff", "union_subset", "subset_union", "inter_subset"):
        assert fams.count(fam) >= 4, f"family {fam} not densified"


def test_failed_rows_not_verified():
    for r in _read(FAILED):
        assert r["verified"] is False


def test_summary_no_true_coverage_gaps_and_honesty_flags():
    s = json.loads(SUMMARY.read_text())
    assert s["n_candidates_verified"] == len(_read(VERIFIED))
    assert s["n_zero_lean_success_theorems"] == 0
    assert s["uses_state_after"] is False and s["uses_manual_oracle"] is False
    assert s["uses_mathlib"] is True
    assert "finset" in s["by_category"]
