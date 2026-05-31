"""Pin v11 per-family LOFO eval headline numbers so a silent regression
(or a silent improvement that quietly bypasses a leakage check) is
caught by pytest, not only by reading the docs.

These tests skip silently if the v11 eval has not yet been run
(`data/baselines/v11_family_lofo_eval/<fam>/<model>/metrics.json` absent).

Pinned cells:
  * forall_inst: v8_lofo pass@5 == 0.000, v11 pass@5 == 0.143
  * rewrite_succ: v8_lofo pass@5 == 0.000, v11 pass@5 == 0.800
  * exists_reconstruct: v8_lofo pass@5 == 0.400, v11 pass@5 == 0.800
  * neg_exfalso: v8_lofo pass@5 == 0.625, v11 pass@5 == 0.625
                 (precision-only lift, pass@1 0.125 -> 0.625)
  * neg_imp_exfalso: both 0.000 (unmoved)

If the eval is re-run with a different seed, verifier timeout, or
training corpus, these pinned values may legitimately change. In that
case update the doc tables in `docs/V11_FAMILY_LOFO_REDUNDANCY_REPORT.md`
and `docs/RESULTS_SUMMARY.md` in the same commit that updates these
constants.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "baselines" / "v11_family_lofo_eval"


def _load(fam: str, tag: str) -> Optional[dict]:
    p = EVAL / fam / tag / "metrics.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# Pinned headline values (lean-cli pass@5 unless noted). Each row is
# (fam, tag, key, value) — equality required.
PINNED = [
    ("forall_inst",        "v8_lofo", "pass@5", 0.0),
    ("forall_inst",        "v11",     "pass@5", 1.0 / 7),  # 0.143
    ("rewrite_succ",       "v8_lofo", "pass@5", 0.0),
    ("rewrite_succ",       "v11",     "pass@5", 4.0 / 5),  # 0.800
    ("exists_reconstruct", "v8_lofo", "pass@5", 2.0 / 5),  # 0.400
    ("exists_reconstruct", "v11",     "pass@5", 4.0 / 5),  # 0.800
    ("neg_exfalso",        "v8_lofo", "pass@5", 5.0 / 8),  # 0.625
    ("neg_exfalso",        "v11",     "pass@5", 5.0 / 8),  # 0.625
    ("neg_exfalso",        "v8_lofo", "pass@1", 1.0 / 8),  # 0.125
    ("neg_exfalso",        "v11",     "pass@1", 5.0 / 8),  # 0.625 precision lift
    ("neg_imp_exfalso",    "v8_lofo", "pass@5", 0.0),
    ("neg_imp_exfalso",    "v11",     "pass@5", 0.0),
]


@pytest.mark.parametrize("fam,tag,key,expected", PINNED,
                         ids=lambda x: str(x))
def test_v11_pinned_headline_value(fam: str, tag: str, key: str, expected: float):
    md = _load(fam, tag)
    if md is None:
        pytest.skip(f"v11 metrics missing for {fam}/{tag}; eval not run yet")
    actual = md.get(key)
    assert actual == pytest.approx(expected, abs=1e-3), (
        f"{fam}/{tag} {key}: expected {expected:.3f}, got {actual!r}. "
        f"If this is an intended change, update PINNED in this test AND "
        f"the headline tables in docs/V11_FAMILY_LOFO_REDUNDANCY_REPORT.md "
        f"and docs/RESULTS_SUMMARY.md in the same commit."
    )


def test_v11_novel_verified_is_zero_on_every_win():
    """v11's docs claim ``novel_verified = 0`` on every winning fold —
    the verifying tactic strings all live in train via v10 siblings. Pin
    that invariant so a future model that synthesises novel strings is
    caught by pytest (and the claim is updated)."""
    wins = [
        ("forall_inst", "v11"),
        ("rewrite_succ", "v11"),
        ("exists_reconstruct", "v11"),
        ("neg_exfalso", "v11"),  # 5 novel verified — but they come from v8 base, NOT a v11 contribution
    ]
    for fam, tag in wins:
        md = _load(fam, tag)
        if md is None:
            continue
        if fam == "neg_exfalso":
            # neg_exfalso has 5 novel from v8's neg sibling families;
            # documented as "5 novel" in the per-family table. Pin it.
            assert md.get("novel_verified") == 5, (
                f"neg_exfalso/v11 novel_verified expected 5, got "
                f"{md.get('novel_verified')!r}"
            )
            continue
        nov = md.get("novel_verified")
        assert nov == 0, (
            f"{fam}/{tag} novel_verified expected 0 (v11 copies from v10 "
            f"siblings under LOFO; no novel-string synthesis), got {nov!r}"
        )


def test_v11_cross_operation_verified_rewrite_succ_is_four():
    """rewrite_succ is the v11 headline cross-operation result. The held
    operation `rewrite` is absent from train; v11 verifies via v10
    `rewrite_eq` cells which Lean considers a different `required_operation`
    label but the same tactic shape. Pin the count so the
    docs and the metrics stay in sync."""
    md = _load("rewrite_succ", "v11")
    if md is None:
        pytest.skip("v11 rewrite_succ metrics absent")
    assert md.get("cross_operation_verified") == 4, (
        f"rewrite_succ/v11 cross_operation_verified expected 4, got "
        f"{md.get('cross_operation_verified')!r}"
    )
