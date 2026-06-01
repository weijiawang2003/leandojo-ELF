"""v28 Part 7 — routed system / broad-core preservation invariants (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTED = ROOT / "data" / "baselines" / "v28_routed_system"
COMP = ROUTED / "comparison.json"

V27_BAR = {"pass@5": 0.9375, "pass@10": 0.9583}

pytestmark = pytest.mark.skipif(not COMP.exists(), reason="v28 routed system eval not run")


def test_router_keys_and_routing_recorded():
    c = json.loads(COMP.read_text())
    assert "V28MathlibRouter" in c["router"]
    assert "broad_to_core" in c["routing"]
    assert "tierc_to_specialist" in c["routing"]


def test_broad_core_preserves_v27_routed_bar():
    c = json.loads(COMP.read_text())
    bc = c["routed"]["broad_core"]
    assert bc["pass@5"] >= V27_BAR["pass@5"] - 1e-9
    assert bc["pass@10"] >= V27_BAR["pass@10"] - 1e-9
    assert c["preserves_v27_routed_bar"] is True
    assert c["adopt_router"] is True


def test_broad_core_no_regression_vs_v24():
    c = json.loads(COMP.read_text())
    if "broad_core_preserved" in c:
        assert c["broad_core_preserved"]["no_regression"] is True


def test_routing_log_all_broad_to_v24():
    # every broad-core seed must route to the untouched v24 model
    for line in (ROUTED / "routing_log.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("tier") == "broad_core":
            assert r["chosen_model"] == "broad_core"
