"""Unit tests for the v10 redundancy-corpus split strategies (pure, no Lean/torch).

Covers ``cell_holdout_folds``, ``kshot_operation_split``, and the
``operation_sibling_in_train`` invariant added to ``retrieval_splits``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mini_elf_lean.retrieval_splits import (  # noqa: E402
    OP_UNKNOWN,
    assert_no_theorem_leakage,
    cell_holdout_folds,
    family_absent_from_train,
    kshot_operation_split,
    operation_absent_from_train,
    operation_sibling_in_train,
)

# Synthetic redundancy corpus: 3 operations × 2 surface families × 1 cell.
THMS = ["op1_f1", "op1_f2", "op2_f1", "op2_f2", "op3_f1", "op3_f2"]
FAM = {
    "op1_f1": "f1_op1", "op1_f2": "f2_op1",
    "op2_f1": "f1_op2", "op2_f2": "f2_op2",
    "op3_f1": "f1_op3", "op3_f2": "f2_op3",
}
OP = {
    "op1_f1": "op1", "op1_f2": "op1",
    "op2_f1": "op2", "op2_f2": "op2",
    "op3_f1": "op3", "op3_f2": "op3",
}


# ---------------- cell_holdout ----------------


def test_cell_holdout_one_fold_per_cell():
    folds = cell_holdout_folds(THMS, OP, FAM)
    # one fold per (operation, surface_family) pair
    assert len(folds) == len(THMS)
    cells = {held for held, _ in folds}
    assert cells == {(OP[t], FAM[t]) for t in THMS}


def test_cell_holdout_no_leakage_and_held_family_absent():
    for (held_op, held_fam), assign in cell_holdout_folds(THMS, OP, FAM):
        assert_no_theorem_leakage(assign)
        # the held cell's theorem(s) are the test set
        assert {t for t, s in assign.items() if s == "test"} \
               == {t for t in THMS if OP[t] == held_op and FAM[t] == held_fam}
        # the held surface family is absent from train
        assert family_absent_from_train(assign, FAM, held_fam)


def test_cell_holdout_keeps_operation_sibling_in_train():
    # In the synthetic corpus each operation has 2 surface families: when one is
    # held out, the *other* family of the same operation MUST remain in train.
    for (held_op, held_fam), assign in cell_holdout_folds(THMS, OP, FAM):
        assert operation_sibling_in_train(assign, OP, FAM, held_op, held_fam), \
            f"v10 redundancy invariant broken: no sibling of {held_op} when {held_fam} held"


def test_cell_holdout_does_not_remove_the_whole_operation():
    # Distinguishes cell_holdout from operation_holdout: holding a single cell
    # must *not* remove the whole operation from train.
    for (held_op, _held_fam), assign in cell_holdout_folds(THMS, OP, FAM):
        train_ops = {OP[t] for t, s in assign.items() if s == "train"}
        assert held_op in train_ops, f"cell_holdout incorrectly removed all of op {held_op}"


# ---------------- kshot_operation_split ----------------


def test_kshot_operation_respects_k():
    for k in (1, 2):
        assign = kshot_operation_split(THMS, OP, FAM, k)
        assert_no_theorem_leakage(assign)
        for op in set(OP.values()):
            train_fams = {FAM[t] for t, s in assign.items()
                          if s == "train" and OP[t] == op}
            assert len(train_fams) <= k, f"op={op} k={k}: {len(train_fams)} train fams"


def test_kshot_operation_k1_includes_one_family_per_operation():
    assign = kshot_operation_split(THMS, OP, FAM, 1)
    for op in set(OP.values()):
        train_fams = {FAM[t] for t, s in assign.items() if s == "train" and OP[t] == op}
        assert len(train_fams) == 1, f"k=1 expected exactly 1 train family/op, got {train_fams}"


def test_kshot_operation_is_deterministic():
    a = kshot_operation_split(THMS, OP, FAM, 1, seed=42)
    b = kshot_operation_split(THMS, OP, FAM, 1, seed=42)
    assert a == b


def test_kshot_operation_k2_grows_train_over_k1():
    n1 = sum(1 for s in kshot_operation_split(THMS, OP, FAM, 1).values() if s == "train")
    n2 = sum(1 for s in kshot_operation_split(THMS, OP, FAM, 2).values() if s == "train")
    assert n2 >= n1


# ---------------- operation_sibling_in_train invariant ----------------


def test_operation_sibling_helper_true_when_sibling_present():
    assign = {"op1_f1": "test", "op1_f2": "train",
              "op2_f1": "train", "op2_f2": "train",
              "op3_f1": "train", "op3_f2": "train"}
    assert operation_sibling_in_train(assign, OP, FAM, "op1", "f1_op1") is True


def test_operation_sibling_helper_false_when_all_siblings_held():
    # If both op1 cells are test, no sibling remains in train.
    assign = {"op1_f1": "test", "op1_f2": "test",
              "op2_f1": "train", "op2_f2": "train",
              "op3_f1": "train", "op3_f2": "train"}
    assert operation_sibling_in_train(assign, OP, FAM, "op1", "f1_op1") is False


# ---------------- mixed with unknown ----------------


def test_cell_holdout_handles_unknown_operation():
    op = dict(OP)
    op["op1_f1"] = OP_UNKNOWN
    op["op1_f2"] = OP_UNKNOWN
    folds = cell_holdout_folds(THMS, op, FAM)
    cells = {held for held, _ in folds}
    assert (OP_UNKNOWN, "f1_op1") in cells
    assert (OP_UNKNOWN, "f2_op1") in cells


# ---------------- cross-invariant sanity: kshot composed with operation_holdout ----------------


def test_kshot_operation_held_operation_stays_test_when_k_is_zero_for_that_op():
    # k=1: keep 1 fam/op; subset that ends up in test must not equal everything.
    assign = kshot_operation_split(THMS, OP, FAM, 1, seed=42)
    for op in set(OP.values()):
        op_test = {t for t, s in assign.items() if s == "test" and OP[t] == op}
        op_train = {t for t, s in assign.items() if s == "train" and OP[t] == op}
        # at k=1 with 2 cells/op, exactly one train and one test for each op
        assert len(op_train) == 1 and len(op_test) == 1, \
            f"k=1 op={op}: train={op_train}, test={op_test}"
