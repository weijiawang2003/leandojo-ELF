"""v30 Part 7 — specialist eval sanity (reads comparison.json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "data" / "baselines" / "v30_specialist_eval" / "comparison.json"

pytestmark = pytest.mark.skipif(not COMP.exists(), reason="v30 specialist eval not run")


def _comp():
    return json.loads(COMP.read_text())


def _cell(res, model, bench):
    return res.get(f"{model}__{bench}")


def test_uses_trusted_verifier():
    assert _comp()["verifier"] == "TrustedMathlibVerifier"


def test_v30_preserves_v28_v29_gains():
    res = _comp()["results"]
    v28 = _cell(res, "v30_general_targeted", "v28_holdout")
    v29 = _cell(res, "v30_general_targeted", "v29_holdout")
    assert v28 and v28["best"]["pass@10"] >= 0.9 - 1e-9, "v28 holdout gain must be preserved"
    assert v29 and v29["best"]["pass@10"] >= 0.9 - 1e-9, "v29 holdout must stay high"


def test_v26_preserved():
    res = _comp()["results"]
    v26 = _cell(res, "v30_general_targeted", "v26_holdout")
    assert v26 and v26["best"]["pass@10"] >= 0.955 - 1e-9


def test_per_family_metrics_emitted():
    run = ROOT / "data" / "baselines" / "v30_specialist_eval" / "v30_general_targeted__v30_targeted_family"
    if not run.exists():
        pytest.skip("cell missing")
    mfs = list(run.glob("*/metrics.json"))
    assert mfs and any("per_family" in json.loads(m.read_text()) for m in mfs)
