"""Backend factory selection for both LLM and Lean runners.

None of these require real Lean, LeanDojo, or API keys.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mini_elf_lean.config import Settings
from mini_elf_lean.lean_runner import (
    LeanCliRunner,
    MockLeanRunner,
    get_lean_runner,
)
from mini_elf_lean.llm_client import (
    ManualFileLLMClient,
    MockLLMClient,
    get_llm_client,
)


# ---- LLM backends ----


def test_llm_factory_mock() -> None:
    client = get_llm_client(Settings(llm_backend="mock"))
    assert isinstance(client, MockLLMClient)
    assert client.name == "mock"


def test_llm_factory_manual_file(tmp_path: Path) -> None:
    cand = tmp_path / "c.jsonl"
    cand.write_text('{"theorem_name": "t", "candidates": ["rfl"]}\n', encoding="utf-8")
    client = get_llm_client(Settings(llm_backend="manual-file"), manual_candidates_path=cand)
    assert isinstance(client, ManualFileLLMClient)
    assert client.model == "manual-file"


def test_llm_factory_manual_file_requires_path() -> None:
    with pytest.raises(ValueError, match="manual-file backend requires"):
        get_llm_client(Settings(llm_backend="manual-file"))


def test_llm_factory_anthropic_without_key_raises() -> None:
    s = Settings(llm_backend="anthropic", anthropic_api_key=None)
    with pytest.raises(RuntimeError, match="API key"):
        get_llm_client(s)


def test_llm_factory_openai_without_key_raises() -> None:
    s = Settings(llm_backend="openai", openai_api_key=None)
    with pytest.raises(RuntimeError, match="API key"):
        get_llm_client(s)


def test_llm_factory_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown LLM backend"):
        get_llm_client(Settings(llm_backend="not-real"))


# ---- Lean backends ----


def test_lean_factory_mock() -> None:
    runner = get_lean_runner(Settings(lean_backend="mock"))
    assert isinstance(runner, MockLeanRunner)


def test_lean_factory_lean_cli_and_underscore() -> None:
    for spelling in ("lean-cli", "lean_cli"):
        runner = get_lean_runner(Settings(lean_backend=spelling))
        try:
            assert isinstance(runner, LeanCliRunner)
        finally:
            runner.close()


def test_lean_factory_threads_lean_command() -> None:
    runner = get_lean_runner(Settings(lean_backend="lean-cli", lean_command="lake env lean"))
    try:
        assert runner._resolve_command() == ["lake", "env", "lean"]
    finally:
        runner.close()


def test_lean_factory_leandojo_missing_is_clean_error() -> None:
    # lean_dojo is not installed in CI; expect a clear RuntimeError, not ImportError.
    try:
        get_lean_runner(Settings(lean_backend="leandojo"))
    except RuntimeError as exc:
        assert "lean-dojo" in str(exc).lower() or "lean_dojo" in str(exc).lower()


def test_lean_factory_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown Lean backend"):
        get_lean_runner(Settings(lean_backend="not-real"))
