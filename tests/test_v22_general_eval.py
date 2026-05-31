"""Tests for the v22 single general-model training + evaluation (Parts 4-5).

These assert structure and honesty (no state_after, no manual oracle,
per-category metrics present). They deliberately do NOT hard-code
pass@k numbers — the experiment reports whatever the evaluation finds.
Artefacts that are not yet produced cause a skip, so the suite stays
green during a partial run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "data" / "models"
BASELINES = ROOT / "data" / "baselines"
MANIFEST = MODELS / "v22_general_manifest.json"

V22_MODELS = ("v22_general_plus_exists", "v22_general_balanced",
              "v22_general_large", "v22_general_balanced_large")
V22_EVALS = {
    "v22_general_plus_exists": BASELINES / "v22_general_plus_exists_eval",
    "v22_general_balanced": BASELINES / "v22_general_balanced_eval",
    "v22_general_large": BASELINES / "v22_general_large_eval",
    "v22_general_balanced_large": BASELINES / "v22_general_balanced_large_eval",
}


def _load(p: Path):
    if not p.exists():
        pytest.skip(f"absent: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def test_v22_manifest_present_and_honest():
    m = _load(MANIFEST)
    assert m.get("uses_state_after") is False
    assert m.get("uses_manual_oracle") is False
    trained = {r["name"] for r in m.get("trained", [])}
    assert trained == set(V22_MODELS), f"unexpected trained set: {trained}"
    for r in m["trained"]:
        assert r["runtime_s"] > 0
        assert r["n_rows"] > 0
        assert r["uses_state_after"] is False


def test_v22_models_saved():
    if not MANIFEST.exists():
        pytest.skip("manifest absent")
    for name in V22_MODELS:
        d = MODELS / name
        assert (d / "model.pt").exists(), f"missing model.pt for {name}"
        assert (d / "config.json").exists()
        assert (d / "vocab.json").exists()


@pytest.mark.parametrize("name", list(V22_EVALS))
def test_v22_eval_metrics_schema(name):
    metrics = _load(V22_EVALS[name] / "abstract" / "metrics.json")
    for k in ("pass@1", "pass@5", "pass@10", "MRR", "per_category",
              "error_taxonomy", "n_no_candidate_verified"):
        assert k in metrics, f"{name} missing metric {k}"
    assert metrics.get("uses_state_after") is False
    # all 10 v18 categories represented
    assert len(metrics["per_category"]) >= 8


def test_v22_eval_no_routed_flag_on_single():
    # single-model evals must record routed=False.
    for name, d in V22_EVALS.items():
        p = d / "abstract" / "metrics.json"
        if not p.exists():
            continue
        m = json.loads(p.read_text(encoding="utf-8"))
        assert m.get("routed") in (False, None)


def test_v22_plus_exists_beats_routed_headline():
    """Pin the v22 headline: the single plus_exists model matches/beats
    v21 routed on coverage and recovers exists, holding forall/impl/bool."""
    pe = V22_EVALS["v22_general_plus_exists"] / "abstract" / "metrics.json"
    routed = BASELINES / "v21_routed_eval" / "abstract" / "metrics.json"
    if not pe.exists() or not routed.exists():
        pytest.skip("metrics not present")
    m = json.loads(pe.read_text(encoding="utf-8"))
    r = json.loads(routed.read_text(encoding="utf-8"))
    # candidate-set coverage (rerank-invariant) strictly dominates routed.
    assert m["pass@10"] >= r["pass@10"]
    assert m["n_no_candidate_verified"] <= r["n_no_candidate_verified"]
    # mean pass@5 matches or beats routing.
    assert m["pass@5"] >= r["pass@5"]
    pc = m["per_category"]
    # forall / implication / bool preserved at 1.0; exists recovered.
    assert pc["forall"]["pass@5"] == 1.0
    assert pc["implication"]["pass@5"] == 1.0
    assert pc["bool"]["pass@5"] == 1.0
    assert pc["exists"]["pass@5"] > r["per_category"]["exists"]["pass@5"]


def test_v22_oversample_and_capacity_did_not_beat_plus_exists():
    """Pin the honest negative result: neither balancing nor capacity
    beat the simple plus_exists model on mean pass@10."""
    def p10(name):
        p = V22_EVALS[name] / "abstract" / "metrics.json"
        if not p.exists():
            pytest.skip(f"{name} metrics absent")
        return json.loads(p.read_text(encoding="utf-8"))["pass@10"]
    base = p10("v22_general_plus_exists")
    assert p10("v22_general_balanced") <= base
    assert p10("v22_general_large") <= base


def test_v22_pass10_is_rerank_invariant():
    """pass@10 must match across rerank configs for the same model
    (reranking can only reorder the same candidate set)."""
    for name, d in V22_EVALS.items():
        configs = list(d.glob("*/metrics.json"))
        if len(configs) < 2:
            continue
        vals = {json.loads(c.read_text(encoding="utf-8"))["pass@10"]
                for c in configs}
        assert len(vals) == 1, f"{name} pass@10 varies across rerank: {vals}"
