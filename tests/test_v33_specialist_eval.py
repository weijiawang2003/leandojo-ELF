"""v33 Part 6 — specialist eval sanity (reads comparison.json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "data" / "baselines" / "v33_specialist_eval" / "comparison.json"

pytestmark = pytest.mark.skipif(not COMP.exists(), reason="v33 specialist eval not run")


def _comp():
    return json.loads(COMP.read_text())


def _cell(res, m, b):
    return res.get(f"{m}__{b}")


def test_uses_trusted_not_placeholders():
    c = _comp()
    assert c["verifier"] == "TrustedMathlibVerifier" and c["not_v19_placeholders"] is True


def test_v33_preserves_standard_holdouts():
    res = _comp()["results"]
    for bench in ("v25_heldout", "v28_holdout", "v29_holdout"):
        c = _cell(res, "v33_general_residual", bench)
        if c:
            assert c["best"]["pass@10"] >= 0.9 - 1e-9, f"{bench} regressed in v33"


def test_v33_not_worse_than_v32_on_stress():
    res = _comp()["results"]
    v32 = _cell(res, "v32_canonical_repaired", "identifier_stress")
    v33 = _cell(res, "v33_general_residual", "identifier_stress")
    if v32 and v33:
        assert v33["best"]["pass@10"] >= v32["best"]["pass@10"] - 1e-9, "v33 should not regress adversarial stress"


def test_residual_only_is_ablation_not_adopted():
    # the residual-only ablation should be clearly weaker on standard holdouts
    res = _comp()["results"]
    ro = _cell(res, "v33_residual_only", "v25_heldout")
    gen = _cell(res, "v33_general_residual", "v25_heldout")
    if ro and gen:
        assert ro["best"]["pass@10"] <= gen["best"]["pass@10"] + 1e-9
