"""v28 Part 8 — scaling / plateau analysis invariants (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data" / "baselines" / "v28_scaling" / "report.json"

pytestmark = pytest.mark.skipif(not REPORT.exists(), reason="v28 scaling analysis not run")


def test_report_answers_research_questions():
    r = json.loads(REPORT.read_text())
    assert "fresh_holdout_scaling" in r
    assert "set_order_per_category" in r
    assert "balancing_v28_holdout" in r
    assert "finset_transfer" in r
    assert "wall_diagnosis" in r


def test_fresh_holdout_deltas_are_numbers():
    r = json.loads(REPORT.read_text())
    for bench, d in r["fresh_holdout_scaling"].items():
        if d.get("delta_pass@10") is not None:
            assert -1.0 <= d["delta_pass@10"] <= 1.0


def test_wall_diagnosis_classifies_residuals():
    r = json.loads(REPORT.read_text())
    wd = r["wall_diagnosis"]
    assert "n_residuals" in wd
    assert "leandojo_next_state_relevant" in wd
    # residual buckets sum to n_residuals
    assert sum(r["residual_buckets"].values()) == wd["n_residuals"]
