"""Tests for the tactic-prediction baselines.

All hand-built fixtures — no dataset on disk, no Lean. The contract under test:

  - MajorityBaseline ranks tactics by training frequency with stable tie-break.
  - RetrievalBaseline never mixes the eval-split theorems into the retrieval
    pool, deduplicates tactics in rank order, and respects top-k.
  - load_dataset_split raises on cross-split leakage (defensive guard).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mini_elf_lean.baselines import (
    Example,
    MajorityBaseline,
    RetrievalBaseline,
    load_dataset,
    load_dataset_split,
    oracle_verified_lookup,
    split_summary,
)


def _ex(name="t1", state="⊢ p", tactic="exact h", split="train", stmt=None) -> Example:
    return Example(
        theorem_name=name,
        theorem_statement=stmt or f"({name})",
        state_before=state,
        tactic=tactic,
        split=split,
    )


def _write_dataset(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "next_tactic.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return p


# ---- MajorityBaseline ----


def test_majority_ranks_by_frequency_then_alphabetical_tiebreak() -> None:
    train = [
        _ex(tactic="rfl"), _ex(tactic="rfl"), _ex(tactic="rfl"),
        _ex(tactic="exact h"), _ex(tactic="exact h"),
        _ex(tactic="trivial"), _ex(tactic="trivial"),  # tie with exact h (2)
        _ex(tactic="omega"),
    ]
    b = MajorityBaseline().fit(train)
    # rfl(3) > [exact h, trivial](2) > omega(1). Tie broken by alphabetical.
    preds = b.predict(_ex(split="val"), k=5)
    assert preds[0] == "rfl"
    assert preds[1:3] == ["exact h", "trivial"]  # 'exact h' < 'trivial'
    assert preds[3] == "omega"


def test_majority_top_k_truncates() -> None:
    train = [_ex(tactic=t) for t in ["a", "b", "c", "d"]]
    b = MajorityBaseline().fit(train)
    assert len(b.predict(_ex(), k=2)) == 2


def test_majority_ignores_input() -> None:
    """Sanity: the prediction must not depend on the eval example's text."""
    train = [_ex(tactic="rfl"), _ex(tactic="rfl"), _ex(tactic="exact h")]
    b = MajorityBaseline().fit(train)
    p1 = b.predict(_ex(state="⊢ p"), k=3)
    p2 = b.predict(_ex(state="∀ x, x = x ∧ True ∧ ⊥"), k=3)
    assert p1 == p2


def test_majority_empty_train_returns_empty() -> None:
    b = MajorityBaseline().fit([])
    assert b.predict(_ex(), k=3) == []


# ---- RetrievalBaseline (char-ngram path; sklearn may or may not be present) ----


def test_retrieval_returns_train_tactics_dedup_in_rank_order() -> None:
    train = [
        _ex(name="and_comm", stmt="(p q : Prop) (h : p ∧ q) : q ∧ p",
            state="p q : Prop\nh : p ∧ q\n⊢ q ∧ p", tactic="exact ⟨h.2, h.1⟩"),
        _ex(name="and_comm2", stmt="(a b : Prop) (h : a ∧ b) : b ∧ a",
            state="a b : Prop\nh : a ∧ b\n⊢ b ∧ a", tactic="exact ⟨h.2, h.1⟩"),  # dup tactic
        _ex(name="ax_p", stmt="(p : Prop) (h : p) : p",
            state="p : Prop\nh : p\n⊢ p", tactic="exact h"),
        _ex(name="ax_q", stmt="(q : Prop) (h : q) : q",
            state="q : Prop\nh : q\n⊢ q", tactic="assumption"),
    ]
    eval_ = _ex(name="ax_r", stmt="(r : Prop) (h : r) : r",
                state="r : Prop\nh : r\n⊢ r", tactic="exact h", split="val")
    b = RetrievalBaseline(neighbors=10).fit(train)
    preds = b.predict(eval_, k=5)

    # No duplicate tactics in the output.
    assert len(preds) == len(set(preds))
    # The matching tactic for an ax_* theorem should be on the list.
    assert "exact h" in preds or "assumption" in preds


def test_retrieval_predict_with_neighbors_returns_provenance() -> None:
    train = [
        _ex(name="A", state="⊢ p1", tactic="rfl"),
        _ex(name="B", state="⊢ p2", tactic="exact h"),
    ]
    b = RetrievalBaseline().fit(train)
    preds, prov = b.predict_with_neighbors(
        _ex(name="Eval", state="⊢ p1", split="val"), k=2
    )
    assert len(preds) == len(prov)
    for p in prov:
        assert "source_theorem" in p and "score" in p
        # score is cosine-like in [0, 1]; with non-empty texts must be a float.
        assert isinstance(p["score"], float)


