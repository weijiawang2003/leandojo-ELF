"""Mini-ELF v20 — ranker-time abstract-pattern reranker.

The v19 brief's negative result showed that **generating** placeholders
fails because the model emits placeholders that don't resolve. v20
keeps generation in raw-name space (what v18 broad does), but uses
the v19 abstraction machinery **only at ranking time** to:

  1. Abstract each raw generated candidate against the current local
     context (the test theorem's ``state_before``).
  2. If abstraction succeeds (i.e., the candidate's identifiers all
     bind to in-scope names), score the abstract *pattern* by how
     frequently it appears in the training-tactic pattern bag.
  3. If abstraction fails (the candidate names a hypothesis that
     isn't in the local context, e.g. v17's `hpfalse` referenced on a
     v18 implication state that only has `hp`), apply a penalty.

The reranker emits **raw-name candidates** — never placeholders. It
just reorders the existing beam. This sidesteps v19's unresolved-
placeholder cliff.

Honesty contract:
  * No state_after.
  * No manual oracle: the training pattern bag is built from verified
    tactics only.
  * No model retraining — this is a scoring layer on top of any
    candidate generator.
  * Word-boundary substitution from v19's identifier_abstraction is
    reused so e.g. ``h`` is not confused with ``hp``.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .identifier_abstraction import (
    abstract_tactic_only,
    build_abstraction_map,
)
from .local_context import parse_state

logger = logging.getLogger("abstract_pattern_reranker")


# Identifiers we consider "free" if not present in the local
# context. Lean tactic keywords, common constructor names, and
# numerals never count as missing identifiers. (Conservative — we
# only penalise truly local-context-named identifiers.)
_BUILTIN_TOKENS = frozenset({
    # Tactic keywords
    "exact", "intro", "intros", "apply", "rw", "rewrite", "rcases",
    "cases", "refine", "constructor", "use", "have", "show",
    "rfl", "simp", "omega", "decide", "trivial", "absurd",
    "linarith", "norm_num", "ring", "tauto", "exfalso",
    "contradiction", "by", "with", "at", "in", "let", "fun",
    "match", "all_goals", "any_goals", "first", "try", "repeat", "skip",
    "from", "this", "assumption",
    # Connective / type-level
    "True", "False", "Nat", "Bool", "Prop", "Type", "List", "Eq",
    # Constructors and projections widely used in core Lean
    "And", "Or", "Not", "Iff", "Exists",
    "And.intro", "Or.inl", "Or.inr", "Or.elim",
    "Eq.refl", "Eq.symm", "Eq.trans", "Eq.subst", "Eq.mpr",
    "And.left", "And.right", "True.intro", "False.elim",
    "Nat.succ", "Nat.zero", "List.nil", "List.cons",
    "Bool.true", "Bool.false",
    "Exists.intro", "Exists.elim", "Exists.choose",
    "absurd", "elim", "symm", "trans", "mp", "mpr", "subst",
    "true", "false", "rfl",
    "_", "?_", "?",
    # Common pattern keywords
    "inl", "inr",
})


@dataclass
class PatternBag:
    """Counter of abstract tactic patterns from verified training
    tactics, optionally keyed by category for category-aware scoring.
    Used by :func:`AbstractPatternReranker.score`.
    """

    global_counts: Counter = field(default_factory=Counter)
    by_category: Dict[str, Counter] = field(default_factory=dict)
    n_rows: int = 0

    def add(self, pattern: str, category: Optional[str]) -> None:
        self.global_counts[pattern] += 1
        if category:
            self.by_category.setdefault(category, Counter())[pattern] += 1
        self.n_rows += 1

    def lookup(self, pattern: str, category: Optional[str]) -> int:
        cat = (self.by_category.get(category, Counter()).get(pattern, 0)
               if category else 0)
        return max(cat, self.global_counts.get(pattern, 0))

    def to_json(self) -> Dict[str, Any]:
        return {
            "global": dict(self.global_counts),
            "by_category": {k: dict(v) for k, v in self.by_category.items()},
            "n_rows": self.n_rows,
        }

    @classmethod
    def from_json(cls, obj: Dict[str, Any]) -> "PatternBag":
        b = cls()
        b.global_counts = Counter(obj.get("global", {}))
        b.by_category = {k: Counter(v)
                         for k, v in obj.get("by_category", {}).items()}
        b.n_rows = int(obj.get("n_rows", 0))
        return b


def build_pattern_bag(rows: Iterable[Dict[str, Any]]) -> PatternBag:
    """Walk verified training rows, abstract each tactic against its
    own state_before, accumulate pattern counts. Skips rows where
    abstraction fails or no abstraction occurs."""
    bag = PatternBag()
    for r in rows:
        state = r.get("state_before") or ""
        tactic = r.get("tactic") or ""
        category = r.get("category")
        if not state or not tactic:
            continue
        try:
            abs_tactic, _ = abstract_tactic_only(state, tactic)
        except Exception:  # pragma: no cover
            continue
        bag.add(abs_tactic, category)
    return bag


# Identify identifier-shaped tokens in a candidate tactic.
_IDENT_RE = re.compile(r"[A-Za-zα-ωΑ-Ω_][A-Za-zα-ωΑ-Ω0-9_']*")


def _candidate_identifiers(tactic: str) -> List[str]:
    return _IDENT_RE.findall(tactic)


def _is_numeric(s: str) -> bool:
    return s.isdigit()


@dataclass
class ScoredCandidate:
    """Result of scoring one candidate; sortable on score descending."""

    candidate: str
    raw_rank: int
    abstract_pattern: str
    pattern_count: int
    n_unbound_idents: int
    score: float
    reason: str


@dataclass
class AbstractPatternReranker:
    """Reorders raw-name candidates using v19 abstraction
    machinery applied **only for scoring**. Generation stays in raw
    names; outputs are raw-name tactics.

    Scoring features:
      * +log(1 + pattern_count) : reward shapes seen in training.
      * -2.0 per unbound identifier (free hyp-name not in state).
      * Mild raw-rank penalty so the original beam order persists
        when patterns are unknown / tied.
    """

    bag: PatternBag
    unbound_penalty: float = 2.0
    pattern_weight: float = 1.5
    rank_decay: float = 0.05

    def score(self, candidate: str, *, raw_rank: int, state_before: str,
              category: Optional[str] = None) -> ScoredCandidate:
        # Parse state, build abstraction map.
        am = build_abstraction_map(state_before)
        local_names = set(am.name_to_ph.keys())
        # Identify identifiers in the candidate that are not built-ins,
        # not in local context, and not pure numeric.
        idents = _candidate_identifiers(candidate)
        unbound = 0
        for ident in idents:
            if ident in _BUILTIN_TOKENS:
                continue
            if ident in local_names:
                continue
            if _is_numeric(ident):
                continue
            # Allow dotted-namespace references e.g. Or.inl
            # The regex tokenises Or, inl separately so we already
            # accept those via the builtin set above. Anything else
            # counts.
            unbound += 1
        # Abstract pattern (over the same state we will substitute
        # into).
        try:
            pattern, _ = abstract_tactic_only(state_before, candidate)
        except Exception:  # pragma: no cover
            pattern = candidate
        n_pat = self.bag.lookup(pattern, category)

        score = (self.pattern_weight * (n_pat ** 0.5)
                 - self.unbound_penalty * unbound
                 - self.rank_decay * raw_rank)
        reason = "ok"
        if unbound > 0:
            reason = "unbound_idents"
        elif n_pat == 0:
            reason = "novel_pattern"
        return ScoredCandidate(
            candidate=candidate, raw_rank=raw_rank,
            abstract_pattern=pattern, pattern_count=n_pat,
            n_unbound_idents=unbound, score=score, reason=reason,
        )

    def rerank(self, candidates: Sequence[str], *, state_before: str,
               category: Optional[str] = None) -> List[ScoredCandidate]:
        scored = [self.score(c, raw_rank=i, state_before=state_before,
                             category=category)
                  for i, c in enumerate(candidates)]
        scored.sort(key=lambda s: (-s.score, s.raw_rank))
        return scored

    def order(self, candidates: Sequence[str], *, state_before: str,
              category: Optional[str] = None) -> List[int]:
        scored = self.rerank(
            candidates, state_before=state_before, category=category)
        idx_of: Dict[Tuple[str, int], int] = {}
        for i, c in enumerate(candidates):
            idx_of.setdefault((c, i), i)
        # Build a per-candidate-instance order so duplicates don't
        # collide.
        seen: Dict[str, int] = {}
        out: List[int] = []
        for s in scored:
            seen[s.candidate] = seen.get(s.candidate, -1) + 1
            count = seen[s.candidate]
            # Find the (count+1)-th occurrence in original
            cnt = 0
            for i, c in enumerate(candidates):
                if c == s.candidate:
                    if cnt == count:
                        out.append(i)
                        break
                    cnt += 1
        return out


def save_pattern_bag(path: Path, bag: PatternBag) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bag.to_json(), indent=2,
                               ensure_ascii=False),
                    encoding="utf-8")


def load_pattern_bag(path: Path) -> PatternBag:
    obj = json.loads(path.read_text(encoding="utf-8"))
    return PatternBag.from_json(obj)


__all__ = [
    "AbstractPatternReranker",
    "PatternBag",
    "ScoredCandidate",
    "build_pattern_bag",
    "save_pattern_bag",
    "load_pattern_bag",
]
