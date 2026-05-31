"""v27 Part 7 — routed system: broad-core preservation (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTED = ROOT / "data" / "baselines" / "v27_routed_system"
COMP = ROUTED / "comparison.json"

pytestmark = pytest.mark.skipif(not COMP.exists(), reason="v27 routed eval not run")


def test_routing_is_complete_and_deterministic():
    d = json.loads(COMP.read_text())
    bc = d["routing"]["broad_to_core"]
    tc = d["routing"]["tierc_to_specialist"]
    # all broad-core -> v24, all tier-C -> specialist
    assert bc.split("/")[0] == bc.split("/")[1]
    assert tc.split("/")[0] == tc.split("/")[1]


def test_broad_core_preserved_no_regression():
    d = json.loads(COMP.read_text())
    p = d["broad_core_preserved"]
    assert p["no_regression"] is True
    # actual values 45/48=0.9375 and 46/48=0.95833 (the "0.938/0.958" targets,
    # exact); preservation = routed >= v24 baseline (the real criterion).
    assert p["routed_pass@5"] >= p["v24_pass@5"] - 1e-9
    assert p["routed_pass@10"] >= p["v24_pass@10"] - 1e-9
    assert p["routed_pass@5"] >= 0.9375 - 1e-9
    assert p["routed_pass@10"] >= 0.9583 - 1e-9


def test_routed_broad_core_matches_v26():
    d = json.loads(COMP.read_text())
    v26 = d.get("vs_v26_routed_broad")
    if v26:  # routed broad-core == v26 routed broad-core (v24 untouched)
        assert abs(d["routed"]["broad_core"]["pass@10"] - v26["v26_pass@10"]) < 1e-6
        assert abs(d["routed"]["broad_core"]["pass@5"] - v26["v26_pass@5"]) < 1e-6


def test_tierc_strong():
    d = json.loads(COMP.read_text())
    assert d["routed"]["tierc"]["pass@10"] >= 0.85


def test_specialist_is_v27():
    d = json.loads(COMP.read_text())
    assert "v27" in d["specialist_model"]
