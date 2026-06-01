"""v32 Part 7 — saturation analysis sanity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "data" / "baselines" / "v32_saturation" / "report.json"

pytestmark = pytest.mark.skipif(not REP.exists(), reason="v32 saturation analysis not run")


def _r():
    return json.loads(REP.read_text())


def test_has_decision_and_failure_breakdown():
    r = _r()
    assert "v33_decision" in r and isinstance(r["v33_decision"], str)
    assert "failure_class_counts" in r


def test_leandojo_relevance_consistent():
    r = _r()
    # if there are no multi-step residuals, LeanDojo must be judged not-relevant
    if r["failure_class_counts"].get("multi_step", 0) == 0:
        assert r["leandojo_next_state_relevant"] is False


def test_stress_fresh_recorded():
    assert isinstance(_r()["stress_fresh_pass10"], dict)
