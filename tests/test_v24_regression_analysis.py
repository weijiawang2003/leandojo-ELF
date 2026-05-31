"""Tests for the v24 regression analysis (Part 8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JSON = ROOT / "data" / "baselines" / "v24_regression_analysis.json"
MD = ROOT / "docs" / "V24_REGRESSION_ANALYSIS.md"


def _o():
    if not JSON.exists():
        pytest.skip("v24 regression analysis absent")
    return json.loads(JSON.read_text(encoding="utf-8"))


def test_schema():
    o = _o()
    for k in ("per_category", "regressions", "protected_held", "v24_mean",
              "v22_mean"):
        assert k in o
    assert o["uses_state_after"] is False


def test_per_category_complete():
    o = _o()
    for c in ("forall", "implication", "bool", "negation", "exists",
              "disjunction", "nat_succ", "list", "conjunction",
              "equality_rewrite"):
        assert c in o["per_category"]
        assert "delta" in o["per_category"][c]


def test_protected_categories_reported():
    o = _o()
    # protected_held is a bool; regressions is a list — both must be present.
    assert isinstance(o["protected_held"], bool)
    assert isinstance(o["regressions"], list)


def test_regression_md_written():
    if not JSON.exists():
        pytest.skip("not run")
    assert MD.exists()
    assert "regression" in MD.read_text(encoding="utf-8").lower()
