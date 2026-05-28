"""Mini-ELF v1 — verifier-aware reranker. Hand features are pure-Python; the
trainer/scorer are torch-gated. No Lean; never reads state_after."""

from __future__ import annotations

from pathlib import Path

import pytest

from mini_elf_lean.elf_rerank import (
    FEATURE_DIM,
    build_known_tokens,
    extract_features,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "mini_elf_lean"


# ---------------- pure-Python hand features ----------------


def test_feature_vector_length_stable():
    fr = extract_features("(p : Prop) : p", "p : Prop\n⊢ p", "exact h")
    assert len(fr.vector) == FEATURE_DIM


def test_known_token_ratio_flags_garble():
    known = build_known_tokens(["exact h.1", "constructor", "rfl"])
    good = extract_features("(p q:Prop)(h:p∧q):p", "p q : Prop\nh : p ∧ q\n⊢ p",
                            "exact h.1", known_tokens=known)
    garble = extract_features("(p q:Prop)(h:p∧q):p", "p q : Prop\nh : p ∧ q\n⊢ p",
                              "constructoontroctoo", known_tokens=known)
    assert good.debug["known_token_ratio"] > garble.debug["known_token_ratio"]
    assert garble.debug["malformed_prefix"] is True


def test_conjunct_consistency_left_vs_right():
    # goal p matches LEFT conjunct of h : p ∧ q -> `.1` is consistent (+1),
    # `.2` is inconsistent (-1).
    left_ok = extract_features("(p q:Prop)(h:p∧q):p", "p q : Prop\nh : p ∧ q\n⊢ p", "exact h.1")
    right_bad = extract_features("(p q:Prop)(h:p∧q):p", "p q : Prop\nh : p ∧ q\n⊢ p", "exact h.2")
    assert left_ok.debug["conjunct_consistency"] == 1.0
    assert right_bad.debug["conjunct_consistency"] == -1.0


def test_disjunct_consistency_inl_vs_inr():
    # goal p ∨ q, hyp h : p -> Or.inl is consistent (+1), Or.inr inconsistent.
    inl_ok = extract_features("(p q:Prop)(h:p):p∨q", "p q : Prop\nh : p\n⊢ p ∨ q", "exact Or.inl h")
    inr_bad = extract_features("(p q:Prop)(h:p):p∨q", "p q : Prop\nh : p\n⊢ p ∨ q", "exact Or.inr h")
    assert inl_ok.debug["disjunct_consistency"] == 1.0
    assert inr_bad.debug["disjunct_consistency"] == -1.0


def test_numeric_match_feature():
    fr = extract_features(": ∃ n : Nat, n = 5", "⊢ ∃ n : Nat, n = 5", "exact ⟨5, rfl⟩")
    assert fr.debug["numeric_match"] is True
    fr2 = extract_features(": ∃ n : Nat, n = 5", "⊢ ∃ n : Nat, n = 5", "exact ⟨9, rfl⟩")
    assert fr2.debug["numeric_match"] is False


def test_incomplete_block_detection():
    fr = extract_features("(p:Prop):p", "p : Prop\n⊢ p", "exact ⟨5, rfl")  # unbalanced ⟨
    assert fr.debug["incomplete_block"] is True


def test_rerank_module_never_accesses_state_after():
    text = (SRC / "elf_rerank.py").read_text(encoding="utf-8")
    for pat in (".state_after", '["state_after"]', "['state_after']",
                'get("state_after"', "get('state_after'"):
        assert pat not in text


# ---------------- torch-gated training / scoring ----------------


def _synthetic_examples():
    from mini_elf_lean.elf_rerank import RerankExample

    pairs = [
        ("a", "b"), ("p", "q"), ("r", "s"), ("x", "y"), ("c", "d"), ("e", "f"),
    ]
    exs = []
    for lhs, rhs in pairs:
        stmt = f"({lhs} {rhs} : Prop) (h : {lhs} ∧ {rhs}) : {lhs}"
        state = f"{lhs} {rhs} : Prop\nh : {lhs} ∧ {rhs}\n⊢ {lhs}"
        # positives: correct projection / valid tactic
        exs.append(RerankExample(stmt, state, "exact h.1", 1, theorem_name=f"and_{lhs}"))
        # negatives: wrong projection + garble
        exs.append(RerankExample(stmt, state, "exact h.2", 0, theorem_name=f"and_{lhs}"))
        exs.append(RerankExample(stmt, state, "consxxtructoor", 0, theorem_name=f"and_{lhs}"))
    return exs


def test_train_and_positive_outranks_negative():
    pytest.importorskip("torch")
    from mini_elf_lean.elf_rerank import RerankConfig, Reranker

    exs = _synthetic_examples()
    cfg = RerankConfig(epochs=80, lr=5e-3, batch=16, seed=0)
    rr = Reranker.fit(exs, cfg)
    stmt = "(p q : Prop) (h : p ∧ q) : p"
    state = "p q : Prop\nh : p ∧ q\n⊢ p"
    s_good = rr.score(stmt, state, "exact h.1")
    s_bad = rr.score(stmt, state, "consxxtructoor")
    s_wrong = rr.score(stmt, state, "exact h.2")
    assert s_good > s_bad
    assert s_good > s_wrong  # structure-aware: right projection beats wrong


def test_rank_dedups_and_orders():
    pytest.importorskip("torch")
    from mini_elf_lean.elf_rerank import RerankConfig, Reranker

    rr = Reranker.fit(_synthetic_examples(), RerankConfig(epochs=40, seed=0))
    cands = ["exact h.1", "exact h.1", "consxxtructoor", "exact h.2"]
    ranked = rr.rank("(p q : Prop) (h : p ∧ q) : p", "p q : Prop\nh : p ∧ q\n⊢ p", cands)
    names = [c for c, _ in ranked]
    assert names.count("exact h.1") == 1  # deduplicated
    assert names[0] == "exact h.1"  # best candidate first
    # sorted by score desc
    scores = [s for _, s in ranked]
    assert scores == sorted(scores, reverse=True)


def test_scoring_deterministic_with_fixed_seed():
    pytest.importorskip("torch")
    from mini_elf_lean.elf_rerank import RerankConfig, Reranker

    a = Reranker.fit(_synthetic_examples(), RerankConfig(epochs=30, seed=0))
    b = Reranker.fit(_synthetic_examples(), RerankConfig(epochs=30, seed=0))
    stmt, state = "(p q : Prop) (h : p ∧ q) : p", "p q : Prop\nh : p ∧ q\n⊢ p"
    assert abs(a.score(stmt, state, "exact h.1") - b.score(stmt, state, "exact h.1")) < 1e-6


def test_save_load_roundtrip(tmp_path):
    pytest.importorskip("torch")
    from mini_elf_lean.elf_rerank import RerankConfig, Reranker

    rr = Reranker.fit(_synthetic_examples(), RerankConfig(epochs=20, seed=0))
    rr.save(tmp_path)
    for f in ("rerank_vocab.json", "rerank_model.pt", "rerank_config.json"):
        assert (tmp_path / f).exists()
    rr2 = Reranker.load(tmp_path)
    stmt, state = "(p q : Prop) (h : p ∧ q) : p", "p q : Prop\nh : p ∧ q\n⊢ p"
    assert abs(rr.score(stmt, state, "exact h.1") - rr2.score(stmt, state, "exact h.1")) < 1e-6
