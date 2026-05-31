"""Pin v14 warm-rerun headline values.

v14 evaluation hit lean-cli cold-start timeouts on ~17 candidates at
120 s — the same pattern v13 saw on its rerun. Re-verifying at 180 s
flips 4 of them. This module pins:

  * the v14 warm-corrected pass@k for the headline families
    (`forall_inst`, `neg_imp_exfalso`),
  * that v14 warm rerun did not silently overwrite v12 / v13 disk
    metrics,
  * and the regression-guard for the v14 mechanism: `forall_inst_var_m`
    must be VERIFIED under v14 + LA + warm (it was the v13 residual).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
V12 = ROOT / "data" / "baselines" / "v12_eval"
V13 = ROOT / "data" / "baselines" / "v13_timeout_rerun"
V14 = ROOT / "data" / "baselines" / "v14_timeout_rerun"


def _load_v14_warm() -> Optional[Dict[str, Any]]:
    p = V14 / "metrics_rerun.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _load_v14_summary() -> Optional[Dict[str, Any]]:
    p = V14 / "rerun_summary.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ----------------- pinned warm-corrected values --------------------------


# (family, config, key, expected) — the v14 headline.
PINNED = [
    # forall_inst literal_adapt_rerank: 7/7 after warm rerun
    ("forall_inst", "literal_adapt_rerank", "pass@1_warm_rerun", 7.0 / 7),
    ("forall_inst", "literal_adapt_rerank", "pass@5_warm_rerun", 7.0 / 7),
    ("forall_inst", "literal_adapt_rerank", "pass@10_warm_rerun", 7.0 / 7),
    # rewrite_succ unchanged
    ("rewrite_succ", "raw", "pass@5_warm_rerun", 1.000),
    ("rewrite_succ", "literal_adapt_rerank", "pass@5_warm_rerun", 1.000),
    # neg_imp_exfalso raw warm: pass@5 = 12/15
    ("neg_imp_exfalso", "raw", "pass@5_warm_rerun", 12.0 / 15),
    # neg_imp_exfalso +LA+rerank: pass@10 = 15/15 (the reranker
    # mis-calibrates on pass@5 = 3/15 = 0.200 but candidate is in beam)
    ("neg_imp_exfalso", "literal_adapt_rerank", "pass@10_warm_rerun", 15.0 / 15),
    ("neg_imp_exfalso", "literal_adapt_rerank", "pass@5_warm_rerun", 3.0 / 15),
    # exists_reconstruct warm: 15/15
    ("exists_reconstruct", "raw", "pass@5_warm_rerun", 15.0 / 15),
    ("exists_reconstruct", "literal_adapt_rerank", "pass@5_warm_rerun", 15.0 / 15),
    # neg_exfalso unchanged
    ("neg_exfalso", "literal_adapt_rerank", "pass@5_warm_rerun", 0.625),
]


@pytest.mark.parametrize("fam,cfg,key,expected", PINNED,
                         ids=lambda x: str(x))
def test_v14_warm_pinned(fam: str, cfg: str, key: str, expected: float) -> None:
    m = _load_v14_warm()
    if m is None:
        pytest.skip("v14 warm metrics absent")
    fam_d = m.get(fam) or {}
    cfg_d = fam_d.get(cfg)
    if cfg_d is None:
        pytest.skip(f"{fam}/{cfg} absent")
    actual = cfg_d.get(key)
    assert actual == pytest.approx(expected, abs=1e-3), (
        f"{fam}/{cfg} {key}: expected {expected:.3f} got {actual!r}. "
        f"If intended, update PINNED here AND docs."
    )


# ----------------- honesty invariants ------------------------------------


def test_v14_does_not_overwrite_v12_metrics() -> None:
    fp = V12 / "forall_inst" / "literal_adapt_rerank" / "metrics.json"
    if not fp.exists():
        pytest.skip("v12 metrics absent")
    md = json.loads(fp.read_text(encoding="utf-8"))
    assert md.get("pass@5") == pytest.approx(3.0 / 7, abs=1e-3), (
        "v14 silently overwrote v12 metrics — honesty violation"
    )


def test_v14_does_not_overwrite_v13_metrics() -> None:
    fp = V13 / "metrics_rerun.json"
    if not fp.exists():
        pytest.skip("v13 metrics absent")
    md = json.loads(fp.read_text(encoding="utf-8"))
    v = md.get("forall_inst", {}).get("literal_adapt_rerank", {}).get(
        "pass@5_warm_rerun")
    assert v == pytest.approx(6.0 / 7, abs=1e-3), (
        "v14 silently overwrote v13 metrics — honesty violation"
    )


def test_v14_rerun_summary_counts() -> None:
    s = _load_v14_summary()
    if s is None:
        pytest.skip("v14 summary absent")
    # The v14 rerun should flip exactly 4 of 17 candidates per the
    # report. Pin to catch silent recompute drift.
    assert s["n_verified_after_rerun"] == 4
    assert s["n_targets"] == 17
    assert s["n_still_timeout"] == 0
    assert 120.0 <= s["timeout_seconds_used"] <= 240.0


def test_v14_warm_no_regression_below_lower_bound() -> None:
    """A warm rerun can only confirm or upgrade — never downgrade
    from the v14 lower bound."""
    m = _load_v14_warm()
    if m is None:
        pytest.skip("v14 warm metrics absent")
    for fam, cfgs in m.items():
        for cfg, d in cfgs.items():
            for k in (1, 5, 10):
                lo = d.get(f"pass@{k}_original_lower_bound")
                warm = d.get(f"pass@{k}_warm_rerun")
                if lo is None or warm is None:
                    continue
                assert warm + 1e-6 >= lo, (
                    f"{fam}/{cfg} pass@{k} regressed under warm rerun: "
                    f"{warm} < {lo}"
                )


def test_forall_inst_var_m_is_fixed_by_v14() -> None:
    """The v14 brief's headline target: the v13 residual
    forall_inst_var_m must verify under v14 + LA + warm. This is the
    inverse of test_v13_timeout_rerun's regression-guard.
    """
    # Check that the v14 literal_adapt_rerank predictions show var_m
    # as pass@5 = True.
    p = (ROOT / "data" / "baselines" / "v14_token_seq2seq"
         / "forall_inst" / "literal_adapt_rerank" / "predictions.jsonl")
    if not p.exists():
        pytest.skip("v14 forall_inst predictions absent")
    found_var_m = False
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("theorem_name") == "forall_inst_var_m":
            found_var_m = True
            assert r.get("pass@5") is True, (
                "v14 literal_adapt_rerank failed to solve "
                "forall_inst_var_m — v14's headline brief target. "
                f"Got: {r.get('pass@5')!r}"
            )
    assert found_var_m, (
        "forall_inst_var_m not found in v14 predictions — "
        "test set composition changed?"
    )


def test_neg_imp_exfalso_cross_family_composition_present() -> None:
    """v14's neg_imp_exfalso win comes from the model emitting
    `intro hp\\n  exact absurd hp hnp` — composed from sibling
    families, not in the neg_imp_exfalso train set. We pin that the
    string appears as a VERIFIED candidate at least once."""
    p = (ROOT / "data" / "baselines" / "v14_token_seq2seq"
         / "neg_imp_exfalso" / "raw" / "predictions.jsonl")
    if not p.exists():
        pytest.skip("v14 neg_imp_exfalso predictions absent")
    target = "intro hp\n  exact absurd hp hnp"
    saw_verified = 0
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        for c, v in zip(r.get("candidates", []), r.get("verifications", [])):
            if c == target and v.get("success"):
                saw_verified += 1
    assert saw_verified >= 3, (
        f"v14 mechanism check: the composed contrapositive "
        f"{target!r} must verify on at least 3 neg_imp_exfalso rows. "
        f"Got: {saw_verified}"
    )
