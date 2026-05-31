"""Unit tests for the v7 donor-availability audit (pure logic; no Lean)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from mini_elf_lean.baselines import Example, oracle_verified_lookup  # noqa: E402
from audit_retrieval_donors import (  # noqa: E402
    compute_donor_conditions,
    operation_map,
    train_facts,
)

# Tiny synthetic corpus: a forall family (literal-bearing) + a neg family.
TRAIN = [
    Example("forall_a", "(h : ∀ n, f n = n) : f 3 = 3", "h : ∀ n, f n = n\n⊢ f 3 = 3", "exact h 3", "train"),
    Example("forall_b", "(h : ∀ n, f n = n) : f 5 = 5", "h : ∀ n, f n = n\n⊢ f 5 = 5", "exact h 5", "train"),
    Example("neg_a", "(hp : p) (hnp : ¬p) : q", "hp : p\nhnp : ¬p\n⊢ q", "exact absurd hp hnp", "train"),
]
TEST = [
    # same family present, but literal 9 unseen -> numeric adaptation needed
    Example("forall_c", "(h : ∀ n, f n = n) : f 9 = 9", "h : ∀ n, f n = n\n⊢ f 9 = 9", "exact h 9", "test"),
    # neg family present, exact tactic also in train -> no adaptation needed
    Example("neg_b", "(hp : p) (hnp : ¬p) : q", "hp : p\nhnp : ¬p\n⊢ q", "exact absurd hp hnp", "test"),
]
FAM = {"forall_a": "forall_inst", "forall_b": "forall_inst", "forall_c": "forall_inst",
       "neg_a": "neg_exfalso", "neg_b": "neg_exfalso"}


def _conditions():
    rows = TRAIN + TEST
    thm2op = operation_map(rows)
    oracle = oracle_verified_lookup(rows)
    return compute_donor_conditions(TRAIN, TEST, FAM, thm2op, oracle), thm2op


def test_same_family_donor_detected():
    conds, _ = _conditions()
    by = {c["theorem_name"]: c for c in conds}
    assert by["forall_c"]["same_family_donor_in_train"] is True
    assert by["neg_b"]["same_family_donor_in_train"] is True


def test_operation_inferred_for_forall_and_neg():
    _, thm2op = _conditions()
    assert thm2op["forall_a"] == "instantiate_forall"
    assert thm2op["neg_a"] == "contradiction"


def test_numeric_adaptation_needed_only_for_unseen_literal():
    conds, _ = _conditions()
    by = {c["theorem_name"]: c for c in conds}
    # forall_c needs `exact h 9`, absent from train (which has h 3 / h 5) -> adapt
    assert by["forall_c"]["numeric_adaptation_needed"] is True
    # neg_b's exact tactic `exact absurd hp hnp` IS in train verbatim -> no adapt
    assert by["neg_b"]["numeric_adaptation_needed"] is False


def test_schema_in_train_true_when_skeleton_present():
    conds, _ = _conditions()
    by = {c["theorem_name"]: c for c in conds}
    # `exact h <num>` schema present in train via forall_a/forall_b
    assert by["forall_c"]["schema_in_train"] is True


def test_train_facts_collects_families_ops_schemas():
    thm2op = operation_map(TRAIN + TEST)
    tf = train_facts(TRAIN, FAM, thm2op)
    assert "forall_inst" in tf.families and "neg_exfalso" in tf.families
    assert "instantiate_forall" in tf.operations
    assert "exact h 3" in tf.tactics
