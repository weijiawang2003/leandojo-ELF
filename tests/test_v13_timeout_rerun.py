"""Pin the v13 warm-verifier rerun headline metrics.

The v13 rerun corrects v12's verifier-timeout false negatives. The
v12 metrics on disk are untouched (and pinned by
``tests/test_v12_eval.py``). This module pins the *corrected* numbers
the warm rerun produced.

Like ``test_v12_eval.py``, any legitimate change here must be
accompanied by a matching update of ``docs/V13_TIMEOUT_RERUN_REPORT.md``
and ``docs/RESULTS_SUMMARY.md``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
V13 = ROOT / "data" / "baselines" / "v13_timeout_rerun"


def _load() -> Optional[dict]:
    p = V13 / "metrics_rerun.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _load_summary() -> Optional[dict]:
    p = V13 / "rerun_summary.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _load_original_snapshot() -> Optional[dict]:
    p = V13 / "metrics_original.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------- pinned headline values ----------------


# (family, config, key, expected_warm_value)
PINNED_WARM = [
    # forall_inst: 3/7 → 6/7 after timeout rerun
    ("forall_inst", "literal_adapt_rerank", "pass@1_warm_rerun", 6.0 / 7),
    ("forall_inst", "literal_adapt_rerank", "pass@5_warm_rerun", 6.0 / 7),
    ("forall_inst", "literal_adapt_rerank", "pass@10_warm_rerun", 6.0 / 7),
    # forall_inst literal_adapt alone: pass@10 lifts from 1/7 to 2/7
    ("forall_inst", "literal_adapt", "pass@10_warm_rerun", 2.0 / 7),
    # rewrite_succ: 4/5 → 5/5 across every config
    ("rewrite_succ", "raw", "pass@5_warm_rerun", 5.0 / 5),
    ("rewrite_succ", "literal_adapt", "pass@5_warm_rerun", 5.0 / 5),
    ("rewrite_succ", "rerank", "pass@5_warm_rerun", 5.0 / 5),
    ("rewrite_succ", "literal_adapt_rerank", "pass@5_warm_rerun", 5.0 / 5),
    # exists_reconstruct: unchanged after rerun (timeouts were on
    # already-passing rows whose underlying error wasn't 'timeout')
    ("exists_reconstruct", "literal_adapt_rerank", "pass@5_warm_rerun", 5.0 / 5),
    # neg_exfalso, neg_imp_exfalso: no timeouts, no change
    ("neg_exfalso", "literal_adapt_rerank", "pass@5_warm_rerun", 5.0 / 8),
    ("neg_imp_exfalso", "literal_adapt_rerank", "pass@5_warm_rerun", 0.0),
]


@pytest.mark.parametrize("fam,config,key,expected", PINNED_WARM,
                         ids=lambda x: str(x))
def test_v13_warm_pinned_value(fam: str, config: str, key: str,
                               expected: float) -> None:
    m = _load()
    if m is None:
        pytest.skip("v13 metrics_rerun.json not present; rerun not executed")
    fam_d = m.get(fam) or {}
    cfg_d = fam_d.get(config)
    if cfg_d is None:
        pytest.skip(f"{fam}/{config} missing from rerun metrics")
    actual = cfg_d.get(key)
    assert actual == pytest.approx(expected, abs=1e-3), (
        f"{fam}/{config} {key}: expected {expected:.3f}, got {actual!r}. "
        f"If intended, update PINNED_WARM here AND "
        f"docs/V13_TIMEOUT_RERUN_REPORT.md / docs/RESULTS_SUMMARY.md."
    )


# ---------------- invariants ----------------


def test_v13_does_not_overwrite_v12_metrics_on_disk() -> None:
    """v12 metrics under data/baselines/v12_eval/ must remain pinned
    to their lower-bound values. The v13 rerun publishes to a parallel
    path."""
    v12_metric_p = ROOT / "data" / "baselines" / "v12_eval" / "forall_inst" \
        / "literal_adapt_rerank" / "metrics.json"
    if not v12_metric_p.exists():
        pytest.skip("v12 metrics absent on disk")
    v12 = json.loads(v12_metric_p.read_text(encoding="utf-8"))
    # v12 pinned forall_inst pass@5 lower bound = 3/7 = 0.429
    assert v12.get("pass@5") == pytest.approx(3.0 / 7, abs=1e-3), (
        "v13 rerun silently overwrote v12 metrics — this is a "
        "honesty-contract violation. v12 must remain at its lower bound."
    )


def test_v13_original_snapshot_matches_current_v12_disk() -> None:
    """The metrics_original.json snapshot v13 wrote at run time must
    match the v12 disk state field-for-field at the time the snapshot
    was taken — so a future reader can audit the corrected numbers
    against the exact original."""
    snap = _load_original_snapshot()
    if snap is None:
        pytest.skip("metrics_original.json snapshot not present")
    v12_dir = ROOT / "data" / "baselines" / "v12_eval"
    # Spot-check: forall_inst/literal_adapt_rerank
    fp = v12_dir / "forall_inst" / "literal_adapt_rerank" / "metrics.json"
    if not fp.exists():
        pytest.skip("v12 metrics absent")
    on_disk = json.loads(fp.read_text(encoding="utf-8"))
    assert snap["forall_inst"]["literal_adapt_rerank"]["pass@5"] == \
        pytest.approx(on_disk["pass@5"], abs=1e-6)
    assert snap["forall_inst"]["literal_adapt_rerank"]["pass@1"] == \
        pytest.approx(on_disk["pass@1"], abs=1e-6)


def test_v13_rerun_summary_counts_match_brief() -> None:
    s = _load_summary()
    if s is None:
        pytest.skip("rerun_summary.json missing")
    # The brief predicts exactly 4 forall_inst + rewrite_succ flips
    # (exact h 5, exact h 13, exact h 8, rw [h]).
    assert s["n_verified_after_rerun"] == 4, (
        f"expected 4 timeout→verified flips per v13 brief, got "
        f"{s['n_verified_after_rerun']}"
    )
    # No target should remain in timeout state at 120 s.
    assert s["n_still_timeout"] == 0
    # The configured timeout must match what the brief asked for
    # (120-180 s).
    assert 120.0 <= s["timeout_seconds_used"] <= 180.0


def test_v13_warm_rerun_does_not_regress_below_v12_lower_bound() -> None:
    """A warm rerun can only confirm or upgrade; it must never drop
    pass@k below the v12 lower bound (that would mean the warm verifier
    *flipped a v12 success into a failure*, which would be a bug)."""
    m = _load()
    if m is None:
        pytest.skip("v13 metrics absent")
    snap = _load_original_snapshot()
    if snap is None:
        pytest.skip("v12 snapshot absent")
    for fam, cfgs in m.items():
        for cfg, d in cfgs.items():
            orig = snap.get(fam, {}).get(cfg)
            if orig is None:
                continue
            for k in (1, 5, 10):
                warm = d.get(f"pass@{k}_warm_rerun")
                lo = orig.get(f"pass@{k}")
                if warm is None or lo is None:
                    continue
                assert warm + 1e-6 >= lo, (
                    f"{fam}/{cfg} pass@{k} regressed under warm rerun: "
                    f"{warm:.4f} < {lo:.4f}"
                )


def test_forall_inst_var_m_remains_unfixed_by_warm_rerun() -> None:
    """The v13 brief is explicit: ``forall_inst_var_m`` is the
    residual case the warm rerun does NOT fix (it's a char-truncation
    + schema-gate issue, not a timeout). If a future change appears
    to fix it without retraining, the test should fail so we can
    audit *why*."""
    p = V13 / "changed_results.jsonl"
    if not p.exists():
        pytest.skip("changed_results.jsonl missing")
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("theorem_name") == "forall_inst_var_m":
            assert not r.get("flipped_timeout_to_verified", False), (
                "forall_inst_var_m flipped to verified under warm rerun? "
                "Audit before accepting — the v13 brief documented this "
                "as a tokenizer-class failure, not a timeout."
            )
