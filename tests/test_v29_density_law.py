"""v29 Part 9 — density law analysis sanity (reads the density-law report)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "data" / "baselines" / "v29_density_law" / "report.json"

pytestmark = pytest.mark.skipif(not REP.exists(), reason="v29 density-law analysis not run")


def _report():
    return json.loads(REP.read_text())


def test_clean_density_effect_same_hard_families():
    # The honest, un-confounded density law: the SAME hard lemma-binding families at
    # density ~6 must beat the same families at density 0 (whole-category transfer).
    # (The raw family_density-vs-low_density contrast is confounded — low_density
    # families close by a universal tactic at any density — see V29_DENSITY_LAW_ANALYSIS.)
    e = _report()["clean_density_effect_hard_families"]
    dense = e["density_~6_family_density_holdout"]["pass@10"]
    set0 = e["density_0_set_transfer"]["pass@10"]
    fin0 = e["density_0_finset_transfer"]["pass@10"]
    assert dense is not None and set0 is not None and fin0 is not None
    assert dense >= set0 + 0.1, f"density~6 ({dense}) must beat density-0 set transfer ({set0})"
    assert dense >= fin0 + 0.1, f"density~6 ({dense}) must beat density-0 finset transfer ({fin0})"


def test_corpus_effective_density_law_monotone():
    law = _report().get("corpus_effective_density_law") or {}
    seq = [law[b]["pass@10"] for b in ("0", "1-3", "4-6")
           if law.get(b, {}).get("pass@10") is not None]
    assert seq and all(b >= a - 1e-9 for a, b in zip(seq, seq[1:])), f"law not monotone: {seq}"


def test_whole_category_transfer_recorded():
    t = _report()["whole_category_transfer"]
    assert set(t) >= {"set", "finset", "order"}


def test_balancing_not_better_than_general():
    # negative control: balanced must not beat general on the fresh v29 holdout
    b = _report()["balancing_negative_control"].get("v29_holdout", {})
    if b.get("general") is not None and b.get("balanced") is not None:
        assert b["balanced"] <= b["general"] + 1e-9, "balancing should not help (v27/v28 showed harmful)"


def test_wall_diagnosis_present():
    w = _report()["wall_diagnosis"]
    assert "leandojo_next_state_relevant" in w
    assert isinstance(w["note"], str)
