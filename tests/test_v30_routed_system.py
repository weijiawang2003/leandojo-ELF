"""v30 Part 8 — routed system: broad-core preservation + router unit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

COMP = ROOT / "data" / "baselines" / "v30_routed_system" / "comparison.json"
BAR = {"pass@5": 0.9375, "pass@10": 0.9583}


def test_router_unit():
    from mini_elf_lean.v30_mathlib_router import V30MathlibRouter, BROAD_CORE, MATHLIB_SPECIALIST
    r = V30MathlibRouter()
    assert r.route_seed({"imports": [], "mathlib": False}) == BROAD_CORE
    assert r.route_seed({"imports": ["import Mathlib"], "mathlib": True, "category": "finset"}) == MATHLIB_SPECIALIST


@pytest.mark.skipif(not COMP.exists(), reason="v30 routed system not run")
def test_broad_core_preserved_and_adopted():
    c = json.loads(COMP.read_text())
    rb = c["routed"]["broad_core"]
    assert rb["pass@5"] >= BAR["pass@5"] - 1e-9
    assert rb["pass@10"] >= BAR["pass@10"] - 1e-9
    assert c["preserves_v27_routed_bar"] is True and c["adopt_router"] is True


@pytest.mark.skipif(not COMP.exists(), reason="v30 routed system not run")
def test_no_broad_core_regression_vs_v24():
    c = json.loads(COMP.read_text())
    bcp = c.get("broad_core_preserved")
    if bcp:
        assert bcp["no_regression"] is True
