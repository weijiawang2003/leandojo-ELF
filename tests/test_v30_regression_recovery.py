"""v30 Part 9 — v25 micro-regression recovery (the headline v30 deliverable)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "data" / "baselines" / "v30_specialist_eval" / "comparison.json"

pytestmark = pytest.mark.skipif(not COMP.exists(), reason="v30 specialist eval not run")


def _comp():
    return json.loads(COMP.read_text())


def test_v25_not_below_v29():
    # v30 must not make the v25 regression worse than v29 (0.857).
    res = _comp()["results"]
    c = res.get("v30_general_targeted__v25_heldout")
    assert c and c["best"]["pass@10"] >= 0.857 - 1e-9


def test_recovery_targets_tracked():
    rec = _comp().get("recovery", {})
    assert "v30_general_targeted" in rec, "v25 recovery must be tracked for the v30 model"
    tgt = rec["v30_general_targeted"]
    assert set(tgt) >= {"v25_nat_add_assoc", "v25_set_empty_subset"}


def test_targeted_repair_recovers_at_least_one():
    # the focused repair should recover at least one of the two regressed theorems
    # (full 1.000 recovery is the goal; >=1 proves the mechanism works).
    rec = _comp().get("recovery", {}).get("v30_general_targeted", {})
    assert sum(1 for v in rec.values() if v) >= 1, "expected >=1 v25 theorem recovered by targeted repair"
