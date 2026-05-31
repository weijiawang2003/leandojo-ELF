"""Mini-ELF v3 proof-planner — parser unit tests (Part 2).

Pure-Python: no torch, no Lean. Exercises the heuristic typed-hypothesis / goal
parser on every hard-corpus shape (implication chains, nested conjunction,
disjunction, iff, equality, exists) and the no-``state_after`` guard."""

from __future__ import annotations

from pathlib import Path

from mini_elf_lean.proof_planner import parse_planner_state

SRC = Path(__file__).resolve().parents[1] / "src" / "mini_elf_lean"


def _state(*lines):
    return "\n".join(lines)


def test_parse_implication_chain_hypotheses():
    st = parse_planner_state(
        "(p q r s : Prop) (h1 : p → q) (h2 : q → r) (h3 : r → s) : p → s",
        _state("p q r s : Prop", "h1 : p → q", "h2 : q → r", "h3 : r → s", "⊢ p → s"),
    )
    assert st.declared_props == frozenset({"p", "q", "r", "s"})
    assert [h.name for h in st.imp_hyps] == ["h1", "h2", "h3"]
    assert st.imp_hyps[0].parts == ("p", "q")
    assert st.imp_hyps[2].parts == ("r", "s")
    assert st.goal == "p → s"
    assert st.goal_shape == "implication_goal"


def test_parse_uncurry_conjunction_antecedent():
    st = parse_planner_state(
        "(p q r : Prop) (h : p ∧ q → r) : p → q → r",
        _state("p q r : Prop", "h : p ∧ q → r", "⊢ p → q → r"),
    )
    # top-level connective is →, antecedent is a conjunction
    assert len(st.imp_hyps) == 1
    ant, con = st.imp_hyps[0].parts
    assert ant == "p ∧ q" and con == "r"


def test_parse_nested_conjunction_right_and_left():
    right = parse_planner_state(
        "(p q r : Prop) (h : p ∧ q ∧ r) : r",
        _state("p q r : Prop", "h : p ∧ q ∧ r", "⊢ r"),
    )
    assert len(right.and_hyps) == 1
    lhs, rhs = right.and_hyps[0].parts
    assert lhs == "p" and rhs == "q ∧ r"  # right-assoc: p ∧ (q ∧ r)

    left = parse_planner_state(
        "(p q r : Prop) (h : (p ∧ q) ∧ r) : a",
        _state("p q r : Prop", "h : (p ∧ q) ∧ r", "⊢ p"),
    )
    lhs, rhs = left.and_hyps[0].parts
    assert lhs == "(p ∧ q)" and rhs == "r"


def test_parse_disjunction_and_case_hypotheses():
    st = parse_planner_state(
        "(p q r : Prop) (h : p ∨ q) (hp : p → r) (hq : q → r) : r",
        _state("p q r : Prop", "h : p ∨ q", "hp : p → r", "hq : q → r", "⊢ r"),
    )
    assert len(st.or_hyps) == 1
    assert st.or_hyps[0].parts == ("p", "q")
    # hp, hq are implication hypotheses available for the branches
    assert {h.name for h in st.imp_hyps} == {"hp", "hq"}


def test_parse_iff_hypotheses():
    st = parse_planner_state(
        "(p q r : Prop) (h1 : p ↔ q) (h2 : q ↔ r) : p → r",
        _state("p q r : Prop", "h1 : p ↔ q", "h2 : q ↔ r", "⊢ p → r"),
    )
    assert [h.name for h in st.iff_hyps] == ["h1", "h2"]
    assert st.iff_hyps[0].parts == ("p", "q")
    assert st.iff_hyps[1].parts == ("q", "r")


def test_parse_equality_hypotheses_and_value_vars():
    st = parse_planner_state(
        "(a b c d : Nat) (h1 : a = b) (h2 : b = c) (h3 : c = d) : a = d",
        _state("a b c d : Nat", "h1 : a = b", "h2 : b = c", "h3 : c = d", "⊢ a = d"),
    )
    # a,b,c,d are Nat values, not proof hypotheses
    assert set(st.value_vars) == {"a", "b", "c", "d"}
    assert all(t == "Nat" for t in st.value_vars.values())
    assert [h.name for h in st.eq_hyps] == ["h1", "h2", "h3"]
    assert st.eq_hyps[0].parts == ("a", "b")
    assert st.goal_shape == "equality_goal"


def test_parse_type_variable_then_values():
    st = parse_planner_state(
        "(α : Type) (a b c : α) (h1 : a = b) (h2 : c = b) : a = c",
        _state("α : Type", "a b c : α", "h1 : a = b", "h2 : c = b", "⊢ a = c"),
    )
    assert "α" in st.declared_types
    assert set(st.value_vars) == {"a", "b", "c"}
    assert len(st.eq_hyps) == 2


def test_parse_exists_goal_shape():
    st = parse_planner_state(": ∃ n : Nat, n = 6", _state("⊢ ∃ n : Nat, n = 6"))
    assert st.goal_shape == "exists_goal"
    assert st.hyps == []  # no hypotheses


def test_parse_atom_proof_hypothesis():
    st = parse_planner_state(
        "(p q r : Prop) (hp : p) (hq : q) (hr : r) : p ∧ r",
        _state("p q r : Prop", "hp : p", "hq : q", "hr : r", "⊢ p ∧ r"),
    )
    atoms = {h.name: h.type for h in st.hyps if h.kind == "atom"}
    assert atoms == {"hp": "p", "hq": "q", "hr": "r"}
    assert st.goal_shape == "and_goal"


def test_parser_never_reads_state_after():
    text = (SRC / "proof_planner.py").read_text(encoding="utf-8")
    for pat in (".state_after", '["state_after"]', "['state_after']",
                'get("state_after"', "get('state_after'"):
        assert pat not in text, f"proof_planner.py references {pat!r}"
