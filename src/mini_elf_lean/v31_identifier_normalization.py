"""Mini-ELF v31 — safe identifier normalization (NOT v19 placeholder decoding).

The v30 audit showed the remaining residuals are **surface-token OOD**: the model knows
the proof shape (`exact ID.1`) but cannot bind an unseen local identifier (`hw`, `hm`,
`g`). v31 attacks this with identifier *canonicalization* — but, unlike the v19
placeholder attempt that turned `unknown_identifier` into a dominant
`unresolved_placeholder` failure and dropped pass@k, this module is engineered so it
can only ever **add** coverage on top of the raw model:

  1. **Valid Lean identifiers.** Canonical binder names are `c0, c1, …` — real, legal
     identifiers; a canonicalized statement type-checks. No angle-bracket placeholders.
  2. **Reject-before-verify.** `concretize_or_reject` returns ``None`` if a generated
     canonical tactic carries a `cN` token with no mapping — the candidate is dropped
     *before* Lean sees it, so the v19 `unresolved_placeholder` mode cannot occur.
  3. **Raw fallback (union, not replacement).** Callers add concretized canonical
     candidates to the raw pool; raw generation is always present.

Approaches provided:
  * **A** (`build_canonical_map` / `canonicalize_text` / `concretize_or_reject`):
    map every *statement binder* identifier to a stable canonical slot, so the model
    sees one identifier-invariant form. Tactic-introduced names (from `intro`/`rintro`)
    are NOT canonicalized — they pass through unchanged.
  * **C** (`tactic_pattern`): an identifier-free pattern for *ranking only* (never an
    output) — two proofs that differ only by identifier collapse to one pattern.

Honesty: no `state_after`; canonical names are valid Lean identifiers; this is not used
as a generation-time placeholder decoder; unresolved canonical candidates are rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# A Lean identifier token (ASCII + Greek + Unicode subscripts/superscripts, primes,
# digits). v33 hardening: the continuation class includes subscript digits/letters
# (U+2080–U+209C) and superscript digits (¹²³ U+00B9/B2/B3, U+2070–U+2079) so binders
# like `proof₁`, `h₂`, `f¹` are recognized — without this the canonical decode missed
# subscript identifiers and rejected the model's canonical output (the v32 adversarial
# ~8.5% unresolved rate). Purely additive: ASCII/Greek identifiers parse unchanged.
_SUB = "₀-ₜ²³¹⁰-⁹"
_IDENT = re.compile(r"[A-Za-z_α-ωΑ-Ω][A-Za-z0-9_'α-ωΑ-Ω" + _SUB + r"]*")
_CANON = re.compile(r"\bc\d+\b")
_CANON_TOKEN = re.compile(r"c\d+")

# Lean / Mathlib keywords and lemma-name fragments that are NEVER local identifiers —
# used by the Approach-C pattern normaliser to keep structure while erasing identifiers.
_KEEP = {
    "exact", "exacts", "intro", "intros", "rintro", "simp", "simpa", "rfl", "omega",
    "ring", "ac_rfl", "tauto", "aesop", "funext", "ext", "cases", "rcases", "obtain",
    "left", "right", "constructor", "by", "fun", "using", "with", "at",
    "Or", "And", "Iff", "Set", "Finset", "List", "Nat", "Function", "True", "False",
    "id", "min", "max", "inl", "inr", "mp", "mpr", "symm", "elim", "le", "ge",
    "le_rfl", "le_refl", "le_antisymm", "le_trans", "le_of_eq", "le_total",
    "empty_subset", "union_subset", "subset_inter", "mem_inter", "mem_union",
    "mem_inter_iff", "inter_subset_left", "inter_subset_right", "subset_union_left",
    "subset_union_right", "add_assoc", "add_comm", "mul_comm", "mem_of_mem_inter_left",
    "mem_of_mem_inter_right", "mem_union_left", "mem_union_right", "subset_refl",
    "Subset", "refl", "univ", "trans", "comp_id", "id_comp", "comp_assoc",
    "min_le_left", "min_le_right", "le_max_left", "le_max_right", "Classical", "em",
    "Type", "Prop", "DecidableEq", "Preorder", "PartialOrder", "LinearOrder", "Lattice",
}


@dataclass
class CanonicalMap:
    """Bijection between a theorem's real binder identifiers and canonical slots."""

    real_to_canon: Dict[str, str] = field(default_factory=dict)
    canon_to_real: Dict[str, str] = field(default_factory=dict)
    ok: bool = False  # False => caller should fall back to raw (no canonicalization)


def is_valid_lean_ident(name: str) -> bool:
    return bool(_IDENT.fullmatch(name)) and name not in _KEEP


