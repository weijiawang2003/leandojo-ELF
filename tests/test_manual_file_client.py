"""Tests for ManualFileLLMClient matching rules."""

from __future__ import annotations

from pathlib import Path

from mini_elf_lean.io_utils import write_jsonl
from mini_elf_lean.llm_client import ManualFileLLMClient
from mini_elf_lean.schemas import TheoremSeed


def _seed(name: str, state: str) -> TheoremSeed:
    return TheoremSeed(theorem_name=name, theorem_statement="...", initial_state=state)


def _write(tmp_path: Path, rows) -> Path:
    p = tmp_path / "cand.jsonl"
    write_jsonl(p, rows)
    return p


def test_exact_match_on_name_and_state(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        [
            {"theorem_name": "t", "state_before": "⊢ A", "candidates": ["a1"], "source": "agent", "prompt_style": "diverse"},
            {"theorem_name": "t", "state_before": "⊢ B", "candidates": ["b1", "b2"]},
        ],
    )
    client = ManualFileLLMClient(p)
    batch = client.propose_tactics(
        seed=_seed("t", "⊢ B"), state_before="⊢ B", num_candidates=5,
        prompt_style="diverse", temperature=None,
    )
    assert batch.candidates == ["b1", "b2"]
    assert batch.model == "manual-file"


def test_name_only_fallback_when_unambiguous(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        [{"theorem_name": "solo", "state_before": "⊢ different", "candidates": ["rfl"], "source": "agent"}],
    )
    client = ManualFileLLMClient(p)
    # state_before does not match, but there is exactly one record for "solo".
    batch = client.propose_tactics(
        seed=_seed("solo", "⊢ unseen-state"), state_before="⊢ unseen-state",
        num_candidates=5, prompt_style=None, temperature=None,
    )
    assert batch.candidates == ["rfl"]
    assert batch.source == "agent"


def test_ambiguous_name_only_returns_empty(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        [
            {"theorem_name": "dup", "state_before": "⊢ A", "candidates": ["a"]},
            {"theorem_name": "dup", "state_before": "⊢ B", "candidates": ["b"]},
        ],
    )
    client = ManualFileLLMClient(p)
    # Two records for "dup", neither matching the state -> refuse to guess.
    batch = client.propose_tactics(
        seed=_seed("dup", "⊢ C"), state_before="⊢ C", num_candidates=5,
        prompt_style=None, temperature=None,
    )
    assert batch.candidates == []


def test_missing_theorem_returns_empty_not_crash(tmp_path: Path) -> None:
    p = _write(tmp_path, [{"theorem_name": "known", "candidates": ["rfl"]}])
    client = ManualFileLLMClient(p)
    batch = client.propose_tactics(
        seed=_seed("unknown", "⊢ X"), state_before="⊢ X", num_candidates=5,
        prompt_style=None, temperature=None,
    )
    assert batch.candidates == []
    assert batch.source == "manual-file"


def test_missing_file_does_not_crash(tmp_path: Path) -> None:
    client = ManualFileLLMClient(tmp_path / "does_not_exist.jsonl")
    batch = client.propose_tactics(
        seed=_seed("t", "⊢ A"), state_before="⊢ A", num_candidates=5,
        prompt_style=None, temperature=None,
    )
    assert batch.candidates == []


def test_num_candidates_limits_returned(tmp_path: Path) -> None:
    p = _write(tmp_path, [{"theorem_name": "t", "state_before": "⊢ A", "candidates": ["a", "b", "c", "d"]}])
    client = ManualFileLLMClient(p)
    batch = client.propose_tactics(
        seed=_seed("t", "⊢ A"), state_before="⊢ A", num_candidates=2,
        prompt_style=None, temperature=None,
    )
    assert batch.candidates == ["a", "b"]
