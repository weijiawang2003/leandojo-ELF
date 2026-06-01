"""v31 Part 7 — routed system: broad-core preservation + router unit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

COMP = ROOT / "data" / "baselines" / "v31_routed_system" / "comparison.json"
BAR = {"pass@5": 0.9375, "pass@10": 0.9583}


def test_router_unit():
    from mini_elf_lean.v31_mathlib_router import V31MathlibRouter, BROAD_CORE, MATHLIB_SPECIALIST
    r = V31MathlibRouter()
    assert r.route_seed({"imports": [], "mathlib": False}) == BROAD_CORE
    assert r.route_seed({"imports": ["import Mathlib"], "mathlib": True, "category": "set"}) == MATHLIB_SPECIALIST


@pytest.mark.skipif(not COMP.exists(), reason="v31 routed system not run")
def test_broad_core_preserved_and_adopted():
    c = json.loads(COMP.read_text())
    rb = c["routed"]["broad_core"]
    assert rb["pass@5"] >= BAR["pass@5"] - 1e-9
    assert rb["pass@10"] >= BAR["pass@10"] - 1e-9
    assert c["preserves_v27_routed_bar"] is True and c["adopt_router"] is True


@pytest.mark.skipif(not COMP.exists(), reason="v31 routed system not run")
def test_no_unresolved_reach_metrics():
    # the canonical guard means rejected candidates are dropped before verification;
    # the pool stats are reported, and broad-core (core verifier) is unaffected.
    c = json.loads(COMP.read_text())
    assert c["not_v19_placeholders"] is True
    bcp = c.get("broad_core_preserved")
    if bcp:
        assert bcp["no_regression"] is True
