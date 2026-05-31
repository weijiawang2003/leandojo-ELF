"""V6 Part 7 — structure-aware retrieval ranking tests.

Pure-Python: no torch, no Lean. Checks the structural scorer fixes the v5
ranking failures F2 (left/right), F3 (missing intro), F4 (wrong negation family),
and that the `no structural` ablation reverts to char-similarity behaviour."""

from __future__ import annotations

from mini_elf_lean.baselines import Example
from mini_elf_lean.proposer import ProposedCandidate
from mini_elf_lean.retrieval_proposer import (
    RetrievalProofBlockProposer,
    StructureAwareRetrievalProposer,
)


def _ex(name, stmt, state, tac):
    return Example(theorem_name=name, theorem_statement=stmt, state_before=state, tactic=tac, split="train")


DONORS = [
    # negation: ex-falso (contradiction) vs double-negation-intro (the F4 distractor)
    _ex("neg_exfalso_ab", "(a b : Prop) (hp : a) (hnp : ¬a) : b",
        "a b : Prop\nhp : a\nhnp : ¬a\n⊢ b", "exact absurd hp hnp"),
    _ex("neg_double_intro_q", "(q : Prop) (hp : q) : ¬¬q",
        "q : Prop\nhp : q\n⊢ ¬¬q", "exact fun hnp => hnp hp"),
    # neg implication (needs intro) — the F3 correct donor
    _ex("neg_imp_exfalso_ps", "(p s : Prop) (hnp : ¬p) : p → s",
        "p s : Prop\nhnp : ¬p\n⊢ p → s", "intro hp\n  exact absurd hp hnp"),
    # exists-elim conjunction: right (same vars as target → F2 distractor) and left
    _ex("exists_elim_conj_r_ab", "(a b : Prop) (h : ∃ _ : Nat, a ∧ b) : b",
        "a b : Prop\nh : ∃ _ : Nat, a ∧ b\n⊢ b", "exact hpq.2"),
    _ex("exists_elim_conj_l_ps", "(p s : Prop) (h : ∃ _ : Nat, p ∧ s) : p",
        "p s : Prop\nh : ∃ _ : Nat, p ∧ s\n⊢ p", "obtain ⟨n, hpq⟩ := h\n  exact hpq.1"),
]


def _v6(**kw):
    return StructureAwareRetrievalProposer(**kw).fit(DONORS)


def test_returns_structural_metadata():
    cands = _v6().propose("(a b : Prop) (hp : a) (hnp : ¬a) : b",
                          "a b : Prop\nhp : a\nhnp : ¬a\n⊢ b", theorem_name="t")
    assert cands and all(isinstance(c, ProposedCandidate) for c in cands)
    md = cands[0].metadata
    for k in ("char_score", "structural_score", "total_score", "donor_operation", "adapted"):
        assert k in md


def test_F4_prefers_contradiction_over_double_negation():
    # target neg_exfalso (goal q, atom + neg hyp) — char-sim picked neg_double_intro in v5.
    top = _v6().propose("(p q : Prop) (hp : p) (hnp : ¬p) : q",
                        "p q : Prop\nhp : p\nhnp : ¬p\n⊢ q", theorem_name="neg_exfalso_pq")[0]
    assert "fun hnp" not in top.tactic          # NOT the double-negation donor
    assert "absurd" in top.tactic or "contradiction" in top.tactic or "elim" in top.tactic


def test_F3_prefers_intro_for_implication_goal():
    top = _v6().propose("(a b : Prop) (hnp : ¬a) : a → b",
                        "a b : Prop\nhnp : ¬a\n⊢ a → b", theorem_name="neg_imp_exfalso_ab")[0]
    assert top.tactic.lstrip().startswith("intro") or "fun " in top.tactic


def test_F2_prefers_left_projection():
    top = _v6().propose("(a b : Prop) (h : ∃ _ : Nat, a ∧ b) : a",
                        "a b : Prop\nh : ∃ _ : Nat, a ∧ b\n⊢ a", theorem_name="exists_elim_conj_l_ab")[0]
    assert "hpq.2" not in top.tactic            # NOT the right-projection (same-var) donor
    assert ".1" in top.tactic or "hpq" in top.tactic


def test_no_structure_ablation_reverts():
    # with structural off, the same-variable right-projection donor wins F2 again.
    top = _v6(enable_structural=False).propose(
        "(a b : Prop) (h : ∃ _ : Nat, a ∧ b) : a",
        "a b : Prop\nh : ∃ _ : Nat, a ∧ b\n⊢ a", theorem_name="exists_elim_conj_l_ab")[0]
    assert "hpq.2" in top.tactic  # char-similarity confusion returns


def test_leakage_guard():
    cands = _v6().propose("(a b : Prop) (hp : a) (hnp : ¬a) : b",
                          "a b : Prop\nhp : a\nhnp : ¬a\n⊢ b", theorem_name="neg_exfalso_ab")
    assert all(c.metadata.get("neighbor_theorem") != "neg_exfalso_ab" for c in cands)


def test_empty_index():
    assert StructureAwareRetrievalProposer().fit([]).propose("x", "y") == []
