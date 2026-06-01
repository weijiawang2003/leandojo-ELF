"""v31 Part 4 — projection rename augmentation (no Lean re-run)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROWS = ROOT / "data" / "processed" / "v31_canonical_mathlib" / "projection_rename_aug_rows.jsonl"
SUMMARY = ROOT / "data" / "processed" / "v31_canonical_mathlib" / "projection_rename_aug_summary.json"

pytestmark = pytest.mark.skipif(not ROWS.exists(), reason="v31 rename augmentation not generated")


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_size_focused_and_verified():
    rows = _read(ROWS)
    assert 50 <= len(rows) <= 200, "v31 rename-aug is a focused 50-200 verified rows"
    for r in rows:
        assert r["verified"] is True
        assert r["source"] == "v31_projection_rename_aug"
        assert "state_after" not in r


def test_missing_identifiers_now_covered():
    rows = _read(ROWS)
    by_ident = Counter(r["renamed_identifier"] for r in rows)
    # the v30 residuals needed hw / hm — they must now be in-distribution
    assert by_ident.get("hw", 0) >= 5
    assert by_ident.get("hm", 0) >= 5


def test_projection_families_only():
    rows = _read(ROWS)
    fams = {r["theorem_family"] for r in rows}
    assert fams <= {"mem_inter_proj", "mem_union_intro"}


def test_summary_no_failures_no_drops():
    s = json.loads(SUMMARY.read_text())
    assert s["n_failed"] == 0
    assert s["uses_state_after"] is False and s["uses_manual_oracle"] is False
