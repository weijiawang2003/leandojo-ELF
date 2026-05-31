"""Unit tests for the v7 donor-scarcity split strategies (pure, no Lean/torch)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mini_elf_lean.retrieval_splits import (  # noqa: E402
    OP_UNKNOWN,
    assert_no_theorem_leakage,
    family_absent_from_train,
    family_holdout_folds,
    family_train_count,
    kshot_family_split,
    literal_holdout_split,
    operation_absent_from_train,
    operation_holdout_folds,
)

# Synthetic corpus: families A,B share operation opX; C is opY.
THMS = ["a1", "a2", "a3", "b1", "b2", "c1"]
FAM = {"a1": "A", "a2": "A", "a3": "A", "b1": "B", "b2": "B", "c1": "C"}
OP = {"a1": "opX", "a2": "opX", "a3": "opX", "b1": "opX", "b2": "opX", "c1": "opY"}


def test_family_holdout_no_test_family_in_train():
    folds = family_holdout_folds(THMS, FAM)
    assert {held for held, _ in folds} == {"A", "B", "C"}
    for held, assign in folds:
        assert_no_theorem_leakage(assign)
        assert family_absent_from_train(assign, FAM, held)
        # the held family's theorems are exactly the test set
        assert {t for t, s in assign.items() if s == "test"} == {t for t in THMS if FAM[t] == held}
        # every theorem is assigned exactly once
        assert set(assign) == set(THMS)


def test_family_holdout_keeps_same_operation_sibling():
    folds = dict(family_holdout_folds(THMS, FAM))
    # holding out A leaves B (same opX) in train -> a same-operation sibling exists
    a_assign = folds["A"]
    train_ops = {OP[t] for t, s in a_assign.items() if s == "train"}
    assert "opX" in train_ops  # B supplies opX even though A is held out


def test_operation_holdout_no_target_operation_in_train():
    folds = operation_holdout_folds(THMS, OP)
    assert {held for held, _ in folds} == {"opX", "opY"}
    for held, assign in folds:
        assert operation_absent_from_train(assign, OP, held)
    # holding out opX removes BOTH families A and B from train (harder than family holdout)
    opx = dict(folds)["opX"]
    assert {t for t, s in opx.items() if s == "train"} == {"c1"}


def test_operation_holdout_handles_unknown_operation():
    op = dict(OP)
    op["c1"] = OP_UNKNOWN
    folds = dict(operation_holdout_folds(THMS, op))
    assert OP_UNKNOWN in folds
    assert operation_absent_from_train(folds[OP_UNKNOWN], op, OP_UNKNOWN)


def test_kshot_respects_k():
    for k in (0, 1, 2):
        assign = kshot_family_split(THMS, FAM, k)
        assert_no_theorem_leakage(assign)
        for fam in set(FAM.values()):
            assert family_train_count(assign, FAM, fam) <= k
        if k == 0:
            assert all(s == "test" for s in assign.values())  # floor: empty train


def test_kshot_is_deterministic():
    assert kshot_family_split(THMS, FAM, 1, seed=42) == kshot_family_split(THMS, FAM, 1, seed=42)


def test_kshot_train_grows_with_k():
    n1 = sum(1 for s in kshot_family_split(THMS, FAM, 1).values() if s == "train")
    n2 = sum(1 for s in kshot_family_split(THMS, FAM, 2).values() if s == "train")
    assert n2 >= n1


def test_literal_holdout_schema_present_literal_unseen():
    # A-family shares one literal-bearing schema with three distinct literals.
    tactics = {
        "a1": ["exact h 1"], "a2": ["exact h 2"], "a3": ["exact h 3"],
        "b1": ["rw [h]"], "c1": ["contradiction"],  # literal-free -> always train
    }
    assign, held = literal_holdout_split(tactics)
    # at least one A theorem held out, schema retained in train
    assert held, "expected some literal-bearing theorem held out"
    train = {t for t, s in assign.items() if s == "train"}
    test = {t for t, s in assign.items() if s == "test"}
    # the held theorems are exactly `test`
    assert set(held) == test
    # literal-free theorems are never held out
    assert {"b1", "c1"} <= train
    # schema `exact h <num>` still present in train (>=1 A theorem trains)
    assert any(t.startswith("a") for t in train)
    # invariant: each held literal is absent from every train tactic
    import re
    num = re.compile(r"(?<![\w.])\d+(?!\w)")
    train_lits = {m.group(0) for t in train for tac in tactics[t] for m in num.finditer(tac)}
    for thm, lits in held.items():
        assert not (set(lits) & train_lits)


def test_literal_holdout_no_literals_means_no_holdout():
    assign, held = literal_holdout_split({"a1": ["rfl"], "a2": ["contradiction"]})
    assert held == {}
    assert all(s == "train" for s in assign.values())
