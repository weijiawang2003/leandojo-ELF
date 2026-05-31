"""Tests for :mod:`mini_elf_lean.proof_block_cleaner`."""

from __future__ import annotations

import pytest


def test_clean_strips_markdown_fences():
    from mini_elf_lean.proof_block_cleaner import clean_candidates
    raw = ["```lean\nexact h\n```", "```\nrfl\n```", "exact absurd hp hnp"]
    out, stats = clean_candidates(raw)
    assert out == ["exact h", "rfl", "exact absurd hp hnp"]
    assert stats.fences_removed >= 4  # two pairs of fences


def test_clean_preserves_multiline_tactic_blocks():
    from mini_elf_lean.proof_block_cleaner import clean_candidates
    multi = "intro h\nexact h.1"
    out, _ = clean_candidates([multi])
    assert out == [multi]


def test_clean_rejects_pure_prose():
    """Lines that start with prose connectives (Here/First/Then/We/…) are
    line-dropped; a candidate composed entirely of such lines becomes empty
    and is dropped. The lean-shaped candidate survives unchanged."""
    from mini_elf_lean.proof_block_cleaner import clean_candidates
    out, stats = clean_candidates([
        "Here is the proof.\nFirst, intro h.\nThen exact h.",  # all prose
        "The theorem says that the proof is by exact.",        # all prose
        "intro h\nexact h",                                    # lean-shaped
        "exact h",                                              # lean-shaped
    ])
    # Both pure-prose blocks are dropped; the two lean-shaped survive.
    assert "exact h" in out
    assert "intro h\nexact h" in out
    assert stats.dropped_prose >= 3  # multiple prose lines were dropped
    assert stats.dropped_empty >= 2  # two candidates became empty after prose strip


def test_clean_rejects_empty_and_dedups():
    from mini_elf_lean.proof_block_cleaner import clean_candidates
    out, stats = clean_candidates(["", "   ", "exact h", "exact h", " exact h "])
    assert out == ["exact h"]
    assert stats.dropped_empty >= 2
    assert stats.dropped_duplicate >= 2


def test_clean_drops_state_after():
    """A generator that hallucinates ``state_after: …`` is rejected."""
    from mini_elf_lean.proof_block_cleaner import clean_candidates
    bad = "exact h\nstate_after: ⊢ True"
    out, stats = clean_candidates([bad, "rfl"])
    assert "rfl" in out
    assert bad not in out
    assert stats.dropped_state_after >= 1


def test_clean_strips_label_prefix():
    from mini_elf_lean.proof_block_cleaner import clean_candidate, CleanerStats
    stats = CleanerStats()
    s = clean_candidate("Proof: exact h", stats)
    assert s == "exact h"
    assert stats.labels_removed >= 1


def test_clean_normalises_common_indent():
    from mini_elf_lean.proof_block_cleaner import clean_candidate, CleanerStats
    stats = CleanerStats()
    s = clean_candidate("    intro h\n    exact h", stats)
    assert s == "intro h\nexact h"
