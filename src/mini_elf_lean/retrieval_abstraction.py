"""Mini-ELF v7 — operation-level *abstraction* of verified tactic blocks.

v6 retrieval ranks donors by char-similarity + structural features, but it still
fundamentally **reuses a donor tactic string**. When the correct proof *family*
is absent from the donor pool (the v7 family/operation-holdout regime), the
nearest donor is from a *different* family and its concrete identifiers/literals
are wrong, so the verbatim string fails. The honest, template-free lever is to
abstract a tactic to the *operation* it performs — which hypothesis **roles** and
which literal slots it consumes — so retrieval can match a cross-family donor
that performs the *same operation* even when no same-family donor exists.

Examples (the brief's three):

  * ``exact h 13``              -> ``exact <forall_hyp> <num>``
  * ``rw [h]``                  -> ``rw [<eq_hyp>]``
  * ``rcases h with ⟨x, hx⟩``   -> ``rcases <exists_hyp> with ⟨<id>, <id>⟩``

Roles come from the hypothesis *types* in ``state_before`` (a ``∀``-typed hyp is
``<forall_hyp>``, a ``= ``-typed hyp ``<eq_hyp>``, …). Standalone integer literals
become ``<num>``; bound/unknown identifiers become ``<id>``. Lean keywords and
tactic punctuation are preserved. Heuristic string parsing only — **no Lean
AST**, **never** reads ``state_after``. Pure-Python / torch-free.

This module supplies the *primitives* (``abstract_tactic``, ``tactic_head``,
``operation_signature``, ``signatures_match``) used by the v7 donor audit, the
abstraction-aware retrieval re-ranker, and the (optional) learned scorer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional

from .elf_structure import _depth0_find, extract_hypotheses, parse_binding

# ---- hypothesis roles (priority order: the first that matches wins) ----
ROLE_FORALL = "forall"
ROLE_EXISTS = "exists"
ROLE_NEG = "neg"
ROLE_IMP = "imp"
ROLE_EQ = "eq"
ROLE_AND = "and"
ROLE_OR = "or"
ROLE_PROP = "prop"

_ROLE_ORDER = (ROLE_FORALL, ROLE_EXISTS, ROLE_NEG, ROLE_IMP, ROLE_EQ, ROLE_AND, ROLE_OR, ROLE_PROP)

# Tactic vocabulary kept verbatim in an abstract signature (structure, not data).
_KEYWORDS: FrozenSet[str] = frozenset({
    "exact", "rw", "rfl", "rcases", "obtain", "intro", "intros", "apply", "refine",
    "constructor", "cases", "with", "at", "absurd", "elim", "left", "right", "by",
    "fun", "trivial", "contradiction", "simp", "omega", "decide", "assumption",
    "exfalso", "Or", "And", "Exists", "False", "True", "show", "from", "have",
})
# Builtin types are not proof hypotheses, so a binding `(n : Nat)` does not make
# `n` a role placeholder — it stays an `<id>`.
_BUILTIN_TYPES = frozenset({"Prop", "Type", "Sort", "Type*", "Nat", "ℕ", "Int", "ℤ", "Bool"})

# A standalone non-negative integer (not glued to a word char or a `.` — so `h.1`
# projections are NOT literals). Mirrors retrieval_proposer._NUM_RE.
_NUM_RE = re.compile(r"(?<![\w.])\d+(?!\w)")
# Lean identifiers (may carry `'` and dotted projections like `False.elim`, `h.1`).
_IDENT_RE = re.compile(r"[A-Za-z_][\w']*(?:\.[A-Za-z0-9_']+)*")


def _classify_role(ty: str) -> str:
    """Map a hypothesis *type* to its proof role (priority-ordered)."""
    t = ty.strip()
    if "∀" in t:
        return ROLE_FORALL
    if t.startswith("∃") or t.startswith("Exists"):
        return ROLE_EXISTS
    if t.startswith("¬") or "→ False" in t or "→False" in t or "¬" in t:
        return ROLE_NEG
    if _depth0_find(t, "→") >= 0:
        return ROLE_IMP
    if _depth0_find(t, "=") >= 0:
        return ROLE_EQ
    if _depth0_find(t, "∧") >= 0:
        return ROLE_AND
    if _depth0_find(t, "∨") >= 0:
        return ROLE_OR
    return ROLE_PROP


def hyp_roles(state_before: str) -> Dict[str, str]:
    """``{hypothesis_name: role}`` parsed from ``state_before``. Type/value
    declarations (``n : Nat``, ``p : Prop``) are skipped — they are not proof
    hypotheses, so their binder names stay ``<id>`` rather than a role slot."""
    out: Dict[str, str] = {}
    try:
        for line in extract_hypotheses(state_before):
            b = parse_binding(line)
            if b is None:
                continue
            names, ty = b
            ty = ty.strip()
            if ty in _BUILTIN_TYPES or ty.startswith("Type") or ty == "Sort":
                continue
            role = _classify_role(ty)
            for n in names:
                out[n] = role
    except Exception:  # noqa: BLE001 - abstraction must never crash retrieval
        return {}
    return out


def tactic_head(tactic: str) -> str:
    """The leading tactic keyword (``exact``, ``rw``, ``rcases``, …). Empty for a
    blank tactic. Multi-line blocks use the first line's head."""
    first = tactic.strip().splitlines()[0] if tactic.strip() else ""
    m = _IDENT_RE.match(first.strip())
    return m.group(0).split(".")[0] if m else ""


