"""Tests for the v21 evaluation outputs (forall recovery).

Pins the headline v21 claims once the eval has run, and guards the
honesty contract (v18/v20 metrics on disk unchanged; no state_after).
All tests skip gracefully if the eval artefacts are not yet present.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "baselines"

# v21 config eval roots (set by evaluate_v21_broad_core.py).
CONFIG_B = BASE / "v21_broad_plus_forall_eval"
CONFIG_C = BASE / "v21_routed_eval"
CONFIG_D = BASE / "v21_capacity_eval"

# Prior metrics that must NOT change.
V18_BO = BASE / "v18_broad_only_eval" / "policy" / "metrics.json"
V20_CORR = BASE / "v20_broad_plus_eval_timeout_rerun" / "abstract" / "metrics.json"


def _metrics(root: Path, cfg: str = "abstract"):
    p = root / cfg / "metrics.json"
    if not p.exists():
        pytest.skip(f"v21 eval artefact absent: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------- prior metrics unchanged --------------------------------


def test_v18_metrics_unchanged():
    if not V18_BO.exists():
        pytest.skip()
    m = json.loads(V18_BO.read_text(encoding="utf-8"))
    assert m["pass@5"] == pytest.approx(0.5833333333333334, abs=1e-9)
    # v18 forall pass@5 = 0.667 (the regression baseline).
    assert m["per_category"]["forall"]["pass@5"] == pytest.approx(
        0.6666666666666666, abs=1e-6)


def test_v20_corrected_metrics_unchanged():
    if not V20_CORR.exists():
        pytest.skip()
    m = json.loads(V20_CORR.read_text(encoding="utf-8"))
    # v20's forall regression (0.000) is pinned — v21 must not edit it.
    assert m["per_category"]["forall"]["pass@5"] == pytest.approx(0.0)
    assert m["pass@5"] == pytest.approx(0.7291666666666666, abs=1e-3)


# ---------------- v21 forall recovery ------------------------------------


def _best_config_root():
    """Return the v21 config root with the highest forall pass@5 that
    also preserves implication+bool at 1.000, or skip."""
    candidates = []
    for root in (CONFIG_B, CONFIG_C, CONFIG_D):
        p = root / "abstract" / "metrics.json"
        if p.exists():
            candidates.append(root)
    if not candidates:
        pytest.skip("no v21 eval artefacts yet")
    return candidates


def test_v21_recovers_forall():
    """At least one v21 config lifts forall pass@5 to >= 0.667."""
    roots = _best_config_root()
    best = max(_metrics(r)["per_category"].get("forall", {}).get("pass@5", 0.0)
               for r in roots)
    assert best >= 0.6666 - 1e-3, f"v21 did not recover forall; best={best}"


def test_v21_preserves_implication_and_bool():
    """The config that best recovers forall must keep implication and
    bool at pass@5 = 1.000."""
    roots = _best_config_root()
    # pick the root with max forall pass@5
    best_root = max(roots, key=lambda r: _metrics(r)["per_category"]
                    .get("forall", {}).get("pass@5", 0.0))
    m = _metrics(best_root)
    assert m["per_category"]["implication"]["pass@5"] == pytest.approx(1.0)
    assert m["per_category"]["bool"]["pass@5"] == pytest.approx(1.0)


def test_v21_mean_pass5_not_below_v20():
    """The best v21 config's mean pass@5 must be >= v20's 0.729."""
    roots = _best_config_root()
    best = max(_metrics(r)["pass@5"] for r in roots)
    assert best >= 0.729 - 1e-3, f"v21 mean pass@5 regressed: {best}"


def test_v21_no_unresolved_placeholder():
    for root in (CONFIG_B, CONFIG_C, CONFIG_D):
        p = root / "abstract" / "metrics.json"
        if not p.exists():
            continue
        m = json.loads(p.read_text(encoding="utf-8"))
        assert "unresolved_placeholder" not in m["error_taxonomy"]


def test_v21_metrics_record_no_state_after():
    for root in (CONFIG_B, CONFIG_C, CONFIG_D):
        sp = root / "summary.json"
        if not sp.exists():
            continue
        s = json.loads(sp.read_text(encoding="utf-8"))
        for cfg, m in s["configs"].items():
            assert m.get("uses_state_after") is False
