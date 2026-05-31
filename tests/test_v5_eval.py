"""V5 Part 7 — fusion baseline + split-strategy tests.

The fusion logic and the `family_interpolation` split are pure-Python (no torch,
no Lean). A torch-gated test confirms the v5 eval script wires the proposer-only
configs together."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from mini_elf_lean.baselines import Example
from mini_elf_lean.elf_v5_sample import MiniElfV5Baseline
from mini_elf_lean.proposer import ProposedCandidate, RetrievalProofBlockProposer
from mini_elf_lean.splits import assign_splits, family_disjoint

ROOT = Path(__file__).resolve().parents[1]


def _ex(name, stmt, state, tac, split="test"):
    return Example(theorem_name=name, theorem_statement=stmt, state_before=state, tactic=tac, split=split)


class _FakeV3:
    """Stand-in for MiniElfV3Baseline: returns pre-ranked symbolic + flow items
    without needing torch or a trained model."""

    mode = "v3(fake)"

    def ranked_candidates(self, example):
        return [
            {"tactic": "exact h.1", "source": "planner_projection", "reranker_score": 0.3, "sample_count": 0},
            {"tactic": "rfl", "source": "flow_decoder", "reranker_score": None, "sample_count": 5},
        ]


class _StubProposer(RetrievalProofBlockProposer):
    """Deterministic proposer for ordering tests."""

    def __init__(self, cands):
        super().__init__()
        self._cands = cands

    def propose(self, theorem_statement, state_before, *, theorem_name=None, pattern_family=None, max_candidates=10):
        return list(self._cands)[:max_candidates]


def test_tier_order_symbolic_then_proposer_then_flow():
    prop = _StubProposer([ProposedCandidate("rw [h]", "retrieval", 0.9, {"a": 1})])
    b = MiniElfV5Baseline(v3=_FakeV3(), proposers=[prop])
    ex = _ex("t", "(p:Prop)(h:p):p", "p : Prop\nh : p\n⊢ p", "exact h.1")
    preds = b.predict(ex, k=5)
    assert preds == ["exact h.1", "rw [h]", "rfl"]  # planner, then proposer, then flow tail


def test_dedup_first_source_wins_across_tiers():
    # proposer re-proposes a symbolic tactic; the symbolic (earlier) tier keeps it.
    prop = _StubProposer([ProposedCandidate("exact h.1", "retrieval", 0.9)])
    b = MiniElfV5Baseline(v3=_FakeV3(), proposers=[prop])
    ex = _ex("t", "(p:Prop)(h:p):p", "p : Prop\nh : p\n⊢ p", "exact h.1")
    _, prov = b.predict_with_neighbors(ex, k=5)
    by_tac = {p: pv["source"] for p, pv in zip(b.predict(ex, k=5), prov)}
    assert by_tac["exact h.1"] == "planner_projection"


def test_retrieval_alone_no_v3():
    prop = _StubProposer([ProposedCandidate("rw [h]", "retrieval", 0.9)])
    b = MiniElfV5Baseline(v3=None, proposers=[prop])
    ex = _ex("t", "(a b:Nat)(h:a=b):a.succ=b.succ", "a b : Nat\nh : a = b\n⊢ a.succ = b.succ", "rw [h]")
    assert b.predict(ex, k=5) == ["rw [h]"]
    assert b.proposer_candidate_count(ex) == 1


def test_provenance_carries_source_and_score():
    prop = _StubProposer([ProposedCandidate("rw [h]", "retrieval", 0.9, {"adaptation": "numeric"})])
    b = MiniElfV5Baseline(v3=None, proposers=[prop])
    ex = _ex("t", "s", "state", "rw [h]")
    _, prov = b.predict_with_neighbors(ex, k=5)
    assert prov[0]["source"] == "retrieval" and prov[0]["score"] == 0.9
    assert prov[0]["strategy"] == "numeric"


def test_family_interpolation_split_gives_both_per_family():
    fams = {"fam_a": 6, "fam_b": 4}
    meta = {}
    for fam, k in fams.items():
        for i in range(k):
            meta[f"{fam}_{i}"] = {"pattern_family": fam}
    split = assign_splits(meta.keys(), meta, "family_interpolation",
                          train=0.5, val=0.0, test=0.5, seed=42)
    assert set(split.values()) <= {"train", "test"}  # val empty
    for fam in fams:
        members = [split[n] for n in meta if n.startswith(fam)]
        assert "train" in members and "test" in members
    # by design families span both splits (this is interpolation, not holdout)
    assert family_disjoint(split, meta) is False


def test_family_interpolation_singleton_to_test():
    meta = {"solo_0": {"pattern_family": "solo"}}
    split = assign_splits(meta.keys(), meta, "family_interpolation", seed=1)
    assert split["solo_0"] == "test"


@pytest.mark.parametrize("config", ["retrieval", "retrieval_verbatim", "llm"])
def test_v5_eval_script_builds_proposer_configs(config):
    pytest.importorskip("torch")  # the eval script imports the v3 baseline (torch)
    sys.path.insert(0, str(ROOT / "scripts"))
    import argparse
    import evaluate_mini_elf_v5 as ev

    args = argparse.Namespace(
        config=config, retrieval_neighbors=24, llm_backend="auto", llm_model=None,
        learned_model_dir=None, learned_beam=8, model_dir=None,
        n_samples=4, flow_steps=2, seed=0, planner_max=24,
    )
    baseline = ev.build_baseline(args)
    assert baseline.v3 is None  # proposer-only configs never load v3
    assert config in ev.CONFIGS
