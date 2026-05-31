"""Tests for :mod:`mini_elf_lean.v8_fusion`."""

from __future__ import annotations

from typing import List, Optional

import pytest

from mini_elf_lean.proposer import CandidateProposer, ProposedCandidate
from mini_elf_lean.v8_fusion import (
    DONOR_AVAILABLE_PRIORITY,
    DONORLESS_PRIORITY,
    family_in_pool,
    fuse,
)


class FakeProposer(CandidateProposer):
    def __init__(self, source: str, tactics, name: str = "fake"):
        self._source = source
        self._tactics = tactics
        self.name = name

    def available(self) -> bool:
        return True

    def propose(self, theorem_statement, state_before, *, theorem_name=None,
                pattern_family=None, max_candidates=10, **kw):
        return [ProposedCandidate(tactic=t, source=self._source, score=None,
                                  metadata={"i": i})
                for i, t in enumerate(self._tactics[:max_candidates])]


def test_priority_tables_distinct():
    assert DONOR_AVAILABLE_PRIORITY[0] != DONORLESS_PRIORITY[0]
    assert "proof_block_seq2seq" in DONOR_AVAILABLE_PRIORITY
    assert "proof_block_seq2seq" in DONORLESS_PRIORITY


def test_donor_available_prefers_retrieval():
    retr = FakeProposer("retrieval_v7_abstract", ["exact h", "rfl"])
    s2s  = FakeProposer("proof_block_seq2seq",   ["exact absurd hp hnp", "contradiction"])
    res = fuse([retr, s2s], "stmt", "⊢ goal", donor_available=True, top_k=4)
    # Retrieval candidates ranked above seq2seq
    sources = [c.source for c in res.candidates]
    assert sources[0] == "retrieval_v7_abstract"
    assert "proof_block_seq2seq" in sources


def test_donorless_prefers_seq2seq():
    retr = FakeProposer("retrieval_v7_abstract", ["exact h", "rfl"])
    s2s  = FakeProposer("proof_block_seq2seq",   ["exact absurd hp hnp", "contradiction"])
    res = fuse([retr, s2s], "stmt", "⊢ goal", donor_available=False, top_k=4)
    sources = [c.source for c in res.candidates]
    assert sources[0] == "proof_block_seq2seq"


def test_dedup_and_cleaner_apply():
    retr = FakeProposer("retrieval", ["exact h", "exact h"])
    s2s  = FakeProposer("proof_block_seq2seq", ["```lean\nexact h\n```", "rfl"])
    res = fuse([retr, s2s], "stmt", "⊢ goal", donor_available=True, top_k=10)
    tacs = [c.tactic for c in res.candidates]
    assert tacs.count("exact h") == 1
    assert "rfl" in tacs
    # No state_after artifacts get through
    assert all("state_after" not in t for t in tacs)


def test_unavailable_proposer_skipped():
    class UnavailableProposer(FakeProposer):
        def available(self):  # noqa: D401
            return False
    a = UnavailableProposer("llm_proposer", ["should not be used"])
    b = FakeProposer("proof_block_seq2seq", ["exact h"])
    res = fuse([a, b], "stmt", "⊢ goal", donor_available=True, top_k=5)
    assert all(c.source != "llm_proposer" for c in res.candidates)
    assert any(c.source == "proof_block_seq2seq" for c in res.candidates)


def test_family_in_pool():
    assert family_in_pool("neg_exfalso", {"neg_exfalso", "forall_inst"}) is True
    assert family_in_pool("neg_exfalso", {"forall_inst"}) is False
    assert family_in_pool(None, {"neg_exfalso"}) is False
