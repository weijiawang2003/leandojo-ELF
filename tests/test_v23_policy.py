"""Tests for the v23 conservative rerank policy (Part 7)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.v23_rerank_policy import apply_policy, hybrid_order  # noqa: E402
from mini_elf_lean.learned_reranker import TrainConfig  # noqa: E402
from mini_elf_lean.v23_learned_reranker import train_v23_reranker  # noqa: E402

NEG_STATE = "p : Prop\nh : p → False\n⊢ ¬p"


def test_hybrid_preserves_order_within_bucket():
    # near-tie probabilities (within 0.1) keep the raw beam order.
    probs = [0.55, 0.52, 0.90]
    order = hybrid_order(probs, [0, 1, 2])
    assert order[0] == 2          # clearly-higher prob promoted
    assert order[1:] == [0, 1]    # the near-tie pair keeps beam order


def test_hybrid_does_not_reorder_uniform():
    probs = [0.5, 0.5, 0.5]
    assert hybrid_order(probs, [0, 1, 2]) == [0, 1, 2]


def test_apply_policy_raw_choice_is_identity():
    cands = [{"candidate": "a", "category": "negation", "beam_rank": 0,
              "state_before": NEG_STATE, "theorem_name": "x"},
             {"candidate": "b", "category": "negation", "beam_rank": 1,
              "state_before": NEG_STATE, "theorem_name": "x"}]
    m = train_v23_reranker(
        [{"theorem_name": "t", "category": "negation", "candidate": "exact h",
          "state_before": NEG_STATE, "beam_rank": 0, "candidate_source": "s",
          "required_operation": "intro_negation", "verified": True}],
        cfg=TrainConfig(epochs=5))
    order = apply_policy(cands, m, per_category_choice={"negation": "raw"})
    assert order == [0, 1]


def test_apply_policy_empty():
    m = train_v23_reranker(
        [{"theorem_name": "t", "category": "negation", "candidate": "exact h",
          "state_before": NEG_STATE, "beam_rank": 0, "candidate_source": "s",
          "required_operation": "intro_negation", "verified": True}],
        cfg=TrainConfig(epochs=5))
    assert apply_policy([], m) == []
