"""v33 Part 8 — final saturation analysis sanity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "data" / "baselines" / "v33_saturation" / "report.json"

pytestmark = pytest.mark.skipif(not REP.exists(), reason="v33 saturation analysis not run")


def _r():
    return json.loads(REP.read_text())


def test_decision_and_breakdown_present():
    r = _r()
    assert "v34_decision" in r and isinstance(r["v34_decision"], str)
    assert "failure_class_counts" in r


def test_leandojo_not_relevant_if_no_multistep():
    r = _r()
    if not r["any_multi_step"]:
        assert r["leandojo_next_state_relevant"] is False


def test_adversarial_stress_improved_over_v31():
    r = _r()["adversarial_stress_v31_to_v33"]
    if r.get("v31") is not None and r.get("v33") is not None:
        assert r["v33"] >= r["v31"] - 1e-9, "v33 should not regress adversarial stress vs v31"
