"""Mini-ELF v19 — local-context parser.

Parses a Lean 4 ``state_before`` string into a structured
representation: ordered hypotheses (name, type, type-category) plus
goal (text, category). Used by :mod:`identifier_abstraction` to
generate stable placeholders during training and to resolve those
placeholders back to actual local names at inference time.

The parser is **purely textual** — it does not invoke Lean, does not
read ``state_after`` (the v18/v19 brief forbid it), and does not
treat any binder as a "manual oracle". It runs on the same
``state_before`` strings every v8-v18 model has seen.

Honesty contract (v19 brief):
  * No ``state_after`` anywhere — only the input
    ``state_before`` text is consumed.
  * Hand-rolled regex (no Lean dependency); failures fall through
    to ``TypeCategory.UNKNOWN`` rather than crashing.
  * No manual oracle: the parser describes what the input *says*;
    nothing is inferred about the proof.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence, Tuple


class TypeCategory(str, Enum):
    """Coarse type buckets, ordered roughly from most-specific to
    least. The order matters for the identifier-abstraction layer:
    a hypothesis of type ``p → q`` should be tagged ``IMPLICATION``
    even though ``p → q`` superficially looks like a Prop."""

    PROP = "PROP"               # Prop itself (a type universe)
    IMPLICATION = "IMPLICATION" # p → q
    NEGATION = "NEGATION"       # ¬p
    CONJUNCTION = "CONJUNCTION" # p ∧ q
    DISJUNCTION = "DISJUNCTION" # p ∨ q
    EQUALITY = "EQUALITY"       # a = b
    FORALL = "FORALL"           # ∀ x, ...
    EXISTS = "EXISTS"           # ∃ n, ...
    NAT = "NAT"                 # n : Nat
    BOOL = "BOOL"               # b : Bool
    LIST = "LIST"               # xs : List α
    HYP_PROP = "HYP_PROP"       # h : p (hypothesis of a Prop-shaped type)
    TYPE = "TYPE"               # α : Type
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Hypothesis:
    """One ``name : type`` entry in the local context, in source
    order. Multiple-name binders (``p q : Prop``) are split into
    individual entries with the same type and category."""

    name: str
    type_str: str
    category: TypeCategory
    position_in_state: int  # 0-based index among hypotheses


@dataclass
class LocalContext:
    """Parsed local context. Used by identifier_abstraction."""

    hypotheses: List[Hypothesis] = field(default_factory=list)
    goal: str = ""
    goal_category: TypeCategory = TypeCategory.UNKNOWN
    raw_state: str = ""

    # ---------- convenience views ----------

    def names(self) -> List[str]:
        """All hypothesis names in source order."""
        return [h.name for h in self.hypotheses]

    def hypotheses_of(self, category: TypeCategory) -> List[Hypothesis]:
        return [h for h in self.hypotheses if h.category is category]

    def find(self, name: str) -> Optional[Hypothesis]:
        for h in self.hypotheses:
            if h.name == name:
                return h
        return None


# --------------------------------------------------------------------------- #
# Type classifier
# --------------------------------------------------------------------------- #


# Exact-string rules (single-identifier types like `Prop`, `Nat`).
_EXACT_RULES = {
    "Prop": TypeCategory.PROP,
    "Nat": TypeCategory.NAT,
    "Bool": TypeCategory.BOOL,
}


def _top_level_has(s: str, *needles: str) -> bool:
    """True iff any needle appears at depth-0 (outside parens) in s."""
    depth = 0
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0:
            for nd in needles:
                if s.startswith(nd, i):
                    return True
        i += 1
    return False


def classify_type(type_str: str) -> TypeCategory:
    """Coarse-classify a Lean type string. Order is meaningful:
    most-specific first.

    The lone single-letter (or short identifier) case is special:
    if the type *is* a single identifier of one letter (like ``p``,
    ``q``, ``α``), we tag it as ``HYP_PROP`` — typical of
    Prop-variable references.
    """
    if not type_str:
        return TypeCategory.UNKNOWN
    s = " ".join(type_str.split())  # collapse whitespace

    # 1. Exact-match singletons (Prop, Nat, Bool)
    if s in _EXACT_RULES:
        return _EXACT_RULES[s]

    # 2. Type / Type u universes (treat as TYPE for binder purposes)
    if s == "Type" or s.startswith("Type "):
        return TypeCategory.TYPE

    # 3. Leading symbols
    if s.startswith("∀ "):
        return TypeCategory.FORALL
    if s.startswith("∃ "):
        return TypeCategory.EXISTS
    if s.startswith("¬"):
        return TypeCategory.NEGATION

    # 4. Top-level connectives (check in priority order: disjunction
    # and conjunction before equality, because for `b = true ∨ b = false`
    # the top-level operator is ∨, not =. Then implication.)
    if _top_level_has(s, " ∨ "):
        return TypeCategory.DISJUNCTION
    if _top_level_has(s, " ∧ "):
        return TypeCategory.CONJUNCTION
    if _top_level_has(s, " → ", "->"):
        return TypeCategory.IMPLICATION
    # Equality: top-level `=` that isn't `=>` or `:=` or `==`.
    eq_rx = re.compile(r"(?<![:=\-!<>])=(?!=|>)")
    for m in eq_rx.finditer(s):
        # exclude `=>` already handled by lookahead, double-check
        # this match isn't inside parens
        depth = 0
        for c in s[:m.start()]:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
        if depth == 0:
            return TypeCategory.EQUALITY

    # 5. Container types (`List α`, etc.)
    if s.startswith("List ") or s == "List":
        return TypeCategory.LIST

    # 6. Single-identifier fallback → Prop-variable reference
    if re.match(r"^[A-Za-zα-ωΑ-Ω_][A-Za-z0-9α-ωΑ-Ω_']*$", s):
        return TypeCategory.HYP_PROP

    # 7. Mentions of known types in compound expressions
    if re.search(r"\bNat\b", s):
        return TypeCategory.NAT
    if re.search(r"\bBool\b", s):
        return TypeCategory.BOOL
    if re.search(r"\bList\b", s):
        return TypeCategory.LIST

    return TypeCategory.UNKNOWN


# --------------------------------------------------------------------------- #
# State parser
# --------------------------------------------------------------------------- #


_TURNSTILE = "⊢"


def _split_lines(state: str) -> Tuple[List[str], str]:
    """Return (hypothesis_lines, goal_text). Hypothesis lines are
    everything before the first ``⊢`` line; the goal is the text
    after ``⊢`` (with possible newlines preserved)."""
    if _TURNSTILE in state:
        before, after = state.split(_TURNSTILE, 1)
    else:
        before, after = state, ""
    hyp_lines = [ln for ln in before.splitlines() if ln.strip()]
    goal = after.strip()
    return hyp_lines, goal


def _parse_hyp_line(line: str) -> List[Tuple[str, str]]:
    """``name1 name2 : type`` -> [(name1, type), (name2, type)].
    Returns [] on malformed input rather than raising."""
    if ":" not in line:
        return []
    # Find the first top-level ':' (depth-0). Lean types can contain
    # ':' inside e.g. ``(x : Nat)`` so depth-aware split is safer.
    depth = 0
    for i, c in enumerate(line):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == ":" and depth == 0:
            if i + 1 < len(line) and line[i + 1] == "=":
                # ":=" — skip; not a binder colon
                continue
            names_part = line[:i].strip()
            type_part = line[i + 1:].strip()
            names = names_part.split()
            return [(n, type_part) for n in names if n and _is_ident(n)]
    return []


def _is_ident(s: str) -> bool:
    """Lenient Lean-4 identifier check. Accepts letters/digits/
    underscore/prime; first char must be a letter or underscore."""
    if not s:
        return False
    if not re.match(r"^[A-Za-zα-ωΑ-Ω_][A-Za-z0-9α-ωΑ-Ω_']*$", s):
        return False
    return True


def parse_state(state_before: str) -> LocalContext:
    """Top-level parser. Resilient — returns an empty context on
    malformed input."""
    if not state_before:
        return LocalContext(raw_state="")
    hyp_lines, goal = _split_lines(state_before)
    hyps: List[Hypothesis] = []
    pos = 0
    for ln in hyp_lines:
        for name, type_str in _parse_hyp_line(ln):
            cat = classify_type(type_str)
            hyps.append(Hypothesis(
                name=name, type_str=type_str, category=cat,
                position_in_state=pos,
            ))
            pos += 1
    return LocalContext(
        hypotheses=hyps, goal=goal,
        goal_category=classify_type(goal),
        raw_state=state_before,
    )


# --------------------------------------------------------------------------- #
# Helpers for the abstraction layer
# --------------------------------------------------------------------------- #


def context_token_signature(ctx: LocalContext) -> Tuple[str, ...]:
    """A hashable summary of the context's hypothesis category
    sequence. Two states with identical signatures are
    abstraction-equivalent."""
    return tuple(h.category.value for h in ctx.hypotheses) + (
        f"goal:{ctx.goal_category.value}",)


__all__ = [
    "Hypothesis",
    "LocalContext",
    "TypeCategory",
    "classify_type",
    "context_token_signature",
    "parse_state",
]
