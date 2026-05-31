"""Tests for the v23 reranker data audit (Part 1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROWS = ROOT / "data" / "processed" / "v23_reranker_data" / "rows.jsonl"
STATS = ROOT / "data" / "processed" / "v23_reranker_data" / "stats.json"


def _rows():
    if not ROWS.exists():
        pytest.skip("v23 reranker rows absent")
    return [json.loads(l) for l in ROWS.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def test_v23_rows_exist_and_sized():
    rows = _rows()
    assert len(rows) > 1000
    pos = sum(1 for r in rows if r["verified"])
    assert 0 < pos < len(rows)  # both classes present


def test_v23_rows_no_state_after():
    for r in _rows():
        assert "state_after" not in r


def test_v23_rows_required_fields():
    req = {"theorem_name", "category", "candidate", "candidate_source",
           "beam_rank", "verified", "error_class", "source_model"}
    for r in _rows()[:200]:
        assert req <= set(r), f"missing {req - set(r)}"


def test_v23_stats_honesty():
    if not STATS.exists():
        pytest.skip("stats absent")
    s = json.loads(STATS.read_text(encoding="utf-8"))
    assert s["uses_state_after"] is False
    assert s["uses_manual_oracle"] is False
    assert "leave-one-theorem-out" in s["leakage_control"]
    assert s["n_positives"] + s["n_negatives"] == s["n_rows"]


def test_v23_has_broad_core_and_negation():
    rows = _rows()
    cats = {r["category"] for r in rows}
    assert "negation" in cats
    # the v22 plus_exists generator's rows are present (the eval target)
    assert any(r["source_model"] == "v22_plus_exists" for r in rows)
