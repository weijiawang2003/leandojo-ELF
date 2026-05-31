"""Mini-ELF v25 — tests for the zero-shot tier-C evaluation (Part 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "baselines" / "v25_zero_shot_tierc"
SUMMARY = EVAL / "summary.json"
CONFIGS = ("raw", "abstract", "policy")


def _metrics(cfg: str):
    p = EVAL / cfg / "metrics.json"
    if not p.exists():
        pytest.skip(f"absent: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def test_summary_exists_and_mathlib():
    if not SUMMARY.exists():
        pytest.skip("v25 zero-shot eval not run yet")
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert s["mathlib"] is True
    assert s["imports"] == ["import Mathlib"]
    assert s["model"] == "v24_broad_residual"


def test_metrics_well_formed():
    m = _metrics("raw")
    for k in ("pass@1", "pass@5", "pass@10", "MRR"):
        assert 0.0 <= m[k] <= 1.0
    assert m["pass@1"] <= m["pass@5"] <= m["pass@10"]
    assert m["uses_state_after"] is False
    assert m["uses_manual_oracle"] is False


def test_failure_taxonomy_present():
    m = _metrics("raw")
    assert "failure_taxonomy" in m
    assert "per_transfer" in m
    assert "per_category" in m
    # transfer breakdown must distinguish core vs mathlib
    assert set(m["per_transfer"]) <= {"core", "mathlib", "unknown"}


def test_no_verify_reason_recorded():
    m = _metrics("raw")
    # every no-verify theorem must have a taxonomy reason attached
    assert m["n_no_candidate_verified"] == len(m["no_verify_reason"])
