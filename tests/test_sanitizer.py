"""Tests for tactic_sanitizer."""

from __future__ import annotations

from mini_elf_lean.tactic_sanitizer import (
    AUTOMATION_TACTICS,
    FORBIDDEN_TOKENS,
    contains_forbidden,
    is_automation,
    sanitize_candidate_list,
    sanitize_candidates,
    split_raw_output,
    tactic_head,
)


def test_strips_numbered_and_bulleted_prefixes() -> None:
    raw = "1. intro h\n- simp\n* rfl\n2) exact h"
    out, _ = sanitize_candidates(raw)
    assert out == ["intro h", "simp", "rfl", "exact h"]


def test_removes_code_fences_and_block_comments() -> None:
    raw = "```lean\nintro h\n/- a comment -/\nsimp\n```"
    out, _ = sanitize_candidates(raw)
    assert "intro h" in out
    assert "simp" in out
    # The fence markers should not appear as their own line.
    assert "```lean" not in out
    assert "```" not in out


def test_drops_inline_lean_comments() -> None:
    raw = "intro h -- explanation\nsimp -- another"
    out, _ = sanitize_candidates(raw)
    assert out == ["intro h", "simp"]


def test_dedupes_preserving_order() -> None:
    raw = "intro h\nsimp\nintro h\nrfl"
    out, stats = sanitize_candidates(raw)
    assert out == ["intro h", "simp", "rfl"]
    assert stats.duplicates_dropped == 1


def test_drops_forbidden_tokens() -> None:
    raw = "intro h\nsorry\nadmit\nsimp"
    out, stats = sanitize_candidates(raw)
    assert "sorry" not in out
    assert "admit" not in out
    assert stats.forbidden_dropped == 2


def test_contains_forbidden_is_word_bounded() -> None:
    # Should not flag a tactic that merely contains a forbidden token as a substring.
    assert not contains_forbidden("rcases h with sorry_like_name")
    # But should flag standalone forbidden tokens.
    for tok in FORBIDDEN_TOKENS:
        assert contains_forbidden(tok)
        assert contains_forbidden(f"  {tok}  ")


def test_handles_empty_and_whitespace() -> None:
    out, stats = sanitize_candidates("\n  \n   \n")
    assert out == []
    assert stats.after_clean == 0


def test_strips_surrounding_quotes() -> None:
    out, _ = sanitize_candidates('"simp"\n\'rfl\'\n`exact h`')
    assert out == ["simp", "rfl", "exact h"]


def test_tactic_head_and_is_automation() -> None:
    assert tactic_head("simp only [foo]") == "simp"
    assert tactic_head("exact?") == "exact?"
    assert tactic_head("  exact h") == "exact"
    assert is_automation("simp only [foo]")
    assert is_automation("omega")
    assert is_automation("exact?")
    assert not is_automation("exact h")
    assert not is_automation("intro h")


def test_automation_set_covers_required_tactics() -> None:
    for t in ("simp", "simp_all", "aesop", "omega", "linarith", "nlinarith",
              "ring", "norm_num", "exact?", "apply?", "grind"):
        assert t in AUTOMATION_TACTICS


def test_sanitize_candidate_list_dedupes_and_filters() -> None:
    out, stats = sanitize_candidate_list(["rfl", "rfl", "sorry", "exact h"])
    assert out == ["rfl", "exact h"]
    assert stats.duplicates_dropped == 1
    assert stats.forbidden_dropped == 1


def test_tactic_block_split_keeps_multiline_blocks() -> None:
    raw = "intro h\nexact h\n\nconstructor\n· exact h.1\n· exact h.2"
    blocks = split_raw_output(raw, prompt_style="tactic_block")
    assert len(blocks) == 2
    assert "intro h\nexact h" in blocks[0]
    out, _ = sanitize_candidate_list(blocks)
    # Multi-line blocks survive sanitization intact.
    assert any("\n" in c for c in out)
