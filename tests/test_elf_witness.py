"""Mini-ELF v1 — witness-copy augmentation. Pure-Python, no torch, no Lean."""

from __future__ import annotations

from pathlib import Path

from mini_elf_lean.elf_structure import parse_prompt, parse_tactic_state_text
from mini_elf_lean.elf_witness import (
    WITNESS_SOURCE,
    collect_witnesses,
    generate_witness_candidates,
    witness_candidates_for,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "mini_elf_lean"


def test_numeric_witness_from_exists_nat_5():
    cands = witness_candidates_for(": ∃ n : Nat, n = 5", "⊢ ∃ n : Nat, n = 5")
    assert "exact ⟨5, rfl⟩" in cands
    assert "refine ⟨5, ?_⟩\n  rfl" in cands


def test_numeric_witness_from_exists_nat_7():
    cands = witness_candidates_for(": ∃ n : Nat, n = 7", "⊢ ∃ n : Nat, n = 7")
    assert "exact ⟨7, rfl⟩" in cands


def test_no_witness_for_non_exists_goal():
    # and_elim goal: ⊢ p with h : p ∧ q -> no witness candidates.
    cands = witness_candidates_for("(p q : Prop) (h : p ∧ q) : p", "p q : Prop\nh : p ∧ q\n⊢ p")
    assert cands == []


def test_no_witness_for_implication():
    cands = witness_candidates_for("(p : Prop) : p → p", "p : Prop\n⊢ p → p")
    assert cands == []


def test_value_identifier_witness_for_exists_self():
    cands = witness_candidates_for("(α : Type) (a : α) : ∃ x : α, x = a", "α : Type\na : α\n⊢ ∃ x : α, x = a")
    assert "exact ⟨a, rfl⟩" in cands


def test_nat_default_fallback_when_no_literal():
    # ∃ n : Nat, n = n has no literal; fall back to 0/1 defaults.
    cands = witness_candidates_for(": ∃ n : Nat, n = n", "⊢ ∃ n : Nat, n = n")
    assert "exact ⟨0, rfl⟩" in cands


def test_candidates_are_deduplicated():
    cands = witness_candidates_for(": ∃ n : Nat, n = 5", "⊢ ∃ n : Nat, n = 5")
    assert len(cands) == len(set(cands))


def test_deterministic_order():
    a = witness_candidates_for(": ∃ n : Nat, n = 5", "⊢ ∃ n : Nat, n = 5")
    b = witness_candidates_for(": ∃ n : Nat, n = 5", "⊢ ∃ n : Nat, n = 5")
    assert a == b


def test_family_hint_triggers_even_without_exists_symbol():
    # If the goal parse misses the binder but the family says exists_witness,
    # numeric literals should still produce witnesses.
    state = parse_tactic_state_text("⊢ Exists fun n => n = 3", theorem_statement=": Exists ...3")
    cands = generate_witness_candidates(state, family="exists_witness")
    assert "exact ⟨3, rfl⟩" in cands


def test_source_label_constant():
    assert WITNESS_SOURCE == "witness_copy"


def test_collect_witnesses_caps_count():
    many = ": ∃ n : Nat, " + " ".join(f"n = {i}" for i in range(20))
    state = parse_prompt(many, "⊢ ∃ n : Nat, n = 0")
    assert len(collect_witnesses(state)) <= 6


def test_witness_module_never_accesses_state_after():
    text = (SRC / "elf_witness.py").read_text(encoding="utf-8")
    for pat in (".state_after", '["state_after"]', "['state_after']",
                'get("state_after"', "get('state_after'"):
        assert pat not in text
