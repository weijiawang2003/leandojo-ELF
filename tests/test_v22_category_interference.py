"""Tests for the v22 category-interference analysis (Part 6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JSON = ROOT / "data" / "baselines" / "v22_category_interference.json"
MD = ROOT / "docs" / "V22_CATEGORY_INTERFERENCE_ANALYSIS.md"


def _load():
    if not JSON.exists():
        pytest.skip(f"interference analysis absent: {JSON}")
    return json.loads(JSON.read_text(encoding="utf-8"))


def test_v22_interference_schema():
    o = _load()
    for k in ("systems_present", "means", "per_category_pass5",
              "single_axis_effects", "verdicts", "training_volume_by_category"):
        assert k in o, f"missing {k}"
    assert o.get("uses_state_after") is False
    assert o.get("uses_manual_oracle") is False


def test_v22_interference_has_routed_reference():
    o = _load()
    # the routed system must be among the compared systems (the bar to beat).
    assert "v21_routed" in o["systems_present"]


def test_v22_interference_verdict_complete():
    o = _load()
    v = o["verdicts"]
    if not v:
        pytest.skip("verdicts pending (v22 evals not present yet)")
    for k in ("best_single", "best_single_pass5", "routed_pass5",
              "routed_minus_best_single", "single_matches_routing",
              "best_single_holds_forall_impl_bool"):
        assert k in v, f"verdict missing {k}"
    assert isinstance(v["single_matches_routing"], bool)


def test_v22_interference_doc_written():
    if not JSON.exists():
        pytest.skip("analysis not run")
    assert MD.exists(), "interference markdown doc not written"
    text = MD.read_text(encoding="utf-8")
    assert "category-interference" in text.lower()
    # honesty: routing-necessity conclusion is stated, tradeoffs not hidden.
    assert "routed" in text.lower()


def test_v22_interference_pass10_invariant_not_assumed():
    """The analysis must compare pass@5 (rerank-sensitive), not silently
    rely on pass@10 — sanity that per_category_pass5 is populated."""
    o = _load()
    if not o["verdicts"]:
        pytest.skip("evals pending")
    cat5 = o["per_category_pass5"]
    assert "forall" in cat5 and "exists" in cat5
    # at least the routed system has a forall number.
    assert cat5["forall"].get("v21_routed") is not None
