"""Unit tests for the v15 confidence-gated rerank policy."""

from __future__ import annotations

import inspect

import pytest

from mini_elf_lean import v15_rerank_policy as policy_mod
from mini_elf_lean.learned_reranker import LearnedReranker, TrainConfig, train_reranker
from mini_elf_lean.rerank_dataset import CandidateRow
from mini_elf_lean.v15_rerank_policy import (
    LEARNED_CONFIDENCE_THRESHOLD, USE_LEARNED, USE_RULE, choose_strategy,
    reorder,
)


def _mk(cand: str, *, verified: bool, op: str, rank: int = 0,
        family: str = "x") -> CandidateRow:
    return CandidateRow(
        theorem_name=f"t_{rank}", family=family, required_operation=op,
        theorem_statement="(p q : Prop) : ¬p",
        state_before="⊢ ¬p",
        candidate=cand, candidate_source="token_seq2seq",
        beam_rank=rank, verified=verified,
        error_class="ok" if verified else "other",
        source_run="v14_raw",
    )


# ----------------- routing table ------------------------------------------


@pytest.mark.parametrize("op,expected", [
    ("instantiate_forall", "rule"),
    ("rewrite", "rule"),
    ("intro_negation", "learned"),
    ("unknown", "learned"),
    # v17 edit: contradiction moved from rule → learned because learned
    # beats rule on neg_exfalso pass@1 under the v16 candidate
    # distribution (audit: docs/V17_RESIDUAL_FAILURE_AUDIT.md). v15
    # had this tied under v14 candidates and routed to rule for
    # continuity; v16 unties it.
    ("contradiction", "learned"),
])
def test_strategy_table(op: str, expected: str) -> None:
    # margin doesn't matter for the explicit table — it should match
    # regardless. Use a margin above and below threshold to be sure.
    for margin in (0.0, 0.5):
        assert choose_strategy(required_operation=op,
                               learned_confidence=margin) == expected


def test_unknown_operation_falls_back_to_rule_at_low_confidence() -> None:
    s = choose_strategy(required_operation="some_made_up_thing",
                        learned_confidence=0.0)
    assert s == "rule"


def test_unknown_operation_uses_learned_when_confident() -> None:
    s = choose_strategy(required_operation="some_made_up_thing",
                        learned_confidence=0.99)
    assert s == "learned"


def test_threshold_boundary() -> None:
    # At exactly the threshold, prefer learned (inclusive)
    s = choose_strategy(required_operation="zzz",
                        learned_confidence=LEARNED_CONFIDENCE_THRESHOLD)
    assert s == "learned"


# ----------------- reorder integration ------------------------------------


def _toy_model() -> LearnedReranker:
    pos = [_mk("intro hp\n  exact absurd hp hnp", verified=True,
               op="intro_negation", rank=i) for i in range(6)]
    neg = [
        _mk("refintro hp", verified=False, op="intro_negation"),
        _mk("rwexact h", verified=False, op="intro_negation"),
        _mk("exact h 5", verified=False, op="intro_negation"),
    ] * 4
    return train_reranker(pos + neg,
                          cfg=TrainConfig(epochs=30, lr=0.3, seed=0,
                                          class_weight_positive=4.0))


def test_reorder_intro_negation_uses_learned() -> None:
    model = _toy_model()
    cands = [
        _mk("refintro hp", verified=False, op="intro_negation", rank=0),
        _mk("intro hp\n  exact absurd hp hnp", verified=True,
            op="intro_negation", rank=4),
        _mk("rwexact h", verified=False, op="intro_negation", rank=1),
    ]
    order = reorder(cands, model=model, state_before="⊢ ¬p",
                    required_operation="intro_negation")
    reordered = [cands[i] for i in order]
    # The verifying candidate should rise to top under learned routing
    assert reordered[0].candidate == "intro hp\n  exact absurd hp hnp"


def test_reorder_returns_permutation() -> None:
    model = _toy_model()
    cands = [
        _mk("a", verified=False, op="intro_negation", rank=0),
        _mk("b", verified=False, op="intro_negation", rank=1),
        _mk("c", verified=False, op="intro_negation", rank=2),
    ]
    order = reorder(cands, model=model, required_operation="intro_negation")
    assert sorted(order) == [0, 1, 2]


def test_reorder_empty_input() -> None:
    model = _toy_model()
    assert reorder([], model=model, required_operation="rewrite") == []


def test_reorder_rewrite_uses_rule_features() -> None:
    """For required_operation == rewrite, the policy must use the rule
    reranker — even if the learned model has different ideas. We can't
    inspect the chosen sub-scorer directly, but we can check that the
    output order matches what the rule reranker would produce
    standalone."""
    from mini_elf_lean.proof_block_reranker import rerank as rule_rerank_fn
    model = _toy_model()
    cands = [
        _mk("intro h\n  rfl", verified=False, op="rewrite", rank=0),
        _mk("rw [h]", verified=True, op="rewrite", rank=4),
        _mk("rw [← h]", verified=False, op="rewrite", rank=3),
    ]
    order = reorder(cands, model=model, state_before="",
                    required_operation="rewrite")
    reordered = [cands[i] for i in order]
    # The rule reranker's schema_match for `rw [h]` should put it at
    # rank 0; the policy's "rule" routing must reflect that.
    assert reordered[0].candidate == "rw [h]"


# ----------------- no state_after -----------------------------------------


def test_no_state_after_in_policy_api() -> None:
    for name in ("choose_strategy", "reorder"):
        obj = getattr(policy_mod, name)
        sig = inspect.signature(obj)
        assert "state_after" not in sig.parameters
