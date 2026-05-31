"""v27 Part 2 — corrected-metrics audit invariants (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data" / "baselines" / "v27_corrected_metrics" / "report.json"

pytestmark = pytest.mark.skipif(not REPORT.exists(), reason="corrected-metrics audit not run")


def test_corrected_reproduces_established_v26_numbers():
    r = json.loads(REPORT.read_text())
    cells = r["cells"]
    # v26 specialists' established best-config pass@10 must reproduce exactly
    assert abs(cells["v26_base__v25_heldout"]["corrected"]["pass@10"] - 0.929) < 0.02
    assert abs(cells["v26_base__v26_holdout"]["corrected"]["pass@10"] - 0.909) < 0.02
    assert abs(cells["v26_widened__v26_holdout"]["corrected"]["pass@10"] - 0.909) < 0.02


def test_specialists_have_zero_naive_false_positives():
    r = json.loads(REPORT.read_text())
    for cell in ("v26_base__v25_heldout", "v26_base__v26_holdout",
                 "v26_widened__v25_heldout", "v26_widened__v26_holdout"):
        assert r["cells"][cell]["naive_candidate_false_positives"] == 0


def test_naive_would_inflate_a_weak_baseline():
    # the audit's scientific point: naive inflates >=1 weak-model cell
    r = json.loads(REPORT.read_text())
    assert r["summary"]["total_naive_candidate_false_positives"] > 0
    assert any(c["naive_inflates"] for c in r["cells"].values())


def test_honesty_flags():
    r = json.loads(REPORT.read_text())
    assert r["summary"]["uses_state_after"] is False
    assert r["summary"]["uses_manual_oracle"] is False
