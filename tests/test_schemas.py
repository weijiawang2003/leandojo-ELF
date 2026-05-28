"""Tests for the pydantic schemas."""

from __future__ import annotations

import pytest

from mini_elf_lean.schemas import (
    CollectionSummary,
    ManualCandidateRecord,
    TheoremSeed,
    TraceRecord,
)


def test_theorem_seed_minimum_fields() -> None:
    seed = TheoremSeed(theorem_name="t", theorem_statement="1 = 1")
    assert seed.theorem_name == "t"
    assert seed.initial_state is None


def test_theorem_seed_old_format_jsonl_still_validates() -> None:
    """Old seed rows with only name/statement/initial_state must still load."""

    seed = TheoremSeed.model_validate(
        {"theorem_name": "t", "theorem_statement": "1 = 1", "initial_state": "⊢ 1 = 1"}
    )
    assert seed.template is None
    assert seed.imports == []
    assert seed.placeholder == "__TACTIC__"


def test_theorem_seed_with_template() -> None:
    seed = TheoremSeed.model_validate(
        {
            "theorem_name": "t",
            "theorem_statement": "True",
            "template": "example : True := by\n  __TACTIC__",
            "imports": ["import Mathlib.Tactic"],
        }
    )
    assert "__TACTIC__" in (seed.template or "")
    assert seed.imports == ["import Mathlib.Tactic"]


def test_theorem_seed_rejects_unknown_fields() -> None:
    with pytest.raises(Exception):
        TheoremSeed(theorem_name="t", theorem_statement="1 = 1", bogus=42)  # type: ignore[call-arg]


def test_trace_record_roundtrip() -> None:
    rec = TraceRecord(
        theorem_name="t",
        theorem_statement="1 = 1",
        state_before="⊢ 1 = 1",
        tactic="rfl",
        state_after="no goals",
        proof_finished=True,
        num_goals_before=1,
        num_goals_after=0,
        state_changed=True,
        success=True,
        source="llm",
        model="mock",
        temperature=0.0,
    )
    dumped = rec.model_dump()
    restored = TraceRecord.model_validate(dumped)
    assert restored == rec
    assert isinstance(restored.timestamp, str)
    # New optional fields default sensibly.
    assert restored.backend == "unknown"
    assert restored.timeout is False
    assert restored.prompt_style is None
    assert restored.metadata == {}


def test_trace_record_carries_new_provenance_fields() -> None:
    rec = TraceRecord(
        theorem_name="t",
        theorem_statement="True",
        state_before="⊢ True",
        tactic="trivial",
        state_after="<verified by lean-cli>",
        success=True,
        proof_finished=True,
        backend="lean-cli",
        source="manual-file",
        model="manual-file",
        prompt_style="diverse",
        timeout=False,
        raw_llm_output=None,
    )
    restored = TraceRecord.model_validate(rec.model_dump())
    assert restored.backend == "lean-cli"
    assert restored.source == "manual-file"
    assert restored.prompt_style == "diverse"


def test_trace_record_ignores_unknown_legacy_fields() -> None:
    """Reading an old trace row with a now-removed key must not crash."""

    rec = TraceRecord.model_validate(
        {
            "theorem_name": "t",
            "theorem_statement": "True",
            "state_before": "⊢ True",
            "tactic": "trivial",
            "state_after": "no goals",
            "success": True,
            "proof_finished": True,
            "some_removed_field": 123,
        }
    )
    assert rec.success is True


def test_manual_candidate_record_loads() -> None:
    rec = ManualCandidateRecord.model_validate(
        {
            "theorem_name": "trivial_true",
            "state_before": "⊢ True",
            "candidates": ["trivial", "exact True.intro"],
            "source": "claude_code_agent",
            "prompt_style": "diverse",
        }
    )
    assert rec.candidates == ["trivial", "exact True.intro"]
    assert rec.source == "claude_code_agent"
    # Tolerates a record with no state_before (name-only matching).
    rec2 = ManualCandidateRecord.model_validate(
        {"theorem_name": "t", "candidates": ["rfl"]}
    )
    assert rec2.state_before is None
    assert rec2.source == "manual-file"


def test_collection_summary_success_rate() -> None:
    s = CollectionSummary(
        seeds_processed=1,
        tactics_attempted=10,
        tactics_succeeded=3,
        proofs_finished=1,
        duplicates_dropped=2,
        forbidden_dropped=1,
        timeouts=0,
        elapsed_seconds=1.5,
    )
    assert s.success_rate == 0.3

    empty = CollectionSummary(
        seeds_processed=0,
        tactics_attempted=0,
        tactics_succeeded=0,
        proofs_finished=0,
        duplicates_dropped=0,
        forbidden_dropped=0,
        timeouts=0,
        elapsed_seconds=0.0,
    )
    assert empty.success_rate == 0.0
