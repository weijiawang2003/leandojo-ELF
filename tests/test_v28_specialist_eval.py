"""v28 Part 6 — specialist eval artifact invariants (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "baselines" / "v28_specialist_eval"
COMP = EVAL / "comparison.json"

pytestmark = pytest.mark.skipif(not COMP.exists(), reason="v28 specialist eval not run")


def test_comparison_has_v28_configs_on_all_benches():
    c = json.loads(COMP.read_text())
    res = c["results"]
    assert c["verifier"] == "TrustedMathlibVerifier"
    # at least the general config must be evaluated on every fresh bench
    for bench in ("v25_heldout", "v26_holdout", "v27_holdout", "v28_holdout"):
        assert f"v28_general__{bench}" in res, f"missing v28_general @ {bench}"


def test_metrics_in_unit_range_and_honesty_flags():
    for mf in EVAL.glob("*/*/metrics.json"):
        m = json.loads(mf.read_text())
        for k in ("pass@1", "pass@5", "pass@10", "MRR"):
            assert 0.0 <= m[k] <= 1.0
        assert m["uses_state_after"] is False
        assert m["uses_manual_oracle"] is False
        assert m["mathlib"] is True


def test_v28_holdout_is_a_robust_benchmark():
    c = json.loads(COMP.read_text())
    cell = c["results"]["v28_general__v28_holdout"]
    assert cell["n_test_theorems"] >= 20  # bigger than v27's 7


def test_transfer_cells_present_if_holdout_models_trained():
    c = json.loads(COMP.read_text())
    # transfer bucket exists (may be empty if holdout models absent at eval time)
    assert "transfer" in c
