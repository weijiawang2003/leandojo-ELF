"""Tests for the v24 broad-core evaluation (Part 6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V24 = ROOT / "data" / "baselines" / "v24_broad_residual_eval"
V22 = ROOT / "data" / "baselines" / "v22_general_plus_exists_eval"


def _m(d: Path, cfg: str = "raw"):
    p = d / cfg / "metrics.json"
    if not p.exists():
        pytest.skip(f"absent: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def test_v24_eval_schema():
    m = _m(V24)
    for k in ("pass@1", "pass@5", "pass@10", "MRR", "per_category",
              "n_no_candidate_verified"):
        assert k in m
    assert m.get("uses_state_after") is False
    assert len(m["per_category"]) >= 8


def test_v24_pass10_at_least_v22():
    """The whole v24 thesis: adding verified shapes should raise the
    generator ceiling (pass@10) — or at least not lower it."""
    v24 = _m(V24)
    v22 = _m(V22)
    assert v24["pass@10"] >= v22["pass@10"] - 1e-9


def test_v24_no_verify_not_worse():
    v24 = _m(V24)
    v22 = _m(V22)
    assert v24["n_no_candidate_verified"] <= v22["n_no_candidate_verified"]


def test_v24_pass10_rerank_invariant():
    cfgs = list(V24.glob("*/metrics.json"))
    if len(cfgs) < 2:
        pytest.skip("not enough configs")
    vals = {json.loads(c.read_text(encoding="utf-8"))["pass@10"] for c in cfgs}
    assert len(vals) == 1
