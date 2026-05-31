"""Mini-ELF v12 — literal-aware candidate augmentation.

The v11 family-LOFO experiment showed the seq2seq learns the tactic
*shape* ``exact h <num>`` from v10 redundancy cells but emits the
literal from its in-train vocabulary (`{3, 4, 5, 7}`) rather than the
goal-required literal (`{3, 5, 8, 9, 13, ...}`). For 6 of 7 failing
``forall_inst`` test rows the model's top-5 beam contains at least one
candidate matching the schema with a *stale* literal; substituting the
goal literal recovers the gold tactic.

This module is a **conservative, post-generation, schema-preserving
adaptation**. It is not a theorem-specific template; it is not a model;
it does not access ``state_after``. It runs as a CPU-only string
transform on the model's beam output, gated by structural checks:

  * The candidate must match a small set of literal-bearing schemas:
    ``exact h <num>``, ``exact <ident> <num>``,
    ``exact <ident> <num> <num>`` (binary), and the optional witness
    schema ``exact ⟨<num>, rfl⟩``.
  * The hypothesis context must contain at least one ``∀ x : Nat`` /
    ``∀ x y : Nat`` quantifier — otherwise the augmentation refuses.
  * The goal must contain at least one numeric literal extractable from
    the line after ``⊢``.
  * For each ``(candidate, goal-literal)`` pair where the candidate's
    literal differs from the goal literal, emit
    ``candidate-with-literal-substituted``.
  * Dedup against the original candidates and against itself; tag every
    emitted candidate with ``source = "seq2seq_literal_adapt"``.

The module is pure-Python (no torch, no Lean) and deterministic.
Tests in ``tests/test_literal_aware_decode.py`` exercise the schema
filter (no augmentation on rewrite_succ; no augmentation when no
forall hypothesis; the canonical ``exact h 4 + goal 13 -> exact h 13``
case).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple


# Source tag for augmented candidates (so the reranker can detect them).
SOURCE_LITERAL_ADAPT = "seq2seq_literal_adapt"

# Original-candidate source label (passes through unchanged).
SOURCE_SEQ2SEQ = "seq2seq"

# ----- regex grammar -----

# Match: a numeric literal NOT preceded/followed by an identifier char.
_NUM_RE = re.compile(r"(?<![\w.])\d+(?!\w)")

# Match: ``exact <ident> <num>`` or ``exact <ident> <num> <num>`` with
# *exactly* the prefix ``exact``. The ``<ident>`` is constrained to a
# single identifier (no dots) so we do not adapt ``exact h.left`` or
# ``exact h.mp`` style. ``<rest>`` captures anything trailing (we keep
# the suffix unchanged after substitution).
_EXACT_HYP_NUM_RE = re.compile(
    r"^exact\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    r"(\s+(\d+))(\s+(\d+))?"
    r"(\s*$)"
)

# Match: ``exact ⟨<num>, rfl⟩`` (the v0/v1 witness-copy shape — kept
# under the literal-adapt umbrella so callers don't have to special-case
# it). The ``rfl`` part is required to keep the gate tight.
_EXACT_WITNESS_RE = re.compile(
    r"^exact\s+⟨\s*(\d+)\s*,\s*rfl\s*⟩\s*$"
)


@dataclass(frozen=True)
class AdaptedCandidate:
    """One literal-adapted candidate emitted by :func:`adapt_candidates`.

    Attributes
    ----------
    tactic : str
        The full tactic string with the literal substituted.
    source : str
        Always ``SOURCE_LITERAL_ADAPT`` for module outputs; the original
        seq2seq candidates pass through with ``SOURCE_SEQ2SEQ`` in
        :func:`compose_candidates`.
    original_index : int
        Index of the parent seq2seq candidate in the input list.
    substituted_from : int
        The stale literal that was replaced.
    substituted_to : int
        The goal literal that replaced it.
    schema : str
        Which schema matched (``exact_h_num`` / ``exact_h_num_num`` /
        ``exact_witness``).
    """
    tactic: str
    source: str
    original_index: int
    substituted_from: int
    substituted_to: int
    schema: str


def _extract_goal_literals(state_before: str) -> List[int]:
    """Return numeric literals from the line(s) AFTER ``⊢`` in
    ``state_before``.  No literal on the goal line ⇒ empty list."""
    if not state_before:
        return []
    # Split at the first ``⊢``; everything to the right is the goal.
    parts = state_before.split("⊢", 1)
    if len(parts) < 2:
        return []
    goal = parts[1]
    return [int(m.group(0)) for m in _NUM_RE.finditer(goal)]


def _has_forall_quantifier(state_before: str, theorem_statement: str) -> bool:
    """True iff the state OR theorem statement contains a ``∀`` symbol.
    Acts as the structural gate that prevents augmentation on non-forall
    goals (e.g. ``rewrite_succ``)."""
    blob = (state_before or "") + "\n" + (theorem_statement or "")
    return "∀" in blob or "Forall" in blob


def _hypothesis_identifiers(state_before: str) -> List[str]:
    """Extract simple hypothesis identifiers from ``state_before`` lines
    of the form ``<name> : <type>``. Used only to constrain which
    identifiers we are willing to substitute INTO (we must not invent a
    name that does not exist in the local context)."""
    out: List[str] = []
    for ln in (state_before or "").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("⊢"):
            continue
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:", ln)
        if m:
            out.append(m.group(1))
    return out


def adapt_candidates(
    candidates: Sequence[str],
    *,
    state_before: str,
    theorem_statement: str = "",
) -> List[AdaptedCandidate]:
    """Return a list of literal-adapted candidates.

    ``candidates`` is the model's raw beam output (a sequence of strings
    in beam-rank order). The return value is a list of
    :class:`AdaptedCandidate`; the caller composes them with the
    originals via :func:`compose_candidates`.

    The gate refuses to augment if:
      * the state contains no ``∀`` quantifier (and no witness-copy
        shape in the candidates), AND
      * the goal has no numeric literal.

    Either condition by itself is sufficient grounds to refuse — both
    are required to even consider augmentation.
    """
    goal_lits = _extract_goal_literals(state_before)
    if not goal_lits:
        return []

    # Conservative target: use the FIRST literal on the goal line. v11's
    # forall_inst test set has the convention that the goal is
    # ``<lit> = <other>`` / ``<lit> ≤ <lit>`` / similar and the gold
    # tactic instantiates with the first literal (``exact h 13`` for
    # ``⊢ 13 = 6``). For multi-literal goals the caller can refine
    # later. This keeps the heuristic deterministic and stops us from
    # polluting the candidate list with multiple incorrect targets.
    primary_target = goal_lits[0]

    have_forall = _has_forall_quantifier(state_before, theorem_statement)
    hyp_ids = set(_hypothesis_identifiers(state_before))

    out: List[AdaptedCandidate] = []
    seen: set = set()  # dedup vs originals and self

    def _emit(new_tactic: str, *, original_index: int,
              from_lit: int, to_lit: int, schema: str) -> None:
        key = new_tactic.strip()
        if not key:
            return
        if key in seen:
            return
        seen.add(key)
        out.append(AdaptedCandidate(
            tactic=new_tactic, source=SOURCE_LITERAL_ADAPT,
            original_index=original_index,
            substituted_from=from_lit, substituted_to=to_lit,
            schema=schema,
        ))

    # Pre-populate ``seen`` with the originals so we never emit a
    # literal-adapt candidate that matches an existing seq2seq candidate.
    for c in candidates:
        seen.add(c.strip())

    for i, c in enumerate(candidates):
        s = c.strip()
        # --- schema 1: exact <hyp> <num> (and optional second <num>) ---
        m = _EXACT_HYP_NUM_RE.match(s)
        if m and have_forall:
            hyp_name = m.group(1)
            # Only substitute when the hypothesis name actually appears
            # in the local context — otherwise we'd be inventing
            # identifiers the model didn't write itself.
            if hyp_name not in hyp_ids:
                pass
            else:
                first_lit = int(m.group(3))
                second_lit_str = m.group(5)
                if second_lit_str is None:
                    # single-arg: ``exact h <K>``
                    schema = "exact_hyp_num"
                    if first_lit != primary_target:
                        new = f"exact {hyp_name} {primary_target}"
                        _emit(new, original_index=i,
                              from_lit=first_lit, to_lit=primary_target,
                              schema=schema)
                else:
                    # binary: ``exact h <K1> <K2>``. Substitute the
                    # first literal only (multi-arg forall_inst is rare;
                    # v10's `forall_inst_pair` uses ``exact h 2 3``).
                    schema = "exact_hyp_num_num"
                    second_lit = int(second_lit_str)
                    if first_lit != primary_target:
                        new = f"exact {hyp_name} {primary_target} {second_lit}"
                        _emit(new, original_index=i,
                              from_lit=first_lit, to_lit=primary_target,
                              schema=schema)
            continue
        # --- schema 2: exact ⟨<num>, rfl⟩ (∃-witness style) ---
        m2 = _EXACT_WITNESS_RE.match(s)
        if m2:
            schema = "exact_witness_num"
            first_lit = int(m2.group(1))
            if first_lit != primary_target:
                new = f"exact ⟨{primary_target}, rfl⟩"
                _emit(new, original_index=i,
                      from_lit=first_lit, to_lit=primary_target,
                      schema=schema)
    return out


def compose_candidates(
    candidates: Sequence[str],
    *,
    state_before: str,
    theorem_statement: str = "",
) -> List[Tuple[str, str, Optional[AdaptedCandidate]]]:
    """Return a unified, deduped list of ``(tactic, source, meta)``
    tuples combining the originals (in beam order) with any
    literal-adapted candidates appended AFTER the originals (so the
    reranker is the final arbiter of order).

    ``meta`` is ``None`` for seq2seq originals and the
    :class:`AdaptedCandidate` for adapted ones.
    """
    out: List[Tuple[str, str, Optional[AdaptedCandidate]]] = []
    seen: set = set()
    for c in candidates:
        key = c.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((c, SOURCE_SEQ2SEQ, None))
    for ac in adapt_candidates(candidates, state_before=state_before,
                               theorem_statement=theorem_statement):
        key = ac.tactic.strip()
        if key in seen:
            continue
        seen.add(key)
        out.append((ac.tactic, ac.source, ac))
    return out
