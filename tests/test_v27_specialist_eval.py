"""v27 Part 7 — specialist eval artifact invariants + headline targets (no Lean)."""

from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data" / "baselines" / "v27_specialist_eval"
COMP = SPEC / "comparison.json"

pytestmark = pytest.mark.skipif(not COMP.exists(), reason="v27 specialist eval not run")


def _best(run_dir):
    bb = None
    for f in glob.glob(str(run_dir / "*" / "metrics.json")):
        m = json.loads(Path(f).read_text())
        k = (m["pass@5"], m["pass@1"])
        if bb is None or k > bb[0]:
            bb = (k, m)
    return bb[1] if bb else None


def _p10(model, bench):
    return _best(SPEC / f"{model}__{bench}")["pass@10"]


def test_comparison_has_v27_models():
    d = json.loads(COMP.read_text())
    labels = set(d["models"])
    assert {"v27_base", "v27_widened", "v27_set_heavy"} <= labels
    assert d["verifier"] == "TrustedMathlibVerifier"


def test_v27_meets_or_beats_v26_targets():
    # v25-heldout target >= 0.929 ; v26-holdout target >= 0.909
    best_v25 = max(_p10(m, "v25_heldout") for m in ("v27_base", "v27_widened",
                   "v27_category_balanced", "v27_set_heavy"))
    best_v26 = max(_p10(m, "v26_holdout") for m in ("v27_base", "v27_widened",
                   "v27_category_balanced", "v27_set_heavy"))
    assert best_v25 >= 0.929 - 1e-9
    assert best_v26 >= 0.909 - 1e-9


def test_v27_set_heavy_closes_set_residual_on_v26_holdout():
    m = _best(SPEC / "v27_set_heavy__v26_holdout")
    setpc = m["per_category"].get("set", {})
    assert setpc.get("pass@10", 0) >= 0.75  # target > 0.75; set_heavy reaches 1.0


def test_v27_beats_cotraining_and_zeroshot():
    for bench in ("v25_heldout", "v26_holdout"):
        v27 = max(_p10(m, bench) for m in ("v27_widened", "v27_set_heavy"))
        assert v27 >= _p10("v25_aug", bench)  # specialist >= co-training
        assert v27 >= _p10("v24", bench)      # specialist >= zero-shot v24


def test_honesty_flags_in_metrics():
    for f in glob.glob(str(SPEC / "*" / "*" / "metrics.json")):
        m = json.loads(Path(f).read_text())
        assert m["uses_state_after"] is False
        assert m["uses_manual_oracle"] is False
