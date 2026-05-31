"""Unit tests for the v15 pure-Python logistic regression reranker.

Pins:
  * deterministic training (same seed ⇒ same weights),
  * save/load round-trip,
  * inference orders candidates higher-score-first,
  * no state_after in any public API,
  * the model learns the obvious correlation
    ``verified ⇔ candidate matches a known-good pattern``.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from mini_elf_lean import learned_reranker as lr
from mini_elf_lean.learned_reranker import (
    FeatureIndex, LearnedReranker, TrainConfig, rerank_candidates,
    train_reranker, vectorise,
)
from mini_elf_lean.rerank_dataset import CandidateRow


def _mk(cand: str, *, verified: bool, family: str = "neg_imp_exfalso",
        op: str = "intro_negation", source: str = "token_seq2seq",
        rank: int = 0) -> CandidateRow:
    return CandidateRow(
        theorem_name=f"t_{cand[:6]}_{rank}",
        family=family, required_operation=op,
        theorem_statement="(p q : Prop) : ¬p",
        state_before="⊢ ¬p",
        candidate=cand, candidate_source=source,
        beam_rank=rank, verified=verified,
        error_class="ok" if verified else "other",
        source_run="v14_raw",
    )


def _toy_dataset():
    """Tiny but well-formed dataset where the learned reranker can
    actually learn something. Positives: `intro hp\n  exact absurd hp hnp`.
    Negatives: malformed siblings."""
    pos = [
        _mk("intro hp\n  exact absurd hp hnp", verified=True, rank=i)
        for i in range(8)
    ]
    neg = [
        _mk("exact fun hp => hnq (h1 ", verified=False, rank=0),
        _mk("exact fun hp => hnq (h hp)", verified=False, rank=1),
        _mk("intro hp\n  exact (h hp)", verified=False, rank=2),
        _mk("exact fun hp => hnp hp", verified=False, rank=3),
        _mk("refintro hp", verified=False, rank=4),
        _mk("rwexact h", verified=False, rank=5),
        _mk("exact h 5", verified=False, rank=6),  # wrong shape for ¬p
        _mk("rcases h wi", verified=False, rank=7),
    ] * 3
    return pos + neg


# ----------------- determinism --------------------------------------------


def test_train_is_deterministic() -> None:
    rows = _toy_dataset()
    cfg = TrainConfig(epochs=20, lr=0.3, seed=42,
                      class_weight_positive=4.0)
    m1 = train_reranker(rows, cfg=cfg)
    m2 = train_reranker(rows, cfg=cfg)
    assert m1.weights == m2.weights
    assert m1.index.id_to_name == m2.index.id_to_name


def test_different_seeds_give_different_weights() -> None:
    rows = _toy_dataset()
    cfg_a = TrainConfig(epochs=20, lr=0.3, seed=0)
    cfg_b = TrainConfig(epochs=20, lr=0.3, seed=1)
    m_a = train_reranker(rows, cfg=cfg_a)
    m_b = train_reranker(rows, cfg=cfg_b)
    assert m_a.weights != m_b.weights


# ----------------- learning signal ----------------------------------------


def test_model_learns_to_prefer_verifying_candidate() -> None:
    rows = _toy_dataset()
    m = train_reranker(rows, cfg=TrainConfig(epochs=40, lr=0.3, seed=0,
                                             class_weight_positive=4.0))
    # The verifying candidate should score higher than any of the
    # malformed siblings in the same toy dataset.
    pos_row = _mk("intro hp\n  exact absurd hp hnp", verified=True)
    neg_rows = [
        _mk("refintro hp", verified=False),
        _mk("rwexact h", verified=False),
        _mk("exact h 5", verified=False),
        _mk("rcases h wi", verified=False),
    ]
    pos_score = m.score_row(pos_row)
    for n in neg_rows:
        assert m.score_row(n) < pos_score, (
            f"learned reranker ranked {n.candidate!r} above the "
            f"verifying contrapositive"
        )


def test_rerank_orders_best_first() -> None:
    rows = _toy_dataset()
    m = train_reranker(rows, cfg=TrainConfig(epochs=40, lr=0.3, seed=0,
                                             class_weight_positive=4.0))
    cands = [
        _mk("refintro hp", verified=False),
        _mk("intro hp\n  exact absurd hp hnp", verified=True),
        _mk("rwexact h", verified=False),
    ]
    out = rerank_candidates(m, cands)
    # The verifying candidate must be at position 0
    assert out[0][0].candidate == "intro hp\n  exact absurd hp hnp"


# ----------------- save/load ----------------------------------------------


def test_save_load_round_trip(tmp_path: Path) -> None:
    rows = _toy_dataset()
    m = train_reranker(rows, cfg=TrainConfig(epochs=10, seed=0))
    out = tmp_path / "rr"
    m.save(out)
    assert (out / "weights.json").exists()
    assert (out / "index.json").exists()
    assert (out / "config.json").exists()
    m2 = LearnedReranker.load(out)
    assert m2.weights == m.weights
    # Identical predictions
    cand = _mk("intro hp\n  exact absurd hp hnp", verified=True)
    assert m2.score_row(cand) == pytest.approx(m.score_row(cand), abs=1e-9)


# ----------------- FeatureIndex contract ----------------------------------


def test_feature_index_extends_only_when_asked() -> None:
    idx = FeatureIndex()
    v = vectorise({"a": 1.0, "b": 0.5}, idx, extend=True)
    assert set(v.values()) == {1.0, 0.5}
    assert len(idx) == 2
    # extend=False: unseen names are silently dropped
    v2 = vectorise({"a": 2.0, "c": 1.0}, idx, extend=False)
    assert v2 == {idx.get("a"): 2.0}
    assert len(idx) == 2  # not extended


# ----------------- no state_after -----------------------------------------


def test_no_state_after_anywhere_in_public_api() -> None:
    for name in ("train_reranker", "rerank_candidates", "vectorise"):
        obj = getattr(lr, name)
        sig = inspect.signature(obj)
        assert "state_after" not in sig.parameters, (
            f"{name} accepts state_after")


def test_model_score_row_does_not_consume_state_after() -> None:
    rows = _toy_dataset()
    m = train_reranker(rows, cfg=TrainConfig(epochs=5, seed=0))
    sig = inspect.signature(m.score_row)
    assert "state_after" not in sig.parameters


# ----------------- top_features readout -----------------------------------


def test_top_features_has_strongly_positive_intro_absurd_features() -> None:
    rows = _toy_dataset()
    m = train_reranker(rows, cfg=TrainConfig(epochs=40, lr=0.3, seed=0,
                                             class_weight_positive=4.0))
    top = m.top_features(k=15)
    # Expect at least one of contains_intro / contains_absurd / has_intro
    # to appear among the top positive features in this toy regime.
    pos_features = [name for name, w in top if w > 0]
    flagged = {"contains_intro", "contains_absurd", "has_intro"}
    assert any(name in flagged for name in pos_features), (
        f"none of {flagged} among top positives; got {top}"
    )


# ----------------- val metrics --------------------------------------------


def test_val_metrics_populated_when_val_rows_given() -> None:
    rows = _toy_dataset()
    val = [
        _mk("intro hp\n  exact absurd hp hnp", verified=True, rank=99),
        _mk("rwexact h", verified=False, rank=99),
    ]
    m = train_reranker(rows, cfg=TrainConfig(epochs=10, seed=0),
                       val_rows=val)
    last = m.train_history[-1]
    assert "val_acc" in last
    assert "val_tp" in last and "val_fp" in last
