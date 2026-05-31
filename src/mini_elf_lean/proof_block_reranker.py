"""Mini-ELF v12 — rule-based candidate reranker.

The v11 family-LOFO experiment showed two ranking failures:

  1. *Beam-rank failure*. The model emits ``exact h 4`` and
     ``exact h 7`` ahead of ``exact h 3`` for a goal whose literal is 3,
     even though the correct tactic exists in the beam. A
     goal-literal-aware reranker boosts the candidate whose first
     numeric literal matches the goal's first numeric literal.

  2. *Stale-literal noise*. Candidates of the form ``exact h <K>``
     where K is in the train-pool vocabulary but ≠ goal-literal should
     be penalised so they fall below adapted candidates and below
     anything else that matches the goal.

This module implements a small, transparent, hand-coded reranker
operating only on:

  * the candidate string,
  * the candidate's source tag (``seq2seq`` / ``seq2seq_literal_adapt``
    from :mod:`mini_elf_lean.literal_aware_decode`),
  * the goal text (split out of ``state_before``),
  * an optional ``required_operation`` tag.

It does **not** access ``state_after``, run Lean, or use a learned
model. Outputs are a stable sort of the input list. The score is a
sum of feature contributions; ties broken by the original beam rank.

Tests in ``tests/test_proof_block_reranker.py`` exercise:

  * the canonical ``exact h 13 ranks above exact h 7`` case
    when the goal literal is 13,
  * non-regression for ``rw [h]`` candidates (they're not demoted),
  * malformed candidates (``exact h.``, ``rw [hns``) penalised,
  * literal_adapt candidates preferred over seq2seq when the seq2seq
    candidate has a stale literal,
  * source metadata round-trips through the reranker unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

from .literal_aware_decode import (
    SOURCE_LITERAL_ADAPT,
    SOURCE_SEQ2SEQ,
)


# --- shared regex grammar -----------------------------------------------------

_NUM_RE = re.compile(r"(?<![\w.])\d+(?!\w)")

# A coarse "malformed" detector for the v8/v10/v11 failure mode 1
# (char-level truncation: ``exact h.``, ``rw [hns``, ``cases h with | inl hp => exa``).
# The patterns target the tail of the candidate.
_TRAILING_PUNCT_RE = re.compile(r"[\.\[⟨,]$")
_INCOMPLETE_BRACKET_RE = re.compile(r"\[[^\]]*$")  # ``rw [hns`` (unclosed)
_INCOMPLETE_ANGLE_RE = re.compile(r"⟨[^⟩]*$")     # ``exact ⟨6, rfl`` (no closing ⟩)
_INCOMPLETE_WITH_RE = re.compile(r"\bwith\s*$")    # ``cases h with`` (no clause)
_DOTTED_TRAIL_RE = re.compile(r"\.\w{0,3}$")     # ``exact h.``, ``exact h.se``

_KNOWN_HEAD_OPS = {
    "exact", "rw", "intro", "cases", "rcases", "constructor",
    "apply", "refine", "exfalso", "absurd", "trivial", "rfl",
    "simp", "subst", "show", "have", "specialize",
}


@dataclass(frozen=True)
class RerankFeatures:
    """Per-candidate features the reranker computes.

    The reranker computes a real-valued ``score`` from these and uses it
    for the stable sort; the features are also returned so the eval
    driver can log them.
    """
    goal_literal_match: bool   # True if any candidate literal == primary goal literal
    has_stale_literal: bool    # True if candidate has numeric literal but none matches goal
    is_malformed: bool         # truncation / incomplete bracket / dotted tail
    schema_match_score: float  # bonus when candidate head matches the required_operation
    is_literal_adapt: bool     # source == seq2seq_literal_adapt
    length: int                # candidate length (shorter preferred, but not for stale)
    has_known_head: bool       # candidate begins with a recognised tactic head
    beam_rank: int             # original input position
    score: float               # the combined score (higher = better)


def _first_goal_literal(state_before: str) -> Optional[int]:
    if not state_before:
        return None
    parts = state_before.split("⊢", 1)
    if len(parts) < 2:
        return None
    for m in _NUM_RE.finditer(parts[1]):
        return int(m.group(0))
    return None


def _candidate_literals(cand: str) -> List[int]:
    return [int(m.group(0)) for m in _NUM_RE.finditer(cand)]


def _candidate_head(cand: str) -> str:
    s = cand.strip()
    if not s:
        return ""
    head = s.split(None, 1)[0]
    # strip trailing punctuation from heads like ``rw[`` (rare)
    head = head.rstrip(".[(:|⟨,")
    return head


def _is_malformed(cand: str) -> bool:
    s = cand.strip()
    if not s:
        return True
    last_line = s.splitlines()[-1].rstrip()
    if not last_line:
        return True
    if _TRAILING_PUNCT_RE.search(last_line):
        return True
    if _INCOMPLETE_BRACKET_RE.search(last_line):
        return True
    if _INCOMPLETE_ANGLE_RE.search(last_line):
        return True
    if _INCOMPLETE_WITH_RE.search(last_line):
        return True
    # ``exact h.``, ``exact h.s`` (short dotted tail) — but not ``exact h.left``
    if _DOTTED_TRAIL_RE.search(last_line):
        # allow well-known field names that aren't truncations
        tail = last_line.rsplit(".", 1)[-1]
        if tail in {"left", "right", "elim", "mp", "mpr", "symm", "trans"}:
            return False
        if not tail or len(tail) < 4:
            return True
    return False


# Schema-match: a coarse mapping from ``required_operation`` (used by
# v8/v10/v11) to the expected head token(s) for that operation's gold
# tactics.
_OP_TO_HEADS = {
    "instantiate_forall": {"exact"},
    "contradiction":      {"exact", "exfalso", "absurd"},
    "rewrite":            {"rw", "exact", "subst", "simp", "simpa"},
    "rewrite_eq":         {"rw", "exact", "subst", "simp", "simpa"},
    "exists_elim":        {"cases", "exact", "rcases"},
    "exists_reconstruct": {"cases", "exact", "rcases"},
    "implication_chain":  {"exact", "intro", "apply", "refine"},
    "intro_negation":     {"intro", "exact"},
    "conjunction_projection": {"exact"},
    "disjunction_cases":  {"cases", "exact", "rcases"},
}


def _schema_score(cand_head: str, required_op: Optional[str]) -> float:
    if not required_op or required_op == "unknown":
        return 0.0
    heads = _OP_TO_HEADS.get(required_op, set())
    if not heads:
        return 0.0
    return 0.4 if cand_head in heads else 0.0


# --- public reranker --------------------------------------------------------


@dataclass
class RerankedCandidate:
    tactic: str
    source: str
    features: RerankFeatures


# Score weights — chosen to make the canonical
# ``exact h 13 > exact h 7`` case win robustly while not demoting
# unrelated tactic shapes (e.g. ``rw [h]`` for rewrite_succ).
_W_GOAL_LITERAL_MATCH = 2.0
_W_STALE_LITERAL      = -1.0   # penalty
_W_MALFORMED          = -2.0   # strong penalty
_W_LITERAL_ADAPT      =  0.5   # gentle prior on the post-processing source
_W_SHORT_AND_CLEAN    =  0.15  # length tie-break; small
_W_KNOWN_HEAD         =  0.2
# Beam rank is incorporated as a tiny tie-breaker so the sort is stable
# (lower beam_rank = higher score). The magnitude is small enough that
# any feature delta wins over a beam-rank difference.
_W_BEAM_RANK_INV      = 0.01


def score_candidate(
    cand: str,
    *,
    source: str,
    beam_rank: int,
    goal_literal: Optional[int],
    required_operation: Optional[str] = None,
) -> RerankFeatures:
    cand_lits = _candidate_literals(cand)
    has_lit_match = goal_literal is not None and goal_literal in cand_lits
    has_stale = (goal_literal is not None and cand_lits
                 and goal_literal not in cand_lits)
    malformed = _is_malformed(cand)
    head = _candidate_head(cand)
    schema_match = _schema_score(head, required_operation)
    is_lit_adapt = source == SOURCE_LITERAL_ADAPT
    has_known = head in _KNOWN_HEAD_OPS

    score = 0.0
    if has_lit_match:
        score += _W_GOAL_LITERAL_MATCH
    if has_stale:
        score += _W_STALE_LITERAL
    if malformed:
        score += _W_MALFORMED
    if is_lit_adapt:
        score += _W_LITERAL_ADAPT
    if has_known:
        score += _W_KNOWN_HEAD
    score += schema_match
    # Length: prefer shorter NON-stale, well-formed candidates by a small
    # margin. Length is in characters; we bias against the very long
    # ``rcases h with ⟨n, hn⟩\n  exact …`` style.
    if not (has_stale or malformed):
        # shorter is better; map to [0, _W_SHORT_AND_CLEAN]
        length_norm = max(0.0, 1.0 - (len(cand) / 80.0))
        score += _W_SHORT_AND_CLEAN * length_norm
    # Stable tie-break: prefer earlier beam positions when scores are
    # otherwise equal. Negative coefficient on beam_rank.
    score -= _W_BEAM_RANK_INV * beam_rank

    return RerankFeatures(
        goal_literal_match=has_lit_match,
        has_stale_literal=has_stale,
        is_malformed=malformed,
        schema_match_score=schema_match,
        is_literal_adapt=is_lit_adapt,
        length=len(cand),
        has_known_head=has_known,
        beam_rank=beam_rank,
        score=score,
    )


def rerank(
    candidates: Sequence[tuple],  # iterable of (tactic, source) OR (tactic, source, meta)
    *,
    state_before: str = "",
    required_operation: Optional[str] = None,
) -> List[RerankedCandidate]:
    """Return ``candidates`` sorted by descending score.

    ``candidates`` may be either:
      * a list of plain strings (legacy callers; source defaults to
        ``seq2seq``);
      * a list of ``(tactic, source)`` tuples;
      * a list of ``(tactic, source, meta)`` tuples (the
        :func:`literal_aware_decode.compose_candidates` output);

    The sort is stable; equal-score candidates keep their input order.
    """
    goal_lit = _first_goal_literal(state_before)
    normalised: List[tuple] = []
    for i, item in enumerate(candidates):
        if isinstance(item, str):
            tactic, source = item, SOURCE_SEQ2SEQ
        elif len(item) == 2:
            tactic, source = item
        else:
            tactic, source, _meta = item[0], item[1], item[2:]
        feats = score_candidate(
            tactic, source=source, beam_rank=i,
            goal_literal=goal_lit, required_operation=required_operation,
        )
        normalised.append((tactic, source, feats))
    # Stable descending sort by score.
    normalised.sort(key=lambda t: -t[2].score)
    return [RerankedCandidate(tactic=t, source=s, features=f)
            for (t, s, f) in normalised]
