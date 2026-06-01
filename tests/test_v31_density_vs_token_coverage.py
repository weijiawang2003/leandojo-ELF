"""v31 Part 8 — density vs token-coverage analysis sanity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "data" / "baselines" / "v31_density_vs_token_coverage" / "report.json"

pytestmark = pytest.mark.skipif(not REP.exists(), reason="v31 density-vs-token analysis not run")


def _report():
    return json.loads(REP.read_text())


def test_token_coverage_result_present():
    r = _report()["token_coverage_result"]
    assert "v30_baseline" in r and ("canonical_A" in r or "rename_aug_B" in r)


def test_at_least_one_approach_improves_token_diversity():
    v = _report()["verdict"]
    assert v["canonical_improves"] or v["augmentation_improves"], \
        "expected at least one normalization/augmentation approach to lift token-diversity"


def test_second_axis_documented():
    assert "TOKEN-COVERAGE" in _report()["density_law_second_axis"]


def test_standard_floor_recorded():
    assert isinstance(_report()["standard_holdout_floor"], dict)
