"""v32 Part 1 — final-residual audit (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "data" / "baselines" / "v32_final_residual" / "report.json"

pytestmark = pytest.mark.skipif(not REP.exists(), reason="v32 final-residual audit not run")


def _r():
    return json.loads(REP.read_text())


def test_one_residual_and_single_tactic():
    r = _r()
    assert r["n_residuals"] == 1
    res = r["residuals"][0]
    assert res["classification"] == "sparse_shape_single_tactic"
    assert res["single_tactic_probe"]["is_single_tactic"] is True


def test_leandojo_not_justified_by_residual():
    r = _r()
    assert r["is_multi_step"] is False
    assert r["leandojo_justified_by_residual"] is False


def test_honesty():
    assert _r()["uses_state_after"] is False
