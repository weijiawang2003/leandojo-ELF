"""Mini-ELF v1 — copy/pointer-inspired witness-candidate augmentation.

A pragmatic, *symbolic* augmentation (not a neural pointer network) for the one
family the flow decoder and AR model both fail on: existential goals whose proof
is ``exact ⟨W, rfl⟩`` for some witness ``W`` that is *literally present in the
prompt*. v0/AR cannot reliably emit ``5``/``7`` for ``exists_nat_5/7``; copying
the literal out of ``∃ n : Nat, n = 5`` makes the right candidate trivially
available.

Mechanism:

  1. Parse the state (:mod:`mini_elf_lean.elf_structure`).
  2. Only fire when the goal is existential (or the pattern family says so).
  3. Collect candidate witnesses: numeric literals copied from the prompt, value
     identifiers from the hypotheses (e.g. ``a : α`` -> ``a`` for
     ``∃ x : α, x = a``), and — only as a fallback when no literal is found and
     the existential is over ``Nat``/``ℕ`` — the small defaults ``0``/``1``.
  4. For each witness emit ``exact ⟨W, rfl⟩`` and ``refine ⟨W, ?_⟩\\n  rfl``.

This is honest: it is an explicit symbolic candidate source, deduplicated and
evaluated by the *same* lean-cli verifier as every other candidate, and tagged
``witness_copy`` in the predictions so its contribution is auditable. It reads
only ``theorem_statement`` + ``state_before`` — never ``state_after``.
"""

from __future__ import annotations

from typing import List, Optional

from .elf_structure import EXISTS_GOAL, StructuredState, parse_prompt

WITNESS_SOURCE = "witness_copy"

# Tactic templates instantiated per witness. ``{w}`` is the witness token.
_TEMPLATES = ("exact ⟨{w}, rfl⟩", "refine ⟨{w}, ?_⟩\n  rfl")

# Fallback witnesses for an existential over Nat when nothing is copyable.
_NAT_DEFAULTS = ("0", "1")
_NAT_TYPES = ("Nat", "ℕ")

# Cap on distinct witnesses so a pathological prompt can't blow up candidate count.
_MAX_WITNESSES = 6


def _is_exists(state: StructuredState, family: Optional[str]) -> bool:
    if state.goal_shape == EXISTS_GOAL:
        return True
    fam = (family or state.pattern_family or "").lower()
    return "exists" in fam


def collect_witnesses(state: StructuredState, family: Optional[str] = None) -> List[str]:
    """Ordered, deduplicated list of candidate witness tokens for ``state``.

    Empty unless the goal is existential. Numeric literals first (most likely the
    intended copy), then value identifiers, then Nat fallbacks."""
    if not _is_exists(state, family):
        return []
    witnesses: List[str] = []
    seen: set = set()

    def add(tok: str) -> None:
        if tok and tok not in seen:
            seen.add(tok)
            witnesses.append(tok)

    for lit in state.numeric_literals:
        add(lit)
    for ident in state.value_witnesses:
        add(ident)
    if not state.numeric_literals and any(t in state.goal for t in _NAT_TYPES):
        for d in _NAT_DEFAULTS:
            add(d)
    return witnesses[:_MAX_WITNESSES]


def generate_witness_candidates(
    state: StructuredState, family: Optional[str] = None
) -> List[str]:
    """Witness tactic strings for ``state`` (deduplicated, deterministic order).
    Empty list for non-existential goals."""
    out: List[str] = []
    seen: set = set()
    for w in collect_witnesses(state, family):
        for tmpl in _TEMPLATES:
            tac = tmpl.format(w=w)
            if tac not in seen:
                seen.add(tac)
                out.append(tac)
    return out


def witness_candidates_for(
    theorem_statement: str, state_before: str, family: Optional[str] = None
) -> List[str]:
    """Parse a ``(theorem_statement, state_before)`` prompt and return its
    witness candidates. Convenience wrapper used by the v1 sampler."""
    state = parse_prompt(theorem_statement, state_before, pattern_family=family)
    return generate_witness_candidates(state, family)
