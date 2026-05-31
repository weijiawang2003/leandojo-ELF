"""Leakage guard tests for v10 holdout regimes.

A v10 *holdout* regime claims that test theorems are absent from the
training pool of the model evaluated on it. The combined_v10 (interpolation)
model violated this: it was trained on 36 of the 40 v10 cells, and the
cell_holdout/operation_holdout test sets re-tested those exact theorems —
turning what was advertised as a holdout signal into in-distribution
memorisation.

These tests pin the invariant. Each test asserts a theorem_name disjointness
between (a) a model's *training* train.jsonl and (b) the test.jsonl rows of
every fold the model is paired with.

They are intentionally separate from `tests/test_redundancy_splits.py` (which
only exercises split *generation*) so adding them does not silently mask the
leakage by passing on synthetic data.

The tests check what's present on disk:

* If the per-operation combined_v10 regime dirs exist
  (``data/processed/proof_blocks_combined_v10_per_op/<op>/``), they MUST be
  leakage-free against their matching operation_holdout test set.

* The legacy ``proof_blocks_combined_v10_redundancy_interpolation`` train
  pool IS expected to overlap the holdout test sets — the test asserts that
  *expected* overlap so a future "fix" that silently removes the regime is
  caught.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Set

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"


def _theorems_in(path: Path) -> Set[str]:
    out: Set[str] = set()
    if not path.exists():
        return out
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        try:
            r = json.loads(s)
        except json.JSONDecodeError:
            continue
        if r.get("theorem_name"):
            out.add(r["theorem_name"])
    return out


def _fold_test_theorems(regime_root: Path) -> List:
    out: List = []
    if not regime_root.exists():
        return out
    for fold in sorted(regime_root.iterdir()):
        if not fold.is_dir():
            continue
        out.append((fold.name, _theorems_in(fold / "test.jsonl")))
    return out


def test_per_op_combined_v10_no_leakage_against_op_holdout():
    """For each per-op combined_v10 regime, the matching op_holdout fold's
    test theorems must be ABSENT from train. Skips silently if the per-op
    regimes do not yet exist."""
    per_op_root = PROCESSED / "proof_blocks_combined_v10_per_op"
    if not per_op_root.exists():
        # The retrain has not yet run; nothing on disk to guard.
        return
    op_holdout_root = PROCESSED / "proof_blocks_redundancy_operation_holdout"
    if not op_holdout_root.exists():
        return
    violations: List[str] = []
    for op_dir in sorted(per_op_root.iterdir()):
        if not op_dir.is_dir():
            continue
        op = op_dir.name
        train_thms = _theorems_in(op_dir / "train.jsonl")
        fold_test_thms = _theorems_in(op_holdout_root / op / "test.jsonl")
        leaked = train_thms & fold_test_thms
        if leaked:
            violations.append(f"per_op/{op}: {len(leaked)} test theorem(s) leaked into train, "
                              f"e.g. {sorted(leaked)[:3]}")
    assert not violations, "v10 leakage in per-op combined_v10:\n  " + "\n  ".join(violations)


def test_per_op_combined_v10_train_excludes_v10_rows_of_held_operation():
    """Each per-op combined_v10 train pool must contain ZERO V10-CORPUS rows
    whose ``required_operation`` matches the held operation. v8 base-pool
    rows that happen to carry the held op label are *transfer signal*, not
    leakage — the baseline_v8 model has them too — so this test scopes the
    check to ``corpus_source == "redundancy_corpus"`` rows only."""
    per_op_root = PROCESSED / "proof_blocks_combined_v10_per_op"
    if not per_op_root.exists():
        return
    violations: List[str] = []
    for op_dir in sorted(per_op_root.iterdir()):
        if not op_dir.is_dir():
            continue
        op = op_dir.name
        train_p = op_dir / "train.jsonl"
        if not train_p.exists():
            continue
        bad_v10_rows = 0
        for ln in train_p.read_text(encoding="utf-8").splitlines():
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            try:
                r = json.loads(s)
            except json.JSONDecodeError:
                continue
            if (r.get("corpus_source") == "redundancy_corpus"
                    and r.get("required_operation") == op):
                bad_v10_rows += 1
        if bad_v10_rows:
            violations.append(f"per_op/{op}: {bad_v10_rows} v10 train row(s) carry "
                              f"required_operation={op}")
    assert not violations, ("per-op combined_v10 must exclude v10 cells of the held op:\n  "
                            + "\n  ".join(violations))


def test_baseline_v8_train_excludes_all_v10_cells():
    """The clean zero-shot baseline: baseline_v8 (proof_blocks_interpolation)
    must contain NO v10_* theorem. If a future regen accidentally folds the
    v10 corpus into the v8 interpolation pool, this catches it."""
    train_p = PROCESSED / "proof_blocks_interpolation" / "train.jsonl"
    val_p = PROCESSED / "proof_blocks_interpolation" / "val.jsonl"
    test_p = PROCESSED / "proof_blocks_interpolation" / "test.jsonl"
    train_thms = _theorems_in(train_p) | _theorems_in(val_p) | _theorems_in(test_p)
    v10_in_base = {t for t in train_thms if t.startswith("v10_")}
    assert not v10_in_base, (
        f"baseline_v8 (proof_blocks_interpolation) contaminated with v10 cells: "
        f"{sorted(v10_in_base)[:5]}"
    )


def test_legacy_combined_v10_interpolation_overlaps_holdout_test_documented():
    """Pin the *known* leakage in the legacy combined_v10_redundancy_interpolation
    pool. This test does NOT enforce 'no leakage' — it documents the bug. If
    the regime dir is deleted or rebuilt cleanly, this test fails LOUDLY so
    the docs that reference it are updated in lockstep."""
    legacy_train = PROCESSED / "proof_blocks_combined_v10_redundancy_interpolation" / "train.jsonl"
    if not legacy_train.exists():
        # If the legacy dir is gone, the docs MUST stop citing it; flag the
        # situation by failing the test so a reviewer is forced to update
        # docs/V10_SEQ2SEQ_SCALING_REPORT.md.
        raise AssertionError(
            "Legacy proof_blocks_combined_v10_redundancy_interpolation/train.jsonl is "
            "missing. Either it was deleted (update the leakage-bug doc accordingly) or "
            "the path moved. Resolve before re-enabling this test."
        )
    train_thms = _theorems_in(legacy_train)
    cell_root = PROCESSED / "proof_blocks_redundancy_cell_holdout"
    op_root = PROCESSED / "proof_blocks_redundancy_operation_holdout"
    cell_test = set()
    for fold, thms in _fold_test_theorems(cell_root):
        cell_test |= thms
    op_test = set()
    for fold, thms in _fold_test_theorems(op_root):
        op_test |= thms
    # Known leakage: train_thms overlaps cell_test AND op_test heavily.
    # Pin both overlaps so the bug is irrefutably documented.
    cell_overlap = train_thms & cell_test
    op_overlap = train_thms & op_test
    assert len(cell_overlap) >= 30, (
        f"unexpected: legacy interpolation pool only overlaps {len(cell_overlap)} cell_holdout "
        f"test theorems (was 36 at the bug-discovery moment). If the corpus was changed, "
        f"update V10_SEQ2SEQ_SCALING_REPORT.md to match."
    )
    assert len(op_overlap) >= 30, (
        f"unexpected: legacy interpolation pool only overlaps {len(op_overlap)} op_holdout "
        f"test theorems (was 36 at the bug-discovery moment)."
    )
