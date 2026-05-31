"""V5 Part 7 — LLM proposer skip-path tests.

Must run with NO API key: checks the proposer reports unavailable and returns
``[]`` (never faked), and that the JSON-list parser is robust. No network."""

from __future__ import annotations

import pytest

from mini_elf_lean.config import Settings
from mini_elf_lean.llm_proposer import LLMProposer, parse_tactic_list


@pytest.fixture
def no_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MINI_ELF_OPENAI_API_KEY", raising=False)


def _proposer():
    # Pass keyless settings explicitly so the test never depends on a real .env.
    return LLMProposer(settings=Settings(anthropic_api_key=None, openai_api_key=None))


def test_unavailable_without_key(no_keys):
    p = _proposer()
    assert p.available() is False
    assert p.backend is None
    status = p.status()
    assert status["available"] is False and status["reason"]


def test_propose_skips_cleanly(no_keys):
    p = _proposer()
    assert p.propose("(p : Prop) (hp : p) : p", "p : Prop\nhp : p\n⊢ p", theorem_name="t") == []


def test_explicit_backend_still_unavailable_without_key(no_keys):
    p = LLMProposer(settings=Settings(), backend="anthropic")
    assert p.available() is False
    assert p.propose("x", "y") == []


def test_parse_tactic_list_json():
    assert parse_tactic_list('["rw [h]", "exact h 5"]') == ["rw [h]", "exact h 5"]


def test_parse_tactic_list_fenced():
    txt = "```json\n[\"contradiction\", \"exact absurd hp hnp\"]\n```"
    assert parse_tactic_list(txt) == ["contradiction", "exact absurd hp hnp"]


def test_parse_tactic_list_embedded_array():
    txt = 'Here you go:\n["rfl", "simp"]\nHope this helps.'
    assert parse_tactic_list(txt) == ["rfl", "simp"]


def test_parse_tactic_list_fallback_lines():
    out = parse_tactic_list("rw [h]\n\nexact h 5")
    assert "rw [h]" in out and "exact h 5" in out


def test_parse_tactic_list_empty():
    assert parse_tactic_list("") == []
