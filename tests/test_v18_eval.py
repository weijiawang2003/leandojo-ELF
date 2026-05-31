"""Pin the v18 transfer headline numbers.

The v18 brief explicitly asks for an *honest* answer: if v17
collapses, report it. So this module pins the documented v18
metrics — both the v17-panel zero-shot and the broad-synthetic
zero-shot — and the structural invariants (no v12-v17 overwrite,
no state_after, ceiling preserved, etc).

Pins were derived from the v18 docs:
  * `data/baselines/v18_zero_shot_v17_pipeline/policy/metrics.json`
  * `data/baselines/v18_broad_only_eval/policy/metrics.json`
  * `data/baselines/v18_broad_synthetic_eval/policy/metrics.json`
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]

V17_POL = ROOT / "data" / "baselines" / "v17_policy_eval"
V18_PANEL = ROOT / "data" / "baselines" / "v18_zero_shot_v17_pipeline"
V18_BROAD_ONLY = ROOT / "data" / "baselines" / "v18_broad_only_eval"


def _load(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# --------------- v17 metrics on disk are NOT touched by v18 -------------


def test_v18_does_not_overwrite_v17_neg_exfalso_policy_pass5() -> None:
    md = _load(V17_POL / "neg_exfalso" / "policy" / "metrics.json")
    if md is None:
        pytest.skip("v17 policy absent")
    # v17 closed neg_exfalso at 1.000 — this is the cornerstone of
    # v17's "templated benchmark closed" claim.
    assert md["pass@5"] == pytest.approx(1.000, abs=1e-3)


# --------------- v18 panel pinned headline values -----------------------


V18_PANEL_PINS = [
    ("raw", "pass@1", 16 / 48),         # 0.333
    ("raw", "pass@5", 22 / 48),         # 0.458
    ("raw", "pass@10", 26 / 48),        # 0.542
    ("rule", "pass@5", 24 / 48),        # 0.500
    ("rule", "pass@10", 28 / 48),       # 0.583
    ("learned", "pass@1", 14 / 48),     # 0.292
    ("policy", "pass@1", 14 / 48),      # 0.292
    ("policy", "pass@5", 24 / 48),      # 0.500
    ("policy", "pass@10", 28 / 48),     # 0.583
]


@pytest.mark.parametrize("cfg,key,expected", V18_PANEL_PINS,
                         ids=lambda x: str(x))
def test_v18_panel_pinned(cfg: str, key: str, expected: float) -> None:
    md = _load(V18_PANEL / cfg / "metrics.json")
    if md is None:
        pytest.skip(f"v18 panel {cfg} metrics absent")
    assert md[key] == pytest.approx(expected, abs=1e-3), (
        f"v18 panel {cfg} {key} = {md[key]} (expected {expected:.3f})")


# --------------- v18 broad-synthetic-only pinned values -----------------


V18_BROAD_PINS = [
    ("policy", "pass@1", 24 / 48),   # 0.500
    ("policy", "pass@5", 28 / 48),   # 0.583
    ("policy", "pass@10", 29 / 48),  # 0.604
    ("rule", "pass@1", 25 / 48),     # 0.521
    ("rule", "pass@5", 28 / 48),     # 0.583
    ("rule", "pass@10", 29 / 48),    # 0.604
]


@pytest.mark.parametrize("cfg,key,expected", V18_BROAD_PINS,
                         ids=lambda x: str(x))
def test_v18_broad_only_pinned(cfg: str, key: str, expected: float) -> None:
    md = _load(V18_BROAD_ONLY / cfg / "metrics.json")
    if md is None:
        pytest.skip(f"v18 broad-only {cfg} metrics absent")
    assert md[key] == pytest.approx(expected, abs=1e-3), (
        f"v18 broad-only {cfg} {key} = {md[key]} (expected {expected:.3f})")


# --------------- broad-only outperforms panel ---------------------------


def test_broad_only_beats_panel_on_pass_at_1() -> None:
    p = _load(V18_PANEL / "policy" / "metrics.json")
    b = _load(V18_BROAD_ONLY / "policy" / "metrics.json")
    if p is None or b is None:
        pytest.skip("v18 metrics absent")
    assert b["pass@1"] > p["pass@1"], (
        f"v18 broad-only pass@1 ({b['pass@1']}) should beat panel "
        f"({p['pass@1']}) — that was the headline scaling finding")


def test_broad_only_beats_or_matches_panel_on_pass_at_5() -> None:
    p = _load(V18_PANEL / "policy" / "metrics.json")
    b = _load(V18_BROAD_ONLY / "policy" / "metrics.json")
    if p is None or b is None:
        pytest.skip("v18 metrics absent")
    assert b["pass@5"] >= p["pass@5"]


def test_broad_only_beats_or_matches_panel_on_pass_at_10() -> None:
    p = _load(V18_PANEL / "policy" / "metrics.json")
    b = _load(V18_BROAD_ONLY / "policy" / "metrics.json")
    if p is None or b is None:
        pytest.skip("v18 metrics absent")
    assert b["pass@10"] >= p["pass@10"]


# --------------- per-category categorical wall --------------------------


def test_implication_is_total_miss_under_panel() -> None:
    md = _load(V18_PANEL / "policy" / "metrics.json")
    if md is None:
        pytest.skip("v18 panel absent")
    assert md["per_category"]["implication"]["pass@5"] == 0.0, (
        "implication pass@5 must be 0.000 under v17 panel — that's "
        "the v18 wall finding")


def test_bool_is_total_miss_in_both_configs() -> None:
    for root in (V18_PANEL, V18_BROAD_ONLY):
        md = _load(root / "policy" / "metrics.json")
        if md is None:
            continue
        assert md["per_category"]["bool"]["pass@10"] == 0.0, (
            "bool must be 0.000 across all k under both configs")


def test_equality_rewrite_transfers_cleanly() -> None:
    for root in (V18_PANEL, V18_BROAD_ONLY):
        md = _load(root / "policy" / "metrics.json")
        if md is None:
            continue
        assert md["per_category"]["equality_rewrite"]["pass@5"] == \
            pytest.approx(1.000, abs=1e-3), (
                "equality_rewrite must be 1.000 — that's the v18 finding "
                "that v17's rewrite training transfers cleanly")


# --------------- structural invariants ----------------------------------


@pytest.mark.parametrize("root", [V18_PANEL, V18_BROAD_ONLY])
def test_no_state_after_in_v18_metrics(root: Path) -> None:
    for cfg in ("raw", "rule", "learned", "policy"):
        md = _load(root / cfg / "metrics.json")
        if md is None:
            continue
        assert md["uses_state_after"] is False


@pytest.mark.parametrize("root", [V18_PANEL, V18_BROAD_ONLY])
def test_n_test_theorems_is_48(root: Path) -> None:
    md = _load(root / "policy" / "metrics.json")
    if md is None:
        pytest.skip(f"{root} absent")
    assert md["n_test_theorems"] == 48


def test_zero_shot_pass_at_10_floor() -> None:
    """The v18 brief is explicit: this is honest. Pin a *floor*
    (not a target) so a regression in v17 generation that drops
    transfer below 0.5 at pass@10 is caught."""
    md = _load(V18_BROAD_ONLY / "policy" / "metrics.json")
    if md is None:
        pytest.skip("v18 broad-only absent")
    assert md["pass@10"] >= 0.55, (
        f"v18 broad-only pass@10 dropped below 0.55: {md['pass@10']}")
