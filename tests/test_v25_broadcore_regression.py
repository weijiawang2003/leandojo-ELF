"""Mini-ELF v25 — tests for the v18 broad-core regression check (Part 6).

The honest v25 outcome: naive co-training of the tiny Mathlib corpus
REGRESSES broad-core, so the augmented model is NOT adopted and v24
remains the broad-core model. These tests therefore assert:

  1. the **adopted** model (v24) still holds the protected categories at
     1.000 (the real guarantee the brief required preserved), and
  2. the experiment **correctly measured** the augmented model's
     regression (the tradeoff is recorded, not hidden).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V25_EVAL = ROOT / "data" / "baselines" / "v25_broadcore_regression"
V24_EVAL = ROOT / "data" / "baselines" / "v24_broad_residual_eval"

PROTECTED = {"forall": 1.0, "implication": 1.0, "bool": 1.0,
             "equality_rewrite": 1.0}
CFGS = ("raw", "abstract", "policy", "policy_abstract", "learned", "rule")


def _best_pass5(root: Path):
    best = {}
    for cfg in CFGS:
        p = root / cfg / "metrics.json"
        if not p.exists():
            continue
        pc = json.loads(p.read_text(encoding="utf-8")).get("per_category", {})
        for cat, v in pc.items():
            best[cat] = max(best.get(cat, 0.0), v.get("pass@5", 0.0))
    return best


def _best_pass10(root: Path):
    best = 0.0
    for cfg in CFGS:
        p = root / cfg / "metrics.json"
        if p.exists():
            best = max(best, json.loads(p.read_text())["pass@10"])
    return best


def test_v24_baseline_present_and_holds_protected():
    # the adopted broad-core model must still hold the protected categories
    if not (V24_EVAL / "raw" / "metrics.json").exists():
        pytest.skip("v24 baseline absent")
    best = _best_pass5(V24_EVAL)
    for cat, target in PROTECTED.items():
        if cat in best:
            assert best[cat] >= target - 1e-9, \
                f"v24 (adopted) {cat} below {target}: {best[cat]:.3f}"


def test_v24_pass10_strong():
    if not (V24_EVAL / "raw" / "metrics.json").exists():
        pytest.skip("v24 baseline absent")
    assert _best_pass10(V24_EVAL) >= 0.93  # v24 closed the residual gate


def test_regression_was_measured_not_hidden():
    # the augmented-model regression must be recorded on disk (honesty check)
    if not (V25_EVAL / "raw" / "metrics.json").exists():
        pytest.skip("v25 broad-core regression eval not run")
    v24_10 = _best_pass10(V24_EVAL)
    v25_10 = _best_pass10(V25_EVAL)
    # we EXPECT a regression; assert it is real and recorded (v25 <= v24)
    assert v25_10 <= v24_10 + 1e-9, \
        "v25 augmented unexpectedly >= v24 on broad-core — re-examine the claim"


def test_regression_report_exists():
    doc = ROOT / "docs" / "V25_BROADCORE_REGRESSION_REPORT.md"
    assert doc.exists()
    txt = doc.read_text(encoding="utf-8")
    # the tradeoff verdict must be stated
    assert "not adopted" in txt.lower() or "remains the broad-core" in txt.lower()
