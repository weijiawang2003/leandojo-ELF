"""Tests for the v20 ranker-time abstract-pattern reranker.

Unlike v19, the reranker NEVER emits placeholders — it scores raw
candidates and reorders them. Tests pin:

  * pattern bag construction
  * score discriminates known-pattern from novel-pattern
  * unbound identifiers are penalised (e.g. ``hpfalse`` on a state
    that contains only ``hp``)
  * Lean keywords and builtin constructors are NEVER treated as
    unbound (``exact``, ``Or.inl``, ``rfl``).
  * No placeholders survive into the reordered output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mini_elf_lean.abstract_pattern_reranker import (
    AbstractPatternReranker,
    PatternBag,
    ScoredCandidate,
    build_pattern_bag,
    load_pattern_bag,
    save_pattern_bag,
)


# ----------------- PatternBag -------------------------------------------


def test_pattern_bag_add_and_lookup() -> None:
    bag = PatternBag()
    bag.add("exact <HYP_PROP_0>", "implication")
    bag.add("exact <HYP_PROP_0>", "implication")
    bag.add("rfl", "equality_rewrite")
    assert bag.lookup("exact <HYP_PROP_0>", "implication") == 2
    assert bag.lookup("rfl", "equality_rewrite") == 1
    # Falls back to global count when category misses
    assert bag.lookup("rfl", "implication") == 1
    assert bag.lookup("never_seen", None) == 0


def test_pattern_bag_round_trip(tmp_path: Path) -> None:
    bag = PatternBag()
    bag.add("exact <HYP_PROP_0>", "implication")
    bag.add("intro <HYP_PROP_0>\n  exact <HYP_PROP_0>", "implication")
    save_pattern_bag(tmp_path / "bag.json", bag)
    bag2 = load_pattern_bag(tmp_path / "bag.json")
    assert bag2.lookup("exact <HYP_PROP_0>", "implication") == 1
    assert bag2.n_rows == 2


def test_build_pattern_bag_from_rows() -> None:
    rows = [
        {"state_before": "p : Prop\nhp : p\n⊢ p",
         "tactic": "exact hp", "category": "implication"},
        {"state_before": "p q : Prop\nh : p → q\nhp : p\n⊢ q",
         "tactic": "exact h hp", "category": "implication"},
    ]
    bag = build_pattern_bag(rows)
    # The first one abstracts hp→<HYP_PROP_0>
    assert any("<HYP_PROP_0>" in p for p in bag.global_counts), (
        f"abstraction did not produce placeholders: {list(bag.global_counts)}"
    )
    assert bag.n_rows == 2


# ----------------- AbstractPatternReranker scoring -----------------------


def _make_reranker_with_bag(patterns):
    bag = PatternBag()
    for p, n, cat in patterns:
        for _ in range(n):
            bag.add(p, cat)
    return AbstractPatternReranker(bag=bag), bag


def test_known_pattern_outranks_novel() -> None:
    rr, _ = _make_reranker_with_bag([
        ("exact <HYP_PROP_0>", 50, "implication"),
    ])
    state = "p : Prop\nhp : p\n⊢ p"
    cands = ["exact hp", "exact Or.inl"]  # second is novel pattern
    order = rr.order(cands, state_before=state, category="implication")
    # `exact hp` should rank above `exact Or.inl`
    first = cands[order[0]]
    assert first == "exact hp", f"expected exact hp first, got {first}"


def test_unbound_identifier_penalised() -> None:
    rr, _ = _make_reranker_with_bag([
        ("exact <HYP_PROP_0>", 100, "implication"),
    ])
    state = "p : Prop\nhp : p\n⊢ p"
    # `hpfalse` is not in the local context; reranker should
    # demote even if the *pattern* matches.
    cands = ["exact hpfalse", "exact hp"]
    order = rr.order(cands, state_before=state, category="implication")
    first = cands[order[0]]
    assert first == "exact hp", (
        f"unbound identifier should be penalised; got {first}")


def test_lean_keywords_not_treated_as_unbound() -> None:
    rr, _ = _make_reranker_with_bag([
        ("rfl", 100, "equality_rewrite"),
    ])
    state = "n : Nat\n⊢ n = n"
    sc = rr.score("rfl", raw_rank=0, state_before=state,
                  category="equality_rewrite")
    assert sc.n_unbound_idents == 0
    assert sc.pattern_count == 100


def test_constructors_not_treated_as_unbound() -> None:
    rr, _ = _make_reranker_with_bag([])
    state = "p : Prop\nhp : p\n⊢ p ∨ True"
    sc = rr.score("exact Or.inl hp", raw_rank=0, state_before=state,
                  category="disjunction")
    # Or, inl, hp are all in scope or builtins; no unbound idents.
    assert sc.n_unbound_idents == 0


def test_output_is_raw_names_never_placeholders() -> None:
    rr, _ = _make_reranker_with_bag([
        ("exact <HYP_PROP_0>", 5, "implication"),
    ])
    state = "p : Prop\nhp : p\n⊢ p"
    cands = ["exact hp", "rfl"]
    scored = rr.rerank(cands, state_before=state, category="implication")
    for s in scored:
        assert "<" not in s.candidate and ">" not in s.candidate, (
            f"reranker emitted a placeholder: {s.candidate}")


def test_order_returns_permutation() -> None:
    rr, _ = _make_reranker_with_bag([])
    state = "p : Prop\nhp : p\n⊢ p"
    cands = ["exact hp", "rfl", "intro x", "apply hp"]
    order = rr.order(cands, state_before=state, category="implication")
    assert sorted(order) == list(range(len(cands)))


def test_duplicate_candidates_handled() -> None:
    rr, _ = _make_reranker_with_bag([])
    state = "p : Prop\nhp : p\n⊢ p"
    cands = ["exact hp", "exact hp", "rfl"]
    order = rr.order(cands, state_before=state, category="implication")
    assert sorted(order) == [0, 1, 2]


def test_unbound_count_for_v18_hpfalse_failure() -> None:
    """Regression: v18 broad-only emits `exact (hpfalse hp).elim`
    on the v18_imp_p_self row whose state contains only `hp` — the
    reranker should detect `hpfalse` as unbound."""
    rr, _ = _make_reranker_with_bag([])
    state = "p : Prop\nhp : p\n⊢ p"
    sc = rr.score("exact (hpfalse hp).elim", raw_rank=0,
                  state_before=state, category="implication")
    assert sc.n_unbound_idents >= 1, (
        f"hpfalse should be flagged unbound; sc={sc}")


def test_score_is_finite() -> None:
    rr, _ = _make_reranker_with_bag([
        ("exact <HYP_PROP_0>", 1000, "implication"),
    ])
    state = "p : Prop\nhp : p\n⊢ p"
    sc = rr.score("exact hp", raw_rank=5, state_before=state,
                  category="implication")
    import math
    assert math.isfinite(sc.score)


def test_pattern_bag_uses_no_state_after() -> None:
    """Pattern bag must build from state_before + tactic only."""
    # We pass rows with state_after to make sure it's ignored.
    rows = [
        {"state_before": "p : Prop\nhp : p\n⊢ p",
         "state_after": "<verified>",
         "tactic": "exact hp", "category": "implication"},
    ]
    bag = build_pattern_bag(rows)
    assert bag.n_rows == 1
    # Just ensure abstract pattern is the placeholder form (which can
    # only come from state_before).
    assert any("<HYP_PROP_0>" in p for p in bag.global_counts)
