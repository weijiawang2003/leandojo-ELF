"""Tests for the v23 learned reranker (Part 3)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.learned_reranker import TrainConfig  # noqa: E402
from mini_elf_lean.v23_learned_reranker import (  # noqa: E402
    build_pattern_bag_from_rows, order_by_score, train_v23_reranker,
)

NEG_STATE = "p : Prop\nh : p → False\n⊢ ¬p"


def _toy_rows():
    # tiny synthetic dataset: grounded+absurd verifies, unbound fails.
    rows = []
    for k in range(6):
        rows.append({"theorem_name": f"t{k}", "category": "negation",
                     "candidate": "intro hp\n  exact absurd hp h",
                     "state_before": NEG_STATE, "beam_rank": 1,
                     "required_operation": "intro_negation",
                     "candidate_source": "token_seq2seq", "verified": True})
        rows.append({"theorem_name": f"t{k}", "category": "negation",
                     "candidate": "exact False.elim (h hp)",
                     "state_before": NEG_STATE, "beam_rank": 0,
                     "required_operation": "intro_negation",
                     "candidate_source": "token_seq2seq", "verified": False})
    return rows


def test_train_v23_is_deterministic():
    rows = _toy_rows()
    cfg = TrainConfig(epochs=40)
    m1 = train_v23_reranker(rows, cfg=cfg)
    m2 = train_v23_reranker(rows, cfg=cfg)
    assert m1.weights == m2.weights


def test_v23_scores_grounded_above_unbound():
    rows = _toy_rows()
    m = train_v23_reranker(rows, cfg=TrainConfig(epochs=80))
    good = m.score_row({"candidate": "intro hp\n  exact absurd hp h",
                        "state_before": NEG_STATE, "category": "negation",
                        "beam_rank": 1, "required_operation": "intro_negation",
                        "candidate_source": "token_seq2seq", "theorem_name": "z"})
    bad = m.score_row({"candidate": "exact False.elim (h hp)",
                       "state_before": NEG_STATE, "category": "negation",
                       "beam_rank": 0, "required_operation": "intro_negation",
                       "candidate_source": "token_seq2seq", "theorem_name": "z"})
    assert good > bad


def test_order_by_score_promotes_verified():
    rows = _toy_rows()
    m = train_v23_reranker(rows, cfg=TrainConfig(epochs=80))
    cands = [{"candidate": "exact False.elim (h hp)", "state_before": NEG_STATE,
              "category": "negation", "beam_rank": 0,
              "required_operation": "intro_negation",
              "candidate_source": "token_seq2seq", "theorem_name": "z"},
             {"candidate": "intro hp\n  exact absurd hp h", "state_before": NEG_STATE,
              "category": "negation", "beam_rank": 1,
              "required_operation": "intro_negation",
              "candidate_source": "token_seq2seq", "theorem_name": "z"}]
    order = order_by_score(cands, m)
    assert order[0] == 1  # the verified (grounded) candidate is promoted to rank0


def test_pattern_bag_built_from_verified_only():
    bag = build_pattern_bag_from_rows(_toy_rows())
    # only the verified candidate contributes a pattern
    assert bag.n_rows == 6


def test_save_load_roundtrip(tmp_path):
    from mini_elf_lean.v23_learned_reranker import V23Reranker
    m = train_v23_reranker(_toy_rows(), cfg=TrainConfig(epochs=20),
                           category_features=True)
    m.save(tmp_path / "m")
    m2 = V23Reranker.load(tmp_path / "m")
    assert m2.weights == m.weights
    assert m2.category_features is True
