"""Tests for the v17 policy edit (contradiction → USE_LEARNED).

Pins:
  * `contradiction` is in `USE_LEARNED` and NOT in `USE_DEFAULT_RULE`.
  * `choose_strategy("contradiction", margin)` returns `"learned"`
    regardless of the margin.
  * Edits do not break other routing entries.
  * The full strategy table matches the documented v17 routing.
"""

from __future__ import annotations

import pytest

from mini_elf_lean.v15_rerank_policy import (
    USE_DEFAULT_RULE, USE_LEARNED, USE_RULE, choose_strategy,
)


def test_contradiction_routes_to_learned() -> None:
    assert "contradiction" in USE_LEARNED
    assert "contradiction" not in USE_DEFAULT_RULE
    assert "contradiction" not in USE_RULE


def test_use_default_rule_is_empty_after_v17_edit() -> None:
    """The v17 edit emptied USE_DEFAULT_RULE — kept as a hook for
    future ties only."""
    assert len(USE_DEFAULT_RULE) == 0


@pytest.mark.parametrize("margin", [0.0, 0.05, 0.10, 0.50, 0.99])
def test_choose_strategy_contradiction_always_learned(margin: float) -> None:
    """The routing for ``contradiction`` must be deterministic
    (no fallback through the margin gate)."""
    assert choose_strategy(required_operation="contradiction",
                           learned_confidence=margin) == "learned"


def test_full_v17_strategy_table() -> None:
    """End-to-end pin: every operation we care about routes as
    documented in V17_ARROW_FALSE_ELIM_REPORT.md §2."""
    expectations = {
        "instantiate_forall": "rule",
        "rewrite": "rule",
        "intro_negation": "learned",
        "unknown": "learned",
        "contradiction": "learned",  # v17 edit
    }
    for op, expected in expectations.items():
        assert choose_strategy(required_operation=op,
                               learned_confidence=1.0) == expected
        assert choose_strategy(required_operation=op,
                               learned_confidence=0.0) == expected


def test_v15_pinned_routes_unchanged_by_v17() -> None:
    """v15's `intro_negation` and `unknown` routings are unchanged by
    the v17 edit (the docs say so). Pin defensively."""
    assert choose_strategy(required_operation="intro_negation",
                           learned_confidence=0.5) == "learned"
    assert choose_strategy(required_operation="unknown",
                           learned_confidence=0.5) == "learned"
    assert choose_strategy(required_operation="instantiate_forall",
                           learned_confidence=0.5) == "rule"
    assert choose_strategy(required_operation="rewrite",
                           learned_confidence=0.5) == "rule"


def test_unknown_op_below_threshold_still_falls_back_to_rule() -> None:
    """v17 didn't touch the confidence-gated fallback. An OOV
    operation with low margin must still default to rule."""
    s = choose_strategy(required_operation="totally_made_up_op",
                        learned_confidence=0.0)
    assert s == "rule"