def parse_binders(statement: str) -> List[str]:
    """Ordered list of binder identifier names from a theorem *statement* of the form
    ``(a b : T) [Inst α] (h : ...) : goal``. Instance binders ``[...]`` contribute no
    new name (their type vars are already bound earlier). Returns names in source
    order; duplicates collapsed keeping first occurrence."""
    names: List[str] = []
    seen = set()
    depth = 0
    i, n = 0, len(statement)
    # binder region = up to the first depth-0 ':' (the goal separator)
    end = n
    d = 0
    for j, ch in enumerate(statement):
        if ch in "([":
            d += 1
        elif ch in ")]":
            d -= 1
        elif ch == ":" and d == 0:
            end = j
            break
    region = statement[:end]
    # scan balanced ( ) groups; '[' instance groups are skipped
    i = 0
    while i < len(region):
        ch = region[i]
        if ch == "(":
            d = 1
            j = i + 1
            while j < len(region) and d > 0:
                if region[j] == "(":
                    d += 1
                elif region[j] == ")":
                    d -= 1
                j += 1
            group = region[i + 1:j - 1]  # inside parens
            # names are tokens before the first ':' in the group
            colon = group.find(":")
            head = group if colon < 0 else group[:colon]
            for tok in head.split():
                if _IDENT.fullmatch(tok) and tok not in seen:
                    names.append(tok)
                    seen.add(tok)
            i = j
        elif ch == "[":
            d = 1
            j = i + 1
            while j < len(region) and d > 0:
                if region[j] == "[":
                    d += 1
                elif region[j] == "]":
                    d -= 1
                j += 1
            i = j  # skip instance binder entirely
        else:
            i += 1
    return names


def build_canonical_map(statement: str, state_before: str = "") -> CanonicalMap:
    """Assign canonical slots ``c0, c1, …`` to the statement's binder identifiers in
    order. Returns ``ok=False`` (identity / no canonicalization) if there are no binders
    or if a binder is already named like a canonical slot (collision → fall back)."""
    names = parse_binders(statement)
    if not names:
        return CanonicalMap(ok=False)
    if any(_CANON.fullmatch(nm) for nm in names):
        return CanonicalMap(ok=False)  # collision with the canonical namespace
    r2c = {nm: f"c{i}" for i, nm in enumerate(names)}
    c2r = {v: k for k, v in r2c.items()}
    return CanonicalMap(real_to_canon=r2c, canon_to_real=c2r, ok=True)


def _replace_idents(text: str, mapping: Dict[str, str]) -> str:
    """Word-boundary replace every identifier token present in ``mapping``; leave all
    other tokens (keywords, lemma names, introduced names) untouched."""
    if not mapping:
        return text
    def repl(m):
        tok = m.group(0)
        return mapping.get(tok, tok)
    return _IDENT.sub(repl, text)


def canonicalize_text(text: str, cmap: CanonicalMap) -> str:
    """Rewrite real binder identifiers → canonical slots in any text (statement / state
    / tactic). No-op if ``cmap.ok`` is False."""
    if not cmap.ok:
        return text
    return _replace_idents(text, cmap.real_to_canon)


def concretize_or_reject(canonical_tactic: str, cmap: CanonicalMap) -> Optional[str]:
    """Invert canonicalization on a model-generated tactic. Returns the concretized
    tactic, or ``None`` if it references a canonical slot (`cN`) that has no real
    binder (the safety gate that prevents the v19 unresolved-placeholder failure).
    Tactic-introduced names (not `cN`) pass through unchanged."""
    if not cmap.ok:
        return canonical_tactic
    # any cN token must be mapped
    for m in _CANON_TOKEN.finditer(canonical_tactic):
        if m.group(0) not in cmap.canon_to_real:
            return None
    return _replace_idents(canonical_tactic, cmap.canon_to_real)


def canonicalize_example(statement: str, state_before: str, tactic: str):
    """Canonicalize a full training example. Returns
    ``(canon_statement, canon_state, canon_tactic, cmap)``. If ``cmap.ok`` is False the
    originals are returned unchanged (the row trains as raw)."""
    cmap = build_canonical_map(statement, state_before)
    return (canonicalize_text(statement, cmap), canonicalize_text(state_before, cmap),
            canonicalize_text(tactic, cmap), cmap)


def tactic_pattern(tactic: str) -> str:
    """Approach C — identifier-free pattern for RANKING ONLY (never output). Replaces
    local identifiers (lowercase / `h`-prefixed, not a Lean/Mathlib keyword or a
    dotted/Capitalised name) with ``ID``; keeps lemma names, operators, projections."""
    def repl(m):
        tok = m.group(0)
        if tok in _KEEP or tok[0].isupper():
            return tok
        return "ID"
    return _IDENT.sub(repl, tactic)


__all__ = [
    "CanonicalMap", "is_valid_lean_ident", "parse_binders", "build_canonical_map",
    "canonicalize_text", "concretize_or_reject", "canonicalize_example", "tactic_pattern",
]
