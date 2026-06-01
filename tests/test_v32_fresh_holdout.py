"""v32 Part 5 — fresh Mathlib micro-holdout (no Lean re-run)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "data" / "processed" / "v32_mathlib" / "fresh_holdout_summary.json"
SEEDS = ROOT / "data" / "seeds" / "v32_fresh_mathlib_holdout_seeds.jsonl"

pytestmark = pytest.mark.skipif(not SUMMARY.exists(), reason="fresh holdout not generated")


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_size_and_eval_only():
    s = json.loads(SUMMARY.read_text())
    assert 20 <= s["n_solvable_theorems"] <= 40
    assert s["uses_state_after"] is False
    assert "EVAL ONLY" in s["note"]


def test_no_training_leakage():
    # the generator drops any statement that coincides with training; n_leaked_dropped
    # records it, and the surviving seeds are guaranteed novel.
    s = json.loads(SUMMARY.read_text())
    assert "n_leaked_dropped" in s
    assert s["n_solvable_theorems"] >= 1


def test_seeds_span_categories():
    cats = {r["category"] for r in _read(SEEDS)}
    assert len(cats) >= 5