def abstract_tactic(tactic: str, state_before: str) -> str:
    """Replace concrete data in ``tactic`` with role/slot placeholders.

    Hypothesis names -> ``<role_hyp>`` (role from their type in ``state_before``);
    standalone integers -> ``<num>``; other lower-case identifiers (bound vars,
    unknown locals) -> ``<id>``; Lean keywords, dotted lemmas (``False.elim``) and
    punctuation are preserved. Whitespace is collapsed so multi-line blocks
    compare structurally."""
    roles = hyp_roles(state_before)

    def repl_ident(m: re.Match) -> str:
        tok = m.group(0)
        base = tok.split(".")[0]
        if base in roles:
            # keep any dotted projection suffix abstract too: `h.1` -> `<and_hyp>.1`
            suffix = tok[len(base):]
            return f"<{roles[base]}_hyp>{suffix}"
        if tok in _KEYWORDS or base in _KEYWORDS:
            return tok
        if "." in tok and tok[0].isupper():
            return tok  # dotted lemma like False.elim / Or.inl — structural
        return "<id>"

    # Idents first (a bare integer cannot start an identifier, so it is untouched
    # by this pass), then numbers — doing numbers first would let the ident pass
    # re-match the letters inside the `<num>` placeholder.
    s = _IDENT_RE.sub(repl_ident, tactic)
    s = _NUM_RE.sub("<num>", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass(frozen=True)
class AbstractSignature:
    """An operation-level fingerprint of a verified tactic block."""

    head: str
    roles: FrozenSet[str]            # hypothesis roles the tactic consumes
    has_num: bool                    # consumes a numeric literal slot
    abstract: str                    # the full abstracted tactic string

    def key(self) -> str:
        """A compact, hashable cluster key: head + sorted roles + num flag."""
        return f"{self.head}|{'+'.join(sorted(self.roles))}|{int(self.has_num)}"


def operation_signature(tactic: str, state_before: str) -> AbstractSignature:
    """Build the :class:`AbstractSignature` for a ``(tactic, state)`` pair."""
    abstract = abstract_tactic(tactic, state_before)
    roles = frozenset(
        r for r in _ROLE_ORDER if f"<{r}_hyp>" in abstract
    )
    return AbstractSignature(
        head=tactic_head(tactic),
        roles=roles,
        has_num="<num>" in abstract,
        abstract=abstract,
    )


def signatures_match(a: AbstractSignature, b: AbstractSignature, *, strict: bool = False) -> bool:
    """Do two operation signatures describe the *same* proof operation?

    ``strict`` requires identical abstract strings (same structure exactly). The
    default (loose) match requires the same tactic head **and** the same set of
    hypothesis roles — enough to say "both instantiate a ∀-hypothesis with a
    number" while tolerating cosmetic differences (bound-var names, literal
    presence)."""
    if strict:
        return a.abstract == b.abstract
    return a.head == b.head and a.roles == b.roles


def schema_of(tactic: str, state_before: str) -> str:
    """Shorthand: the abstract tactic string (the proof *schema*)."""
    return abstract_tactic(tactic, state_before)
