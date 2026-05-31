"""Tests for the v23 reranker eval + hybrid policy (Parts 4/7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "data" / "baselines" / "v23_rerank_eval" / "metrics.json"
PER_THM = ROOT / "data" / "baselines" / "v23_rerank_eval" / "per_theorem.jsonl"


def _m():
    if not METRICS.exists():
        pytest.skip("v23 rerank eval absent")
    return json.loads(METRICS.read_text(encoding="utf-8"))


def test_v23_eval_schema():
    m = _m()
    assert m["uses_state_after"] is False
    assert "leave-one-theorem-out" in m["leakage_control"]
    for r in ("raw", "v23_plain", "v23_category", "v23_hybrid"):
        assert r in m["computed_rankers"]
        for k in ("pass@1", "pass@5", "pass@10", "MRR", "per_category"):
            assert k in m["computed_rankers"][r]


def test_v23_pass10_matches_raw_generator_ceiling():
    """Reranking cannot change which candidates exist, so pass@10 is
    identical across every ranker (the generator ceiling)."""
    m = _m()
    p10 = {r: m["computed_rankers"][r]["pass@10"] for r in m["computed_rankers"]}
    assert len(set(round(v, 6) for v in p10.values())) == 1


def test_v23_hybrid_does_not_regress_raw_pass5():
    """The hybrid policy must not drop below raw on pass@5 (it defaults to
    raw on near-ties) — the 'do not demote verified candidates' guarantee."""
    m = _m()
    raw = m["computed_rankers"]["raw"]["pass@5"]
    hyb = m["computed_rankers"]["v23_hybrid"]["pass@5"]
    assert hyb >= raw - 1e-9


def test_v23_negation_not_below_raw_for_best_ranker():
    """The whole point: the refreshed reranker keeps negation at least at
    raw's level (raw=0.800), unlike the v22 abstract reranker (0.600)."""
    m = _m()
    raw_neg = m["computed_rankers"]["raw"]["per_category"]["negation"]["pass@5"]
    hyb_neg = m["computed_rankers"]["v23_hybrid"]["per_category"]["negation"]["pass@5"]
    assert hyb_neg >= raw_neg - 1e-9


def test_v23_demotion_promotion_present():
    m = _m()
    for k in ("v23_plain", "v23_category", "v23_hybrid"):
        dp = m["demotion_promotion_vs_raw"][k]
        for f in ("demotion@5", "promotion@5", "demotion@1", "promotion@1"):
            assert f in dp


def test_v23_per_theorem_dump():
    if not PER_THM.exists():
        pytest.skip("per-theorem dump absent")
    rows = [json.loads(l) for l in PER_THM.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    assert len(rows) == 48
    assert all("raw_first_verified_rank" in r for r in rows)
