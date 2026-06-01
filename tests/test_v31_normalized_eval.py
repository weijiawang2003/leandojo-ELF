"""v31 Part 6 — normalized specialist eval sanity (reads comparison.json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "data" / "baselines" / "v31_normalized_eval" / "comparison.json"

pytestmark = pytest.mark.skipif(not COMP.exists(), reason="v31 normalized eval not run")


def _comp():
    return json.loads(COMP.read_text())


def _cell(res, model, bench):
    return res.get(f"{model}__{bench}")


def test_uses_trusted_verifier_not_placeholders():
    c = _comp()
    assert c["verifier"] == "TrustedMathlibVerifier"
    assert c["not_v19_placeholders"] is True


def test_some_v31_config_improves_token_diversity():
    res = _comp()["results"]
    base_cell = _cell(res, "v30_general_targeted", "token_diversity")
    if base_cell is None:
        pytest.skip("no v30 baseline cell")
    base = base_cell["best"]["pass@10"]
    best31 = max((v["best"]["pass@10"] for k, v in res.items()
                  if k.startswith("v31_") and k.endswith("__token_diversity")), default=None)
    assert best31 is not None
    assert best31 > base + 1e-9, "a v31 config should IMPROVE token-diversity over v30"


def test_standard_holdouts_not_regressed_by_best_v31():
    # whichever v31 config is adopted must not collapse v25/v26/v29 (raw fallback guards it)
    res = _comp()["results"]
    for bench in ("v25_heldout", "v26_holdout", "v29_holdout"):
        base = _cell(res, "v30_general_targeted", bench)
        aug = _cell(res, "v31_raw_plus_projection_aug", bench)
        if base and aug:
            assert aug["best"]["pass@10"] >= base["best"]["pass@10"] - 0.1, f"{bench} regressed materially"


def test_canonical_pool_stats_show_guard_active():
    # canonical/mixture cells must report the reject-before-verify guard counters
    res = _comp()["results"]
    can = _cell(res, "v31_canonical_general", "token_diversity")
    if can and can.get("pool_stats"):
        ps = can["pool_stats"]
        assert "n_unresolved_rejected" in ps and "n_from_raw_fallback" in ps
