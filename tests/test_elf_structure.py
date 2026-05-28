"""Mini-ELF v1 — structure-aware tactic-state parser. Pure-Python (no torch
needed for the parser); the optional StructuredConditionEncoder test is
torch-gated. No Lean."""

from __future__ import annotations

from pathlib import Path

import pytest

from mini_elf_lean.elf_structure import (
    AND_GOAL,
    EQUALITY_GOAL,
    EXISTS_GOAL,
    FALSE_GOAL,
    IFF_GOAL,
    IMPLICATION_GOAL,
    OR_GOAL,
    TRUE_GOAL,
    UNKNOWN_GOAL,
    classify_goal_shape,
    extract_goal_line,
    extract_hypotheses,
    extract_identifiers,
    extract_numeric_literals,
    parse_binding,
    parse_prompt,
    parse_tactic_state_text,
    split_binary,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "mini_elf_lean"


# ---------------- goal / hypothesis split ----------------


def test_parse_simple_imp_identity():
    st = parse_tactic_state_text("p : Prop\n⊢ p → p")
    assert st.goal == "p → p"
    assert st.hypotheses == ["p : Prop"]
    assert st.goal_shape == IMPLICATION_GOAL
    assert st.hyp_bindings == [(["p"], "Prop")]


def test_parse_hyp_p_goal_p():
    st = parse_tactic_state_text("p : Prop\nh : p\n⊢ p")
    assert st.hypotheses == ["p : Prop", "h : p"]
    assert st.goal == "p"
    assert st.goal_shape == UNKNOWN_GOAL  # bare atom


def test_and_elim_left_structure():
    # h : p ∧ q / ⊢ p  -> goal matches the LEFT conjunct of h.
    st = parse_tactic_state_text("p q : Prop\nh : p ∧ q\n⊢ p")
    assert st.goal == "p"
    assert st.conjunction_hyps == [("h", "p", "q")]
    name, lhs, rhs = st.conjunction_hyps[0]
    assert st.goal == lhs and st.goal != rhs  # left conjunct


def test_and_elim_right_structure():
    # h : p ∧ q / ⊢ q  -> goal matches the RIGHT conjunct of h.
    st = parse_tactic_state_text("p q : Prop\nh : p ∧ q\n⊢ q")
    name, lhs, rhs = st.conjunction_hyps[0]
    assert st.goal == rhs and st.goal != lhs  # right conjunct


def test_or_intro_goal_disjuncts():
    st = parse_tactic_state_text("p q : Prop\nh : p\n⊢ p ∨ q")
    assert st.goal_shape == OR_GOAL
    assert st.goal_disjuncts == ("p", "q")


# ---------------- goal-shape classification ----------------


@pytest.mark.parametrize(
    "goal,shape",
    [
        ("p ∧ q", AND_GOAL),
        ("p ∨ q", OR_GOAL),
        ("p ↔ q", IFF_GOAL),
        ("p → q", IMPLICATION_GOAL),
        ("a = b", EQUALITY_GOAL),
        ("∃ n : Nat, n = 5", EXISTS_GOAL),
        ("True", TRUE_GOAL),
        ("False", FALSE_GOAL),
        ("p", UNKNOWN_GOAL),
        ("(a ∧ b) → c", IMPLICATION_GOAL),  # top-level connective is →, not ∧
    ],
)
def test_classify_goal_shape(goal, shape):
    assert classify_goal_shape(goal) == shape


def test_exists_not_misread_as_equality():
    # `∃ n, n = 5` contains `=` but the top-level shape is the binder.
    assert classify_goal_shape("∃ n : Nat, n = 5") == EXISTS_GOAL


# ---------------- numeric / identifier extraction ----------------


def test_extract_numeric_literals_from_exists():
    st = parse_tactic_state_text("⊢ ∃ n : Nat, n = 5", theorem_statement=": ∃ n : Nat, n = 5")
    assert st.numeric_literals == ["5"]


def test_extract_numeric_literals_dedup_order():
    assert extract_numeric_literals("a 3 b 3 c 7 1") == ["3", "7", "1"]


def test_extract_numeric_literals_none_for_refl():
    assert extract_numeric_literals("∃ n : Nat, n = n") == []


def test_extract_identifiers_excludes_digits_and_dots():
    ids = extract_identifiers("exact Or.inl h 5")
    assert ids == ["exact", "Or", "inl", "h"]


# ---------------- helpers ----------------


def test_split_binary_depth_aware():
    assert split_binary("(a ∧ b) ∨ c", "∨") == ("(a ∧ b)", "c")
    assert split_binary("(a ∧ b) ∨ c", "∧") is None  # ∧ is nested, not depth-0


def test_parse_binding():
    assert parse_binding("p q : Prop") == (["p", "q"], "Prop")
    assert parse_binding("h : p ∧ q") == (["h"], "p ∧ q")
    assert parse_binding("not a binding") is None
    assert parse_binding("(p q : Prop) (h : p) : p") is None  # statement signature


def test_extract_goal_line_no_turnstile():
    assert extract_goal_line("p → p") == "p → p"


# ---------------- combined prompt robustness ----------------


def test_parse_prompt_excludes_statement_line():
    # The combined prompt prepends the statement; it must not become a hypothesis.
    st = parse_prompt("(p q : Prop) (h : p ∧ q) : p", "p q : Prop\nh : p ∧ q\n⊢ p")
    assert st.hypotheses == ["p q : Prop", "h : p ∧ q"]
    assert st.conjunction_hyps == [("h", "p", "q")]
    assert st.goal == "p"


def test_value_witnesses_for_exists_self():
    st = parse_tactic_state_text("α : Type\na : α\n⊢ ∃ x : α, x = a")
    # α is a Type binder (not a witness); a : α is a value witness.
    assert "a" in st.value_witnesses
    assert "α" not in st.value_witnesses


# ---------------- robustness ----------------


def test_no_crash_on_malformed_state():
    for bad in ["", "⊢", "⊢ ", "no turnstile here", "::: garbage :::", "\n\n⊢\n"]:
        st = parse_tactic_state_text(bad)
        assert isinstance(st.goal, str)
        assert isinstance(st.hypotheses, list)
        assert st.goal_shape in {
            AND_GOAL, OR_GOAL, IFF_GOAL, IMPLICATION_GOAL, EQUALITY_GOAL,
            EXISTS_GOAL, TRUE_GOAL, FALSE_GOAL, UNKNOWN_GOAL,
        }


def test_pattern_family_metadata_carried():
    st = parse_tactic_state_text("⊢ p", pattern_family="and_elim_left")
    assert st.pattern_family == "and_elim_left"


def test_structure_module_never_accesses_state_after():
    text = (SRC / "elf_structure.py").read_text(encoding="utf-8")
    for pat in (".state_after", '["state_after"]', "['state_after']",
                'get("state_after"', "get('state_after'"):
        assert pat not in text


# ---------------- torch-gated encoder ----------------


def test_structured_condition_encoder_forward():
    torch = pytest.importorskip("torch")
    from mini_elf_lean.elf_structure import StructuredConditionEncoder, NUMERIC_FEATURE_DIM

    enc = StructuredConditionEncoder(vocab_size=40, cond_dim=32, raw_hidden=16, goal_hidden=8)
    B = 3
    raw_src = torch.randint(1, 40, (B, 12))
    raw_len = torch.tensor([12, 10, 7])
    goal_src = torch.randint(1, 40, (B, 5))
    goal_len = torch.tensor([5, 4, 3])
    shape_idx = torch.tensor([0, 4, 8])
    num_feats = torch.zeros(B, NUMERIC_FEATURE_DIM)
    out = enc(raw_src, raw_len, goal_src, goal_len, shape_idx, num_feats)
    assert out.shape == (B, 32)
