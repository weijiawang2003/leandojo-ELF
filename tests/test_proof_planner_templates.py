"""Mini-ELF v3 proof-planner — template / candidate-generation tests (Part 3).

Pure-Python: no torch, no Lean. Checks the planner emits the expected structured
proof-block strings (alpha-renamed binders are fine — these are the *verified*
shapes, confirmed against lean-cli in `scripts/run_mini_elf_v3_eval.sh`), with
correct source labels, deduplicated, and that ∃-goals are deferred to the
witness-copy augmenter."""

from __future__ import annotations

from mini_elf_lean.proof_planner import (
    PLANNER_CASES,
    PLANNER_CHAIN,
    PLANNER_EQ,
    PLANNER_IFF,
    PLANNER_PROJECTION,
    PLANNER_TEMPLATE,
    plan_candidates,
)


def _state(*lines):
    return "\n".join(lines)


def _by_tactic(stmt, state):
    return {c.tactic: c.source for c in plan_candidates(stmt, state)}


def test_implication_chain_three_steps():
    cands = _by_tactic(
        "(p q r s : Prop) (h1 : p → q) (h2 : q → r) (h3 : r → s) : p → s",
        _state("p q r s : Prop", "h1 : p → q", "h2 : q → r", "h3 : r → s", "⊢ p → s"),
    )
    assert "intro ha\n  exact h3 (h2 (h1 ha))" in cands
    assert "exact fun ha => h3 (h2 (h1 ha))" in cands
    assert cands["intro ha\n  exact h3 (h2 (h1 ha))"] == PLANNER_CHAIN


def test_uncurry_builds_anonymous_constructor_argument():
    cands = _by_tactic(
        "(p q r : Prop) (h : p ∧ q → r) : p → q → r",
        _state("p q r : Prop", "h : p ∧ q → r", "⊢ p → q → r"),
    )
    # corpus convention: `h ⟨ha, hb⟩` (no outer parens around the ⟨⟩ group)
    assert "intro ha hb\n  exact h ⟨ha, hb⟩" in cands
    assert "exact fun ha hb => h ⟨ha, hb⟩" in cands


def test_imp_chain_mixed_uses_conjunction_projection():
    cands = _by_tactic(
        "(p q r t : Prop) (h1 : p → q) (h2 : q → r) (h3 : p ∧ t) : r",
        _state("p q r t : Prop", "h1 : p → q", "h2 : q → r", "h3 : p ∧ t", "⊢ r"),
    )
    assert "exact h2 (h1 h3.1)" in cands
    assert "exact h2 (h1 h3.left)" in cands
    assert cands["exact h2 (h1 h3.1)"] == PLANNER_CHAIN


def test_nested_conjunction_projection_right_assoc():
    cands = _by_tactic(
        "(p q r : Prop) (h : p ∧ q ∧ r) : r",
        _state("p q r : Prop", "h : p ∧ q ∧ r", "⊢ r"),
    )
    assert "exact h.2.2" in cands and "exact h.right.right" in cands
    assert cands["exact h.2.2"] == PLANNER_PROJECTION
    # and the middle conjunct
    mid = _by_tactic("(p q r : Prop) (h : p ∧ q ∧ r) : q",
                     _state("p q r : Prop", "h : p ∧ q ∧ r", "⊢ q"))
    assert "exact h.2.1" in mid and "exact h.right.left" in mid


def test_nested_conjunction_projection_left_assoc():
    cands = _by_tactic(
        "(p q r : Prop) (h : (p ∧ q) ∧ r) : p",
        _state("p q r : Prop", "h : (p ∧ q) ∧ r", "⊢ p"),
    )
    assert "exact h.1.1" in cands and "exact h.left.left" in cands


