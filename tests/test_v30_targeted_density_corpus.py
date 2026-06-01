"""v30 Part 3 — targeted density corpus structure + honesty (no Lean re-run)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "data" / "processed" / "v30_mathlib_specialist" / "targeted_summary.json"
VERIFIED = ROOT / "data" / "traces" / "v30_targeted_density_verified.jsonl"

pytestmark = pytest.mark.skipif(not SUMMARY.exists(), reason="v30 targeted corpus not generated")


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _summary():
    return json.loads(SUMMARY.read_text())


def test_targeted_size_bounded_and_no_gaps():
    s = _summary()
    assert 80 <= s["n_candidates_verified"] <= 250, "v30 target is a focused 80-250 verified rows"
    assert s["n_zero_lean_success_theorems"] == 0


def test_trusted_only_and_honest():
    s = _summary()
    assert "Trusted" in s["lean_verifier"]
    assert s["uses_state_after"] is False and s["uses_manual_oracle"] is False


def test_repair_families_densified():
    rows = _read(VERIFIED)
    by_fam = Counter(r["theorem_family"] for r in rows)
    for fam in ("add_assoc", "empty_subset", "le_refl", "mem_inter_proj"):
        assert by_fam.get(fam, 0) >= 3, f"repair family {fam} underpopulated"


def test_density_repair_metadata():
    for r in _read(VERIFIED):
        assert r["density_repair"] is True
        assert r["target_family"] and r["target_density"] == 6
        assert r["theorem_name"].startswith("v30_")
        assert "state_after" not in r
