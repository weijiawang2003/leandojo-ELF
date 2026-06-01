"""v32 Part 3/4 — adversarial identifier stress benchmark + eval."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "data" / "processed" / "v32_mathlib" / "identifier_stress_summary.json"
COMP = ROOT / "data" / "baselines" / "v32_identifier_stress_eval" / "comparison.json"


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.mark.skipif(not SUMMARY.exists(), reason="stress benchmark not generated")
def test_benchmark_size_and_provable():
    s = json.loads(SUMMARY.read_text())
    assert 30 <= s["n_theorems"] <= 90
    assert s["n_zero_success_theorems"] == 0, "every benchmark theorem must be provable"
    assert s["uses_state_after"] is False


@pytest.mark.skipif(not COMP.exists(), reason="stress eval not run")
def test_canonical_beats_raw_on_stress():
    res = json.loads(COMP.read_text())["results"]
    def p10(m):
        c = res.get(f"{m}__identifier_stress")
        return c["best"]["pass@10"] if c else None
    raw = p10("v30_general_targeted")
    canon = p10("v31_canonical_general")
    if raw is not None and canon is not None:
        assert canon >= raw - 1e-9, "canonicalization should not do worse than raw on adversarial identifiers"


@pytest.mark.skipif(not COMP.exists(), reason="stress eval not run")
def test_pool_stats_present_and_safe():
    c = json.loads(COMP.read_text())
    assert c["not_v19_placeholders"] is True
    # canonical cells report the reject-before-verify counters
    for k, v in c["results"].items():
        if "canonical" in k and v.get("pool_stats"):
            assert "n_unresolved_rejected" in v["pool_stats"]
