"""V4 — optional template-extension ablation tests (Part 5/7).

Pure-Python: no torch, no Lean. Checks the explicitly-labelled v4 template
families (`planner_negation`, `planner_exists_elim`) produce the expected
Lean-verified shapes, carry the right source labels, are *off by default*, and
wire into the v3 fusion baseline only when their flags are set."""

from __future__ import annotations

from mini_elf_lean.proof_planner_v4 import (
    PLANNER_EXISTS_ELIM,
    PLANNER_NEGATION,
    exists_elim_candidates,
    negation_candidates,
    v4_extra_candidates,
)
from mini_elf_lean.proof_planner import parse_planner_state
from mini_elf_lean.baselines import Example
from mini_elf_lean.elf_v3_sample import MiniElfV3Baseline


def _state(*lines):
    return "\n".join(lines)


def _by_tactic(stmt, state, **kw):
    return {c.tactic: c.source for c in v4_extra_candidates(stmt, state, **kw)}


def test_disabled_by_default():
    assert v4_extra_candidates("(p q : Prop) (hp : p) (hnp : ¬p) : q",
                               _state("p q : Prop", "hp : p", "hnp : ¬p", "⊢ q")) == []


def test_negation_exfalso_templates():
    c = _by_tactic("(p q : Prop) (hp : p) (hnp : ¬p) : q",
                   _state("p q : Prop", "hp : p", "hnp : ¬p", "⊢ q"),
                   enable_negation=True)
    assert "contradiction" in c
    assert "exact absurd hp hnp" in c
    assert "exact (hnp hp).elim" in c
    assert all(v == PLANNER_NEGATION for v in c.values())


def test_negation_contrapositive_template():
    c = _by_tactic("(p q : Prop) (h : p → q) (hnq : ¬q) : ¬p",
                   _state("p q : Prop", "h : p → q", "hnq : ¬q", "⊢ ¬p"),
                   enable_negation=True)
    assert "intro ha\n  exact hnq (h ha)" in c


def test_negation_imp_exfalso_template():
    c = _by_tactic("(p q : Prop) (hnp : ¬p) : p → q",
                   _state("p q : Prop", "hnp : ¬p", "⊢ p → q"),
                   enable_negation=True)
    assert "intro ha\n  exact (hnp ha).elim" in c or "intro ha\n  exact absurd ha hnp" in c


def test_negation_or_cases_template():
    c = _by_tactic("(p q : Prop) (h : p ∨ q) (hnp : ¬p) : q",
                   _state("p q : Prop", "h : p ∨ q", "hnp : ¬p", "⊢ q"),
                   enable_negation=True)
    assert "cases h with\n  | inl hx => exact (hnp hx).elim\n  | inr hx => exact hx" in c


def test_exists_elim_prop_template():
    c = _by_tactic("(p : Prop) (h : ∃ _ : Nat, p) : p",
                   _state("p : Prop", "h : ∃ _ : Nat, p", "⊢ p"),
                   enable_exists_elim=True)
    assert "rcases h with ⟨ha, hb⟩\n  exact hb" in c
    assert "obtain ⟨ha, hb⟩ := h\n  exact hb" in c
    assert all(v == PLANNER_EXISTS_ELIM for v in c.values())


def test_exists_elim_conj_projects_body_not_misparsed_hyp():
    st = parse_planner_state("(p q : Prop) (h : ∃ _ : Nat, p ∧ q) : q",
                             _state("p q : Prop", "h : ∃ _ : Nat, p ∧ q", "⊢ q"))
    tactics = {c.tactic for c in exists_elim_candidates(st)}
    # must project the destructured body (hb.2), NOT the mis-parsed ∃-hyp (h.2)
    assert "rcases h with ⟨ha, hb⟩\n  exact hb.2" in tactics
    assert "rcases h with ⟨ha, hb⟩\n  exact h.2" not in tactics


def test_negation_candidates_directly():
    st = parse_planner_state("(p : Prop) (hp : p) : ¬¬p",
                             _state("p : Prop", "hp : p", "⊢ ¬¬p"))
    tactics = {c.tactic for c in negation_candidates(st)}
    assert "intro ha\n  exact ha hp" in tactics


class _FakeV2:
    decode = "decoder"; rerank_pool = 16; rerank_blend = 0.15; n_samples = 4
    use_witness = False; use_reranker = False; reranker = None
    mode = "fake_v2"

    def _flow_candidates(self, stmt, state):
        return [("garbo", 1)]

    def distinct_flow_candidates(self, e):
        return 1


def test_baseline_flags_inject_v4_sources():
    ex = Example("t", "(p q : Prop) (hp : p) (hnp : ¬p) : q",
                 _state("p q : Prop", "hp : p", "hnp : ¬p", "⊢ q"), "contradiction", "test")
    off = MiniElfV3Baseline(_FakeV2())
    on = MiniElfV3Baseline(_FakeV2(), enable_negation_templates=True)
    off_sources = {it["source"] for it in off.ranked_candidates(ex)}
    on_sources = {it["source"] for it in on.ranked_candidates(ex)}
    assert PLANNER_NEGATION not in off_sources
    assert PLANNER_NEGATION in on_sources
    # the negation template should also lead (tier-0) over the flow garbage
    ranked = on.ranked_candidates(ex)
    assert ranked[0]["source"] == PLANNER_NEGATION


def test_mode_string_marks_enabled_templates():
    b = MiniElfV3Baseline(_FakeV2(), enable_negation_templates=True, enable_exists_elim_templates=True)
    assert "v4_negation" in b.mode and "v4_exists_elim" in b.mode
