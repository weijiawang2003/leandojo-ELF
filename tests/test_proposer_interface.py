"""V5 Part 7 — candidate-proposer interface tests.

Pure-Python: no torch, no Lean, no API key. Checks the common interface produces
typed candidates, dedup preserves source provenance, ``max_candidates`` is
enforced, and none of the v5 proposer modules access ``state_after``."""

from __future__ import annotations

import re
from pathlib import Path

import mini_elf_lean.elf_v5_sample as elf_v5_sample
import mini_elf_lean.llm_proposer as llm_proposer
import mini_elf_lean.proposer as proposer_mod
import mini_elf_lean.retrieval_proposer as retrieval_proposer
from mini_elf_lean.proposer import (
    CandidateProposer,
    ManualCandidateProposer,
    PlannerProposer,
    ProposedCandidate,
    WitnessProposer,
    dedup_candidates,
)


def test_proposed_candidate_is_typed():
    c = ProposedCandidate(tactic="rw [h]", source="retrieval", score=0.9, metadata={"k": 1})
    assert isinstance(c.tactic, str) and isinstance(c.source, str)
    assert isinstance(c.metadata, dict) and c.score == 0.9
    # default metadata is an independent dict per instance
    a, b = ProposedCandidate("a", "s"), ProposedCandidate("b", "s")
    a.metadata["x"] = 1
    assert b.metadata == {}


def test_dedup_preserves_first_source():
    out = dedup_candidates([
        ProposedCandidate("rw [h]", "retrieval", 0.9, {"keep": True}),
        ProposedCandidate("rw [h]", "flow_decoder", 0.1, {}),
        ProposedCandidate("exact h", "retrieval", 0.5),
    ])
    assert [c.tactic for c in out] == ["rw [h]", "exact h"]
    assert out[0].source == "retrieval" and out[0].metadata.get("keep") is True


def test_planner_proposer_typed_and_capped():
    cands = PlannerProposer().propose(
        "(p q : Prop) (h : p ∧ q) : p", "p q : Prop\nh : p ∧ q\n⊢ p", max_candidates=2)
    assert 0 < len(cands) <= 2
    assert all(isinstance(c, ProposedCandidate) for c in cands)
    assert all(c.source.startswith("planner_") for c in cands)


def test_witness_proposer_fires_on_exists():
    cands = WitnessProposer().propose(
        "(h : ∃ n : Nat, n = 3) : ∃ m : Nat, m = 3",
        "h : ∃ n : Nat, n = 3\n⊢ ∃ m : Nat, m = 3", max_candidates=10)
    tacs = [c.tactic for c in cands]
    assert any("⟨3," in t for t in tacs)
    assert all(c.source == "witness_copy" for c in cands)


def test_witness_proposer_silent_on_non_exists():
    assert WitnessProposer().propose("(p : Prop) (hp : p) : p", "p : Prop\nhp : p\n⊢ p") == []


def test_manual_proposer_is_audit_only(tmp_path: Path):
    f = tmp_path / "manual.jsonl"
    f.write_text('{"theorem_name": "t1", "candidates": ["exact h", "rfl"]}\n', encoding="utf-8")
    m = ManualCandidateProposer(f)
    out = m.propose("(p:Prop)(h:p):p", "p : Prop\nh : p\n⊢ p", theorem_name="t1", max_candidates=1)
    assert len(out) == 1 and out[0].source == "manual_oracle"
    # no theorem_name -> nothing
    assert m.propose("x", "y") == []


def test_base_fit_is_noop():
    assert isinstance(CandidateProposer().fit([1, 2, 3]), CandidateProposer)


def test_no_state_after_access_in_v5_modules():
    """The proposer modules must never read state_after (only describe it)."""
    forbidden = [re.compile(p) for p in (
        r"\.state_after\b", r"""\[['"]state_after['"]\]""",
        r"""get\(\s*['"]state_after['"]""", r"""state_after\s*=""")]
    for mod in (proposer_mod, retrieval_proposer, llm_proposer, elf_v5_sample):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        for pat in forbidden:
            assert not pat.search(src), f"{mod.__name__} appears to access state_after: {pat.pattern}"
