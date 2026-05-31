"""Tests for ``scripts/extract_donorless_targets.py``'s pure-logic core.

The script's grouping table and audit row shape are pure Python; we exercise
both without touching the real data files.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "extract_donorless_targets.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("extract_donorless_targets", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    spec.loader.exec_module(mod)
    return mod


def test_group_for_known_families():
    m = _load_script_module()
    assert m.group_for("neg_exfalso") == "negation_contradiction"
    assert m.group_for("neg_imp_exfalso") == "negation_contradiction"
    assert m.group_for("neg_double_intro") == "negation_contradiction"
    assert m.group_for("neg_contrapositive") == "contrapositive"
    assert m.group_for("exists_elim_conj") == "exists_elim"
    assert m.group_for("exists_elim_prop") == "exists_elim"
    assert m.group_for("neg_or_cases") == "exists_elim"  # explicit map
    assert m.group_for("forall_inst") == "forall_inst"
    assert m.group_for("rewrite_succ") == "rewrite"
    assert m.group_for("exists_reconstruct") == "exists_reconstruct"


def test_group_for_unknown_falls_back():
    m = _load_script_module()
    assert m.group_for("zzz_not_a_family") == "other"
    assert m.group_for("") == "other"


def test_required_op_for_row_uses_state_only():
    """The op classifier feeds extract_features the same goal the v6/v7
    ranker sees — assert it never reads state_after."""
    m = _load_script_module()
    row = {
        "theorem_statement": "(p : Prop) (h : p → False) : ¬p",
        "state_before": "p : Prop\nh : p → False\n⊢ ¬p",
        "state_after": "<<<should never be read>>>",   # poison
    }
    op = m.required_op_for_row(row)
    assert isinstance(op, str)


def test_build_target_marks_donorless_for_family_holdout():
    m = _load_script_module()
    row = {
        "theorem_name": "neg_exfalso_pq",
        "theorem_statement": "(p q : Prop) (hp : p) (hnp : ¬p) : q",
        "state_before": "p q : Prop\nhp : p\nhnp : ¬p\n⊢ q",
        "metadata": {"pattern_family": "neg_exfalso"},
    }
    t = m.build_target(
        row, split_kind="family_holdout", held="neg_exfalso",
        train_families={"forall_inst", "neg_or_cases", "neg_imp_exfalso"},
        train_operations=set(),
        sibling_families={"neg_or_cases"},
        thm2tac={"neg_exfalso_pq": ["exact absurd hp hnp", "contradiction"]},
    )
    assert t["theorem_name"] == "neg_exfalso_pq"
    assert t["family"] == "neg_exfalso"
    assert t["group"] == "negation_contradiction"
    assert "neg_exfalso" not in t["available_donor_families"]
    assert "neg_or_cases" in t["same_operation_siblings_in_train"]
    assert t["has_manual_verified"] is True
    assert t["shortest_verified_tactic"] == "contradiction"  # shorter of two
    assert "no_same_family_donor" in t["why_retrieval_fails"]


def test_build_target_op_holdout_uses_op_reason():
    m = _load_script_module()
    row = {
        "theorem_name": "rewrite_one",
        "theorem_statement": "(n : Nat) (h : n = 3) : n + 0 = 3",
        "state_before": "n : Nat\nh : n = 3\n⊢ n + 0 = 3",
        "metadata": {"pattern_family": "rewrite_succ"},
    }
    t = m.build_target(
        row, split_kind="operation_holdout", held="rewrite",
        train_families={"neg_exfalso", "forall_inst"}, train_operations=set(),
        sibling_families=set(), thm2tac={},
    )
    assert "no_same_operation_donor" in t["why_retrieval_fails"]
    assert t["has_manual_verified"] is False
    assert t["shortest_verified_tactic"] is None
