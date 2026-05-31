"""V4 — planner coverage audit tests (Part 1/7).

Pure-Python: no torch, no Lean. Confirms the audit's shape catalog correctly
separates planner-supported shapes from planner-blind ones, and that the
planner-blind families (negation, contrapositive, ∃-elim, ∀-inst, rewrite)
genuinely produce **zero** planner candidates."""

from __future__ import annotations

from scripts.audit_planner_coverage import SHAPE_PROBES, _shape_catalog
from mini_elf_lean.proof_planner import plan_candidates


def test_shape_catalog_separates_supported_from_blind():
    cat = {c["shape"]: c for c in _shape_catalog()}
    # supported shapes emit candidates
    assert cat["conjunction projection (nested)"]["planner_candidates"] > 0
    assert cat["implication chain"]["planner_candidates"] > 0
    assert cat["equality trans/symm chain"]["planner_candidates"] > 0
    assert cat["∨-elimination case split"]["planner_candidates"] > 0
    # blind shapes emit none
    for blind in ("negation: ¬p + p ⊢ q (ex falso)", "contrapositive ⊢ ¬p",
                  "∃-elimination (h : ∃ _, p ⊢ p)", "∀-instantiation (h : ∀ x, x = 0 ⊢ 7 = 0)",
                  "rewrite/substitution (h : n = m ⊢ n.succ = m.succ)",
                  "negation inside cases (h : p ∨ q, ¬p ⊢ q)"):
        assert cat[blind]["planner_candidates"] == 0, f"{blind} should be planner-blind"


def test_negation_goal_produces_no_planner_candidates():
    # ¬p + p ⊢ q : no rule in the planner constructs ex-falso
    cands = plan_candidates("(p q : Prop) (hp : p) (hnp : ¬p) : q",
                            "p q : Prop\nhp : p\nhnp : ¬p\n⊢ q")
    assert cands == []


def test_contrapositive_goal_produces_no_planner_candidates():
    cands = plan_candidates("(p q : Prop) (h : p → q) (hnq : ¬q) : ¬p",
                            "p q : Prop\nh : p → q\nhnq : ¬q\n⊢ ¬p")
    assert cands == []


def test_exists_elim_produces_no_planner_candidates():
    # ∃-elimination: the planner defers ∃-goals AND cannot use ∃-hyps as proofs
    cands = plan_candidates("(p : Prop) (h : ∃ _ : Nat, p) : p",
                            "p : Prop\nh : ∃ _ : Nat, p\n⊢ p")
    assert cands == []


def test_negation_in_cases_planner_cannot_complete_branch():
    # planner starts a case split but cannot prove the inl branch (needs ¬-elim)
    cands = plan_candidates("(p q : Prop) (h : p ∨ q) (hnp : ¬p) : q",
                            "p q : Prop\nh : p ∨ q\nhnp : ¬p\n⊢ q")
    assert cands == []


def test_probe_list_marks_expected_support():
    # the static probe table's expectations match the planner's actual behavior
    for name, expected_supported, stmt, state in SHAPE_PROBES:
        n = len(plan_candidates(stmt, state))
        if expected_supported:
            assert n > 0, f"{name} expected supported but planner emitted 0"
        else:
            assert n == 0, f"{name} expected blind but planner emitted {n}"
