"""Pin v12 headline metrics so a silent regression is caught by pytest.

If the v12 eval is re-run with a different cache state or
verifier-timeout these constants may legitimately change. In that
case update PINNED below AND the tables in
``docs/V12_LITERAL_RERANK_REPORT.md`` and ``docs/RESULTS_SUMMARY.md``
in the same commit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "baselines" / "v12_eval"


def _load(fam: str, config: str) -> Optional[dict]:
    p = EVAL / fam / config / "metrics.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# (fam, config, key, expected_value)
PINNED = [
    # forall_inst headline: +literal_adapt+rerank wins; raw/literal_adapt/rerank stay at 1/7
    ("forall_inst", "raw", "pass@5", 1.0 / 7),
    ("forall_inst", "literal_adapt", "pass@5", 1.0 / 7),
    ("forall_inst", "rerank", "pass@5", 1.0 / 7),
    ("forall_inst", "literal_adapt_rerank", "pass@5", 3.0 / 7),  # 0.429
    ("forall_inst", "literal_adapt_rerank", "pass@1", 3.0 / 7),  # also 0.429
    # rewrite_succ floor preserved at 4/5 = 0.800 across configs
    ("rewrite_succ", "raw", "pass@5", 4.0 / 5),
    ("rewrite_succ", "literal_adapt_rerank", "pass@5", 4.0 / 5),
    # exists_reconstruct: +both lifts 4/5 -> 5/5
    ("exists_reconstruct", "raw", "pass@5", 4.0 / 5),
    ("exists_reconstruct", "literal_adapt_rerank", "pass@5", 5.0 / 5),
    # neg_exfalso unchanged
    ("neg_exfalso", "raw", "pass@5", 5.0 / 8),
    ("neg_exfalso", "literal_adapt_rerank", "pass@5", 5.0 / 8),
    # neg_imp_exfalso: still 0/5 (v10 has no contrapositive shape)
    ("neg_imp_exfalso", "raw", "pass@5", 0.0),
    ("neg_imp_exfalso", "literal_adapt_rerank", "pass@5", 0.0),
]


@pytest.mark.parametrize("fam,config,key,expected", PINNED,
                         ids=lambda x: str(x))
def test_v12_pinned_headline_value(fam: str, config: str, key: str, expected: float):
    md = _load(fam, config)
    if md is None:
        pytest.skip(f"v12 metrics missing for {fam}/{config}; eval not run yet")
    actual = md.get(key)
    assert actual == pytest.approx(expected, abs=1e-3), (
        f"{fam}/{config} {key}: expected {expected:.3f}, got {actual!r}. "
        f"If this is an intended change, update PINNED in this test AND "
        f"docs/V12_LITERAL_RERANK_REPORT.md / docs/RESULTS_SUMMARY.md."
    )


# ---------------- invariant tests ----------------


def test_v12_literal_adapt_alone_does_not_regress_pass5():
    """Adding literal-adapt candidates without reranking must NOT
    decrease pass@5 on any family — the originals stay at the top."""
    for fam in ("forall_inst", "rewrite_succ", "neg_exfalso",
                "exists_reconstruct", "neg_imp_exfalso"):
        raw = _load(fam, "raw")
        adapt = _load(fam, "literal_adapt")
        if raw is None or adapt is None:
            continue
        assert adapt["pass@5"] >= raw["pass@5"] - 1e-6, (
            f"{fam}: literal_adapt regressed pass@5 below raw "
            f"({adapt['pass@5']} < {raw['pass@5']})"
        )


def test_v12_rerank_alone_does_not_regress_pass5():
    """Rerank-alone (no new candidates) must not decrease pass@5."""
    for fam in ("forall_inst", "rewrite_succ", "neg_exfalso",
                "exists_reconstruct", "neg_imp_exfalso"):
        raw = _load(fam, "raw")
        r = _load(fam, "rerank")
        if raw is None or r is None:
            continue
        assert r["pass@5"] >= raw["pass@5"] - 1e-6, (
            f"{fam}: rerank regressed pass@5 below raw "
            f"({r['pass@5']} < {raw['pass@5']})"
        )


def test_v12_both_is_strictly_better_or_equal_to_either_alone():
    """The combined `literal_adapt_rerank` config should match or beat
    each single-layer config on pass@5 for every family."""
    for fam in ("forall_inst", "rewrite_succ", "neg_exfalso",
                "exists_reconstruct", "neg_imp_exfalso"):
        raw = _load(fam, "raw")
        adapt = _load(fam, "literal_adapt")
        r = _load(fam, "rerank")
        both = _load(fam, "literal_adapt_rerank")
        if any(x is None for x in (raw, adapt, r, both)):
            continue
        assert both["pass@5"] >= raw["pass@5"] - 1e-6
        assert both["pass@5"] >= adapt["pass@5"] - 1e-6
        assert both["pass@5"] >= r["pass@5"] - 1e-6


def test_v12_literal_adapt_does_not_touch_rewrite_succ_metrics():
    """rewrite_succ has no goal literal and no ``∀`` quantifier; the
    literal-adapt step must never fire on its rows. Verified candidate
    count may *drop* due to compose_candidates dedup of duplicate
    seq2seq beam entries — but pass@5 must be preserved."""
    raw = _load("rewrite_succ", "raw")
    both = _load("rewrite_succ", "literal_adapt_rerank")
    if raw is None or both is None:
        pytest.skip("rewrite_succ v12 metrics absent")
    assert both["literal_adapt_verified"] == 0
    assert both["pass@5"] == pytest.approx(raw["pass@5"], abs=1e-6)


def test_v12_forall_inst_has_literal_adapt_verified_count_at_least_2():
    """At least 2 of the 3 forall_inst wins must be literal-adapt
    candidates (the +literal_adapt+rerank headline)."""
    m = _load("forall_inst", "literal_adapt_rerank")
    if m is None:
        pytest.skip("forall_inst v12 metrics absent")
    assert m.get("literal_adapt_verified", 0) >= 2, (
        f"forall_inst literal_adapt_verified expected >= 2, got "
        f"{m.get('literal_adapt_verified')!r}"
    )


def test_v12_rewrite_succ_floor_preserved():
    """The v12 brief explicitly requires `rewrite_succ` pass@5 >= 0.800."""
    m = _load("rewrite_succ", "literal_adapt_rerank")
    if m is None:
        pytest.skip("rewrite_succ v12 metrics absent")
    assert m.get("pass@5", 0.0) >= 0.8 - 1e-6, (
        f"rewrite_succ pass@5 below brief's 0.800 floor: "
        f"{m.get('pass@5')!r}"
    )
