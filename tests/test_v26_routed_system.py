"""v26 routed-system tests: broad-core preserved + tier-C improved + routing correct."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTED = ROOT / "data" / "baselines" / "v26_routed_system"
CMP = ROUTED / "comparison.json"

pytestmark = pytest.mark.skipif(not CMP.exists(), reason="routed eval not run")


def _cmp():
    return json.loads(CMP.read_text())


def test_routing_sends_each_tier_to_the_right_model():
    c = _cmp()
    assert c["routing"]["broad_to_core"].split("/")[0] == c["routing"]["broad_to_core"].split("/")[1]
    assert c["routing"]["tierc_to_specialist"].split("/")[0] == c["routing"]["tierc_to_specialist"].split("/")[1]


def test_broad_core_preserved_no_regression():
    c = _cmp()
    bp = c["broad_core_preserved"]
    assert bp["no_regression"] is True
    # meets the protected bar (p@5 >= 0.917, p@10 >= 0.938)
    assert c["routed"]["broad_core"]["pass@5"] >= 0.917 - 1e-9
    assert c["routed"]["broad_core"]["pass@10"] >= 0.938 - 1e-9


def test_routed_tierc_beats_v25_cotraining_and_v24():
    c = _cmp()
    routed_tierc = c["routed"]["tierc"]["pass@10"]
    assert routed_tierc >= 0.85


def test_routing_log_is_consistent():
    log = [json.loads(l) for l in (ROUTED / "routing_log.jsonl").read_text().splitlines() if l.strip()]
    for r in log:
        if r["tier"] == "broad_core":
            assert r["chosen_model"] == "broad_core"
        if r["tier"] == "tierc":
            assert r["chosen_model"] == "mathlib_specialist"


def test_broadcore_regression_evidence_present():
    """The v25 co-training regression (the reason v26 routes) is recorded."""
    reg = ROOT / "data" / "baselines" / "v25_broadcore_regression" / "raw" / "metrics.json"
    if not reg.exists():
        pytest.skip("v25 regression eval absent")
    m = json.loads(reg.read_text())
    # v25 co-trained broad-core p@10 regressed below the v24 0.938 bar
    assert m["pass@10"] < 0.938
