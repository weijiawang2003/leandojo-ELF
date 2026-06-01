"""v33 Part 2 — residual-coverage corpus (no Lean re-run)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "data" / "processed" / "v33_mathlib_specialist" / "residual_coverage_summary.json"
ROWS = ROOT / "data" / "processed" / "v33_mathlib_specialist" / "residual_coverage_rows.jsonl"

pytestmark = pytest.mark.skipif(not SUMMARY.exists(), reason="v33 residual coverage not generated")


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_size_and_verified():
    s = json.loads(SUMMARY.read_text())
    assert 80 <= s["n_verified"] <= 200
    assert s["n_failed"] == 0
    assert s["uses_state_after"] is False


def test_repair_types_present():
    s = json.loads(SUMMARY.read_text())
    for rt in ("vocabulary", "density", "token_surface"):
        assert s["by_repair_type"].get(rt, 0) > 0


def test_rows_verified_and_typed():
    for r in _read(ROWS):
        assert r["verified"] is True
        assert r["repair_type"] in ("vocabulary", "density", "token_surface")
        assert "state_after" not in r
        assert r["theorem_name"].startswith("v33_")