def test_and_introduction_nested_and_constructor():
    cands = _by_tactic(
        "(p q r : Prop) (hp : p) (hq : q) (hr : r) : p ∧ r",
        _state("p q r : Prop", "hp : p", "hq : q", "hr : r", "⊢ p ∧ r"),
    )
    assert "exact ⟨hp, hr⟩" in cands
    assert "constructor\n  exact hp\n  exact hr" in cands
    assert cands["exact ⟨hp, hr⟩"] == PLANNER_TEMPLATE
    # left-nested goal -> structurally-exact nested constructor (flat is wrong here)
    ll = _by_tactic("(p q r : Prop) (hp : p) (hq : q) (hr : r) : (p ∧ q) ∧ r",
                    _state("p q r : Prop", "hp : p", "hq : q", "hr : r", "⊢ (p ∧ q) ∧ r"))
    assert "exact ⟨⟨hp, hq⟩, hr⟩" in ll
    assert "exact ⟨hp, hq, hr⟩" not in ll  # flat form is NOT valid for (p∧q)∧r


def test_or_elimination_case_split():
    cands = _by_tactic(
        "(p q r : Prop) (h : p ∨ q) (hp : p → r) (hq : q → r) : r",
        _state("p q r : Prop", "h : p ∨ q", "hp : p → r", "hq : q → r", "⊢ r"),
    )
    assert "cases h with\n  | inl hx => exact hp hx\n  | inr hx => exact hq hx" in cands
    assert "rcases h with hx | hx\n  exact hp hx\n  exact hq hx" in cands
    assert "exact Or.elim h hp hq" in cands
    assert cands["cases h with\n  | inl hx => exact hp hx\n  | inr hx => exact hq hx"] == PLANNER_CASES


def test_or_self_elimination():
    cands = _by_tactic("(p : Prop) (h : p ∨ p) : p", _state("p : Prop", "h : p ∨ p", "⊢ p"))
    assert "cases h with\n  | inl hx => exact hx\n  | inr hx => exact hx" in cands


def test_iff_direction_chain_and_flip():
    chain = _by_tactic(
        "(p q r : Prop) (h1 : p ↔ q) (h2 : q ↔ r) : p → r",
        _state("p q r : Prop", "h1 : p ↔ q", "h2 : q ↔ r", "⊢ p → r"),
    )
    assert "intro ha\n  exact h2.mp (h1.mp ha)" in chain
    assert chain["intro ha\n  exact h2.mp (h1.mp ha)"] == PLANNER_IFF

    flip = _by_tactic("(p q : Prop) (h : p ↔ q) : q → p",
                      _state("p q : Prop", "h : p ↔ q", "⊢ q → p"))
    assert "intro ha\n  exact h.mpr ha" in flip

    apply = _by_tactic("(p q : Prop) (h : p ↔ q) (hp : p) : q",
                       _state("p q : Prop", "h : p ↔ q", "hp : p", "⊢ q"))
    assert "exact h.mp hp" in apply
    assert apply["exact h.mp hp"] == PLANNER_IFF


def test_equality_trans_and_symm_chains():
    chain = _by_tactic(
        "(a b c d : Nat) (h1 : a = b) (h2 : b = c) (h3 : c = d) : a = d",
        _state("a b c d : Nat", "h1 : a = b", "h2 : b = c", "h3 : c = d", "⊢ a = d"),
    )
    assert "exact h1.trans (h2.trans h3)" in chain
    assert "exact (h1.trans h2).trans h3" in chain
    assert chain["exact h1.trans (h2.trans h3)"] == PLANNER_EQ

    symm = _by_tactic("(a b c : Nat) (h1 : a = b) (h2 : c = b) : a = c",
                      _state("a b c : Nat", "h1 : a = b", "h2 : c = b", "⊢ a = c"))
    assert "exact h1.trans h2.symm" in symm


def test_exists_goal_is_deferred_to_witness_copy():
    assert plan_candidates(": ∃ n : Nat, n = 6", _state("⊢ ∃ n : Nat, n = 6")) == []


def test_candidates_are_deduplicated_and_ordered_by_priority():
    cands = plan_candidates(
        "(p q r : Prop) (h : p ∧ q ∧ r) : r",
        _state("p q r : Prop", "h : p ∧ q ∧ r", "⊢ r"),
    )
    tactics = [c.tactic for c in cands]
    assert len(tactics) == len(set(tactics))  # no duplicates
    # non-decreasing priority (the public ordering contract)
    assert all(cands[i].priority <= cands[i + 1].priority for i in range(len(cands) - 1))
