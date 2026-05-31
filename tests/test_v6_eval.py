"""V6 Part 7 — v6 eval wiring + stats tests.

The fusion baseline with a structure-aware proposer is torch-free; a torch-gated
test confirms the eval script builds the retrieval-only configs."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from mini_elf_lean.baselines import Example
from mini_elf_lean.elf_v5_sample import MiniElfV5Baseline
from mini_elf_lean.retrieval_proposer import StructureAwareRetrievalProposer, load_v6_weights

ROOT = Path(__file__).resolve().parents[1]


def _ex(name, stmt, state, tac, split="train"):
    return Example(theorem_name=name, theorem_statement=stmt, state_before=state, tactic=tac, split=split)


def test_v6_proposer_in_fusion_baseline():
    donors = [_ex("forall_inst_7_0", "(h : ∀ x : Nat, x = 0) : 7 = 0",
                  "h : ∀ x : Nat, x = 0\n⊢ 7 = 0", "exact h 7")]
    b = MiniElfV5Baseline(v3=None, proposers=[StructureAwareRetrievalProposer().fit(donors)])
    b.fit(donors)
    ex = _ex("forall_inst_13_6", "(h : ∀ x : Nat, x = 6) : 13 = 6",
             "h : ∀ x : Nat, x = 6\n⊢ 13 = 6", "exact h 13", split="test")
    preds = b.predict(ex, k=5)
    assert "exact h 13" in preds


def test_load_v6_weights_defaults_and_override(tmp_path):
    w = load_v6_weights(None)
    assert "alpha_char" in w and "pen_stale_literal" in w
    f = tmp_path / "w.json"
    f.write_text('{"alpha_char": 9.0}', encoding="utf-8")
    w2 = load_v6_weights(f)
    assert w2["alpha_char"] == 9.0 and "beta_goal_shape" in w2  # merged with defaults


def test_v6_extra_stats_counts_adapted_top1():
    pytest.importorskip("torch")
    sys.path.insert(0, str(ROOT / "scripts"))
    import evaluate_mini_elf_v6 as ev

    predictions = [
        {  # adapted candidate verified at top-1
            "predictions": ["exact h 13", "exact h 3"],
            "prediction_provenance": [
                {"source": "retrieval_adapted", "metadata": {"adapted": True}},
                {"source": "retrieval", "metadata": {"adapted": False}},
            ],
            "lean_results": {"exact h 13": {"success": True}, "exact h 3": {"success": False}},
        },
        {  # verbatim verified at top-1
            "predictions": ["rw [h]"],
            "prediction_provenance": [{"source": "retrieval", "metadata": {"adapted": False}}],
            "lean_results": {"rw [h]": {"success": True}},
        },
    ]
    stats = ev._v6_extra_stats(predictions, verifier_used=True)
    assert stats["adapted_candidate_verified"] == 1
    assert stats["adapted_candidate_top1"] == 1
    assert stats["adapted_candidate_top1_verified"] == 1
    assert 0.0 < stats["adapted_candidate_top1_rate"] <= 1.0


@pytest.mark.parametrize("config", ["v5_retrieval", "v6_retrieval"])
def test_v6_eval_builds_retrieval_configs(config):
    pytest.importorskip("torch")
    sys.path.insert(0, str(ROOT / "scripts"))
    import argparse
    import evaluate_mini_elf_v6 as ev

    args = argparse.Namespace(
        config=config, retrieval_neighbors=24, model_dir=None,
        weights=ROOT / "data" / "configs" / "v6_retrieval.json",
        n_samples=4, flow_steps=2, seed=0, planner_max=24,
    )
    baseline = ev.build_baseline(args)
    assert baseline.v3 is None
    assert config in ev.CONFIGS
