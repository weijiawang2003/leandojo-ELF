"""v29 Part 3 — density corpus structure + honesty (no Lean re-run)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "data" / "processed" / "v29_mathlib_specialist" / "density_summary.json"
VERIFIED = ROOT / "data" / "traces" / "v29_mathlib_density_verified.jsonl"
SEEDS = ROOT / "data" / "seeds" / "v29_mathlib_density_seeds.jsonl"

pytestmark = pytest.mark.skipif(not SUMMARY.exists(), reason="v29 density corpus not generated")


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _summary():
    return json.loads(SUMMARY.read_text())


def test_corpus_has_verified_rows_and_no_gaps():
    s = _summary()
    assert s["n_candidates_verified"] >= 300, "v29 target is 300-700 verified rows"
    assert s["n_candidates_verified"] <= 800
    assert s["n_zero_lean_success_theorems"] == 0, "every theorem must have >=1 verified candidate"


def test_trusted_verifier_only_and_honest():
    s = _summary()
    assert "Trusted" in s["lean_verifier"]
    assert s["uses_state_after"] is False
    assert s["uses_manual_oracle"] is False
    assert s["uses_mathlib"] is True


def test_dense_target_families_present():
    # the residual families must each be densified to several verified siblings
    rows = _read(VERIFIED)
    by_fam = Counter(r["theorem_family"] for r in rows)
    for fam in ("mem_inter_proj", "inter_subset", "subset_union", "comp_assoc", "antisymm"):
        assert by_fam.get(fam, 0) >= 2, f"family {fam} underpopulated: {by_fam.get(fam, 0)}"


def test_every_verified_row_marked_and_typed():
    for r in _read(VERIFIED):
        assert r["verified"] is True
        assert r["category"] and r["theorem_family"]
        assert "state_after" not in r
        assert r["theorem_name"].startswith("v29_")


def test_seeds_align_with_plan():
    seeds = _read(SEEDS)
    assert len({s["theorem_name"] for s in seeds}) == len(seeds)
    assert all(s.get("source") == "v29_mathlib_density" for s in seeds)
