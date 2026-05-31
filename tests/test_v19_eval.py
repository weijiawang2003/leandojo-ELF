"""Pin the v19 evaluation headline numbers — including the honest
negative finding.

The v19 brief explicitly anticipated a negative result and asked
for honest reporting. So this module:
  * Pins the v19 abstract-only and ensemble pass@k *floors* (so a
    regression below the documented numbers is caught).
  * Pins the *direction* of the result: v19 is worse than v18
    broad-synthetic on the broad-core benchmark — this is the
    honest finding the docs spell out.
  * Confirms v17/v18 metrics on disk are NOT touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]

V18_BROAD = ROOT / "data" / "baselines" / "v18_broad_only_eval"
V19_ABS_ONLY = ROOT / "data" / "baselines" / "v19_abstract_only_eval"
V19_ENSEMBLE = ROOT / "data" / "baselines" / "v19_abstract_ensemble_eval"
V17_POL = ROOT / "data" / "baselines" / "v17_policy_eval"


def _load(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ----------------- v17/v18 metrics on disk untouched ------------------


def test_v19_does_not_overwrite_v17() -> None:
    md = _load(V17_POL / "neg_exfalso" / "policy" / "metrics.json")
    if md is None:
        pytest.skip("v17 absent")
    # v17 closed neg_exfalso to 1.000 at pass@5
    assert md["pass@5"] == pytest.approx(1.000, abs=1e-3)


def test_v19_does_not_overwrite_v18_broad() -> None:
    md = _load(V18_BROAD / "policy" / "metrics.json")
    if md is None:
        pytest.skip("v18 broad absent")
    assert md["pass@5"] == pytest.approx(28 / 48, abs=1e-3)


# ----------------- v19 abstract-only pinned values --------------------


@pytest.mark.parametrize("cfg,key,expected", [
    ("raw", "pass@1", 4 / 48),     # 0.083
    ("raw", "pass@5", 7 / 48),     # 0.146
    ("raw", "pass@10", 13 / 48),   # 0.271
    ("rule", "pass@1", 6 / 48),    # 0.125
    ("rule", "pass@5", 9 / 48),    # 0.188
    ("policy", "pass@1", 7 / 48),  # 0.146
    ("policy", "pass@5", 10 / 48), # 0.208
    ("policy", "pass@10", 13 / 48),# 0.271
])
def test_v19_abstract_only_pinned(cfg, key, expected) -> None:
    md = _load(V19_ABS_ONLY / cfg / "metrics.json")
    if md is None:
        pytest.skip(f"v19 abstract-only {cfg} absent")
    assert md[key] == pytest.approx(expected, abs=1e-3), (
        f"v19 abstract-only {cfg} {key} = {md[key]} "
        f"(expected {expected:.3f})")


# ----------------- v19 ensemble pinned values --------------------------


@pytest.mark.parametrize("cfg,key,expected", [
    ("policy", "pass@1", 7 / 48),  # 0.146
    ("policy", "pass@5", 15 / 48), # 0.312
    ("policy", "pass@10", 21 / 48),# 0.438
    ("rule", "pass@5", 15 / 48),   # 0.312
    ("rule", "pass@10", 27 / 48),  # 0.562
])
def test_v19_ensemble_pinned(cfg, key, expected) -> None:
    md = _load(V19_ENSEMBLE / cfg / "metrics.json")
    if md is None:
        pytest.skip(f"v19 ensemble {cfg} absent")
    assert md[key] == pytest.approx(expected, abs=1e-3), (
        f"v19 ensemble {cfg} {key} = {md[key]} "
        f"(expected {expected:.3f})")


# ----------------- the honest negative-result direction --------------


def test_v19_underperforms_v18_broad_on_pass_at_5() -> None:
    """The honest v19 finding: abstraction-based generation
    UNDERPERFORMS the v18 broad-synthetic baseline on the v18
    broad-core benchmark. Pin the direction so a future change
    that flips the sign is flagged for re-inspection."""
    v18 = _load(V18_BROAD / "policy" / "metrics.json")
    v19_a = _load(V19_ABS_ONLY / "policy" / "metrics.json")
    v19_e = _load(V19_ENSEMBLE / "policy" / "metrics.json")
    if v18 is None or v19_a is None or v19_e is None:
        pytest.skip("v18/v19 metrics absent")
    assert v19_a["pass@5"] < v18["pass@5"], (
        f"v19 abstract-only ({v19_a['pass@5']}) should be < v18 "
        f"broad-only ({v18['pass@5']}) — the documented honest "
        f"negative result")
    assert v19_e["pass@5"] < v18["pass@5"], (
        f"v19 ensemble ({v19_e['pass@5']}) should be < v18 "
        f"broad-only ({v18['pass@5']})")


def test_unresolved_placeholder_is_new_dominant_failure_class() -> None:
    """Pin that the v19 abstract eval introduces a new
    `unresolved_placeholder` failure class at >= 100 slots.
    This is the brief's anticipated "new dominant failure"."""
    md = _load(V19_ABS_ONLY / "policy" / "metrics.json")
    if md is None:
        pytest.skip("v19 abstract-only absent")
    assert md.get("n_unresolved_placeholder_top10", 0) >= 100, (
        f"unresolved_placeholder count = "
        f"{md.get('n_unresolved_placeholder_top10')}; expected ≥ 100 "
        f"per the v19 honest negative finding")


# ----------------- no state_after ------------------------------------


def test_v19_metrics_have_no_state_after_field() -> None:
    for root in (V19_ABS_ONLY, V19_ENSEMBLE):
        for cfg in ("raw", "rule", "policy"):
            md = _load(root / cfg / "metrics.json")
            if md is None:
                continue
            assert md.get("uses_state_after") is False


def test_v19_metrics_have_per_category_breakdown() -> None:
    md = _load(V19_ABS_ONLY / "policy" / "metrics.json")
    if md is None:
        pytest.skip("v19 abstract-only absent")
    assert "per_category" in md
    expected_cats = {"implication", "conjunction", "disjunction",
                     "negation", "equality_rewrite", "exists",
                     "forall", "nat_succ", "bool", "list"}
    assert set(md["per_category"]) >= expected_cats
