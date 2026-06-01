"""v31 Part 2 — identifier-normalization module (the safety-critical unit, no Lean)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.v31_identifier_normalization import (  # noqa: E402
    build_canonical_map, canonicalize_text, concretize_or_reject, parse_binders,
    is_valid_lean_ident, tactic_pattern,
)

STMT = "(α : Type) (u v : Set α) (w : α) (hw : w ∈ u ∩ v) : w ∈ u"
STMT2 = "(α : Type) (s t : Set α) (x : α) (h : x ∈ s ∩ t) : x ∈ s"
FS = "(α : Type) [DecidableEq α] (s t : Finset α) (a : α) (ha : a ∈ s ∩ t) : a ∈ s"


def test_parse_binders_skips_instances():
    assert parse_binders(STMT) == ["α", "u", "v", "w", "hw"]
    assert parse_binders(FS) == ["α", "s", "t", "a", "ha"]  # [DecidableEq α] contributes no name


def test_canonical_names_are_valid_lean_identifiers():
    cmap = build_canonical_map(STMT)
    for canon in cmap.canon_to_real:
        assert is_valid_lean_ident(canon), f"{canon} not a valid Lean identifier"
        assert "?" not in canon and "<" not in canon  # not a v19 placeholder


def test_roundtrip_projection():
    cmap = build_canonical_map(STMT)
    canon = canonicalize_text("exact hw.1", cmap)
    assert canon == "exact c4.1"
    assert concretize_or_reject(canon, cmap) == "exact hw.1"


def test_identifier_invariance_hw_and_h_same_canonical():
    # the headline property: different identifiers map to the SAME canonical form
    c1 = build_canonical_map(STMT)
    c2 = build_canonical_map(STMT2)
    assert canonicalize_text("exact hw.1", c1) == canonicalize_text("exact h.1", c2) == "exact c4.1"


def test_finset_mem_inter_roundtrips():
    cmap = build_canonical_map(FS)
    canon = canonicalize_text("exact (Finset.mem_inter.mp ha).1", cmap)
    assert concretize_or_reject(canon, cmap) == "exact (Finset.mem_inter.mp ha).1"


def test_unresolved_canonical_is_rejected():
    cmap = build_canonical_map(STMT)  # has c0..c4
    assert concretize_or_reject("exact c9.1", cmap) is None  # the v19 guard
    assert concretize_or_reject("exact c4.1", cmap) is not None


def test_tactic_introduced_names_pass_through():
    cmap = build_canonical_map(STMT)
    assert concretize_or_reject("intro x hx; exact hx.1", cmap) == "intro x hx; exact hx.1"


def test_no_binders_is_noop_fallback():
    cmap = build_canonical_map("rfl-only goal with no binders : True")
    # parse finds none -> ok False -> identity
    assert canonicalize_text("rfl", cmap) == "rfl"
    assert concretize_or_reject("rfl", cmap) == "rfl"


def test_pattern_collapses_identifiers():
    assert tactic_pattern("exact hw.1") == tactic_pattern("exact h.1") == "exact ID.1"
    assert "Set" in tactic_pattern("exact Set.empty_subset s")  # keeps lemma names
