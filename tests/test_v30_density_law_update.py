"""v30 Part 9 — density law update sanity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "data" / "baselines" / "v30_density_law_update" / "report.json"

pytestmark = pytest.mark.skipif(not REP.exists(), reason="v30 density-law update not run")


def _report():
    return json.loads(REP.read_text())


def test_v25_recovery_reported():
    r = _report()["v25_recovery"]
    assert "v25_pass@10_v30" in r and r["v25_pass@10_v30"] is not None


def test_v28_v29_gains_not_regressed():
    t = _report()["bench_v29_vs_v30"]
    for b in ("v28_holdout", "v29_holdout"):
        d = t.get(b, {})
        if d.get("v30") is not None:
            assert d["v30"] >= 0.9 - 1e-9, f"{b} regressed in v30"


def test_density_law_out_of_sample_recorded():
    o = _report()["density_law_out_of_sample"]
    assert "v25_recovered" in o and "below_threshold_worse" in o


def test_residual_classes_present():
    assert isinstance(_report()["v30_residual_classes"], dict)
