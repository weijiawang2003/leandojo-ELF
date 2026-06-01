"""v33 Part 3 — fresh robustness holdout (no Lean re-run)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "data" / "processed" / "v33_mathlib_specialist" / "fresh_robustness_summary.json"
SEEDS = ROOT / "data" / "seeds" / "v33_fresh_robustness_holdout_seeds.jsonl"

pytestmark = pytest.mark.skipif(not SUMMARY.exists(), reason="v33 fresh robustness not generated")


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_size_and_eval_only():
    s = json.loads(SUMMARY.read_text())
    assert 30 <= s["n_solvable"] <= 60
    assert s["n_zero_success"] == 0
    assert "EVAL ONLY" in s["note"]
    assert s["uses_state_after"] is False


def test_spans_categories():
    cats = {r["category"] for r in _read(SEEDS)}
    assert len(cats) >= 6
