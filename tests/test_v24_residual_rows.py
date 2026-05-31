"""Tests for the v24 residual row-by-row results (Part 7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JSON = ROOT / "data" / "baselines" / "v24_regression_analysis.json"
MD = ROOT / "docs" / "V24_RESIDUAL_ROW_RESULTS.md"


def _o():
    if not JSON.exists():
        pytest.skip("v24 regression analysis absent")
    return json.loads(JSON.read_text(encoding="utf-8"))


def test_residual_rows_present():
    o = _o()
    assert o["n_residual_total"] == 8
    assert 0 <= o["n_residual_fixed"] <= 8
    for r in o["row_results"]:
        assert r["old_first_verified_rank"] is None  # all were generator-bound
        assert "new_first_verified_rank" in r


def test_fixed_rows_have_verifying_candidate():
    o = _o()
    for r in o["row_results"]:
        if r["new_first_verified_rank"] is not None:
            assert r["verifying_candidate"]  # non-empty verifying tactic


def test_residual_md_written():
    if not JSON.exists():
        pytest.skip("not run")
    assert MD.exists()
    assert "residual row-by-row" in MD.read_text(encoding="utf-8").lower()
