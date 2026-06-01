"""v29 Part 7 — specialist eval sanity (reads comparison.json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "data" / "baselines" / "v29_specialist_eval" / "comparison.json"

pytestmark = pytest.mark.skipif(not COMP.exists(), reason="v29 specialist eval not run")


def _comp():
    return json.loads(COMP.read_text())


def _cell(results, model, bench):
    return results.get(f"{model}__{bench}")


def test_uses_trusted_verifier():
    assert _comp()["verifier"] == "TrustedMathlibVerifier"


def test_v29_improves_v26_and_v28_holdouts():
    # v29 improves the larger/fresher held-outs (the primary direction).
    res = _comp()["results"]
    v26 = _cell(res, "v29_general", "v26_holdout")
    v28 = _cell(res, "v29_general", "v28_holdout")
    assert v26 and v26["best"]["pass@10"] >= 0.955 - 1e-9, "v26 holdout must be >= 0.955"
    assert v28 and v28["best"]["pass@10"] >= 0.867 + 1e-9, "v28 holdout must improve above 0.867"


def test_v25_regression_is_bounded_and_documented():
    # HONEST contract: v29 trades a small, recoverable v25 micro-benchmark regression
    # (2/14) for the fresh-holdout gains — see V29_SPECIALIST_EVAL_REPORT. It must stay
    # bounded (no collapse), and SOME v29 config must keep v25 reasonably high.
    res = _comp()["results"]
    v25_general = _cell(res, "v29_general", "v25_heldout")
    assert v25_general and v25_general["best"]["pass@10"] >= 0.85 - 1e-9, "v25 must not collapse"
    best_v25 = max(_cell(res, m, "v25_heldout")["best"]["pass@10"]
                   for m in ("v29_general", "v29_function_order", "v29_set_finset_order_heavy")
                   if _cell(res, m, "v25_heldout"))
    assert best_v25 >= 0.9 - 1e-9, "some v29 config should keep v25 >= 0.9"


def test_density_contrast_present_in_eval():
    res = _comp()["results"]
    assert _cell(res, "v29_general", "family_density_holdout") is not None
    assert _cell(res, "v29_general", "low_density_holdout") is not None


def test_per_family_metrics_emitted():
    # at least one cell metrics.json carries per_family
    run = ROOT / "data" / "baselines" / "v29_specialist_eval" / "v29_general__family_density_holdout"
    if not run.exists():
        pytest.skip("cell missing")
    mfs = list(run.glob("*/metrics.json"))
    assert mfs
    assert any("per_family" in json.loads(m.read_text()) for m in mfs)