def test_retrieval_empty_train_returns_empty_predictions() -> None:
    b = RetrievalBaseline().fit([])
    assert b.predict(_ex(split="val"), k=3) == []


def test_retrieval_dedup_keeps_first_seen_order() -> None:
    # Two train rows produce the same tactic; later rows produce alternates.
    train = [
        _ex(name="A", state="x", tactic="rfl"),
        _ex(name="B", state="x", tactic="rfl"),
        _ex(name="C", state="x", tactic="exact h"),
        _ex(name="D", state="x", tactic="trivial"),
    ]
    b = RetrievalBaseline(neighbors=10).fit(train)
    preds = b.predict(_ex(name="E", state="x", split="val"), k=5)
    # No duplicates.
    assert preds == list(dict.fromkeys(preds))


# ---- split loading / leakage ----


def test_load_dataset_split_returns_train_and_eval_disjoint(tmp_path: Path) -> None:
    rows = [
        {"theorem_name": "a", "theorem_statement": "(a)", "state_before": "⊢ a",
         "tactic": "rfl", "split": "train", "state_after": "no goals",
         "state_after_is_real": False, "verification_quality": "theorem-level",
         "proof_finished": True, "success": True, "backend": "lean-cli",
         "num_goals_before": 1, "num_goals_after": 0, "source_record_hash": "h1"},
        {"theorem_name": "b", "theorem_statement": "(b)", "state_before": "⊢ b",
         "tactic": "exact h", "split": "val", "state_after": "no goals",
         "state_after_is_real": False, "verification_quality": "theorem-level",
         "proof_finished": True, "success": True, "backend": "lean-cli",
         "num_goals_before": 1, "num_goals_after": 0, "source_record_hash": "h2"},
    ]
    path = _write_dataset(tmp_path, rows)
    train, val = load_dataset_split(path, "val")
    assert [e.theorem_name for e in train] == ["a"]
    assert [e.theorem_name for e in val] == ["b"]


def test_load_dataset_split_train_returns_copies_of_train(tmp_path: Path) -> None:
    rows = [
        {"theorem_name": "a", "theorem_statement": "(a)", "state_before": "⊢ a",
         "tactic": "rfl", "split": "train"},
    ]
    path = _write_dataset(tmp_path, rows)
    train, eval_ = load_dataset_split(path, "train")
    assert [e.theorem_name for e in train] == ["a"]
    assert [e.theorem_name for e in eval_] == ["a"]


def test_load_dataset_split_raises_on_leakage(tmp_path: Path) -> None:
    # Hand-craft a malformed dataset where 'a' lives in both train and val.
    rows = [
        {"theorem_name": "a", "theorem_statement": "(a)", "state_before": "⊢ a",
         "tactic": "rfl", "split": "train"},
        {"theorem_name": "a", "theorem_statement": "(a)", "state_before": "⊢ a",
         "tactic": "exact h", "split": "val"},
    ]
    path = _write_dataset(tmp_path, rows)
    with pytest.raises(RuntimeError, match="leakage"):
        load_dataset_split(path, "val")


def test_split_summary_reports_theorem_intersection_empty_for_clean() -> None:
    train = [_ex(name="a"), _ex(name="b")]
    val = [_ex(name="c", split="val")]
    s = split_summary(train, val)
    assert s["theorem_intersection"] == []
    assert s["n_train_theorems"] == 2 and s["n_eval_theorems"] == 1


def test_oracle_lookup_aggregates_tactics_per_state() -> None:
    rows = [
        _ex(name="t", state="⊢ p", tactic="exact h"),
        _ex(name="t", state="⊢ p", tactic="assumption"),
        _ex(name="t", state="⊢ q", tactic="trivial"),
    ]
    lookup = oracle_verified_lookup(rows)
    assert lookup[("t", "⊢ p")] == frozenset({"exact h", "assumption"})
    assert lookup[("t", "⊢ q")] == frozenset({"trivial"})


def test_retrieval_does_not_leak_eval_theorems_into_train_pool(tmp_path: Path) -> None:
    """End-to-end: fit on train only, predict for an eval row — none of the
    eval row's theorem's tactics should be available to the retrieval pool."""
    train = [_ex(name="ax_p", state="⊢ p", tactic="exact h"),
             _ex(name="ax_q", state="⊢ q", tactic="assumption")]
    eval_row = _ex(name="ax_r", state="⊢ r", tactic="rfl", split="val")
    b = RetrievalBaseline().fit(train)  # eval not in `fit`
    preds = b.predict(eval_row, k=5)
    assert "rfl" not in preds  # eval-only tactic must not appear
    assert all(p in {"exact h", "assumption"} for p in preds)
