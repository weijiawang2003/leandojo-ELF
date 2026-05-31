"""v26 specialist eval tests: assert the produced comparison meets the v26 goals
(specialist improves tier-C over v24 and v25 co-training; Set reachable)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "baselines" / "v26_specialist_eval"
CMP = EVAL / "comparison.json"

pytestmark = pytest.mark.skipif(not CMP.exists(), reason="specialist eval not run")


def _cmp():
    return json.loads(CMP.read_text())["results"]


def test_specialist_beats_baselines_on_v25_heldout():
    r = _cmp()
    v24 = r["v24__v25_heldout"]["best"]["pass@10"]
    v25 = r["v25_aug__v25_heldout"]["best"]["pass@10"]
    base = r["v26_base__v25_heldout"]["best"]["pass@10"]
    assert base > v25 > v24
    # the explicit v26 target: improve v25 held-out tier-C pass@10 above 0.786
    assert base >= 0.90


def test_specialist_beats_baselines_on_v26_holdout():
    r = _cmp()
    v24 = r["v24__v26_holdout"]["best"]["pass@10"]
    base = r["v26_base__v26_holdout"]["best"]["pass@10"]
    assert base >= 0.85
    assert base > v24 + 0.4  # large margin over zero-shot v24


def test_set_category_reachable_by_specialist():
    """v24 leaves Set at 0; the specialist must reach it (the v25 'unreachable')."""
    m24 = json.loads((EVAL / "v24__v26_holdout" / "abstract" / "metrics.json").read_text())
    mS = json.loads((EVAL / "v26_base__v26_holdout" / "abstract" / "metrics.json").read_text())
    v24_set = m24["per_category"].get("set", {}).get("pass@10", 0.0)
    spec_set = mS["per_category"].get("set", {}).get("pass@10", 0.0)
    assert v24_set == 0.0
    assert spec_set > 0.0


def test_mathlib_transfer_subset_improved():
    mS = json.loads((EVAL / "v26_base__v26_holdout" / "abstract" / "metrics.json").read_text())
    m24 = json.loads((EVAL / "v24__v26_holdout" / "abstract" / "metrics.json").read_text())
    assert mS["per_transfer"]["mathlib"]["pass@10"] > m24["per_transfer"]["mathlib"]["pass@10"]
    assert mS["uses_state_after"] is False and mS["uses_manual_oracle"] is False
