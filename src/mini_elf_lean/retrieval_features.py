"""Mini-ELF v6 — heuristic *structured* features for structure-aware retrieval.

v5 retrieval ranked donors by char-n-gram similarity alone, which mis-ranks
sibling families (`docs/V6_RETRIEVAL_FAILURE_ANALYSIS.md`). v6 adds a small bag
of *parse* features over `theorem_statement` + `state_before` — goal shape,
hypothesis shapes, numeric literals, connective multiset, a left/right
conjunct-position signal, and a guessed `required_operation` — so the retrieval
scorer can prefer the donor with the right **proof structure** over the one with
the right **variable letters**.

Heuristic string parsing only (reuses `elf_structure`); **no Lean AST**, and
**never** reads `state_after`. Pure-Python / torch-free.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import FrozenSet, List, Optional, Tuple

from .elf_structure import (
    _depth0_find,
    _strip_outer_parens,
    extract_goal_line,
    extract_hypotheses,
    extract_identifiers,
    extract_numeric_literals,
    parse_binding,
    split_binary,
)

# ---- goal-shape labels (superset of elf_structure's, refined for v6) ----
FORALL_GOAL = "forall_goal"
EXISTS_GOAL = "exists_goal"
NEG_GOAL = "neg_goal"
IMPLICATION_GOAL = "implication_goal"
CONJUNCTION_GOAL = "conjunction_goal"
DISJUNCTION_GOAL = "disjunction_goal"
IFF_GOAL = "iff_goal"
EQUALITY_GOAL = "equality_goal"
REWRITE_GOAL = "rewrite_goal"            # f a = f b with a matching eq-hyp
CONTRADICTION_GOAL = "contradiction_goal"  # bare atom + a negation hypothesis (ex falso)
TRUE_GOAL = "true_goal"
FALSE_GOAL = "false_goal"
ATOM_GOAL = "atom_goal"

# ---- required-operation guesses (brief's fixed enum) ----
OP_INSTANTIATE_FORALL = "instantiate_forall"
OP_REWRITE = "rewrite"
OP_DESTRUCT_EXISTS = "destruct_exists"
OP_CONTRADICTION = "contradiction"
OP_INTRO_NEGATION = "intro_negation"
OP_PROJECT_CONJUNCTION = "project_conjunction"
OP_UNKNOWN = "unknown"

_CONNECTIVE_SYMBOLS = ("∀", "∃", "¬", "↔", "→", "∨", "∧")
_EQ_RE = re.compile(r"(?<![:<>=])=(?![=>])")  # standalone '=' (not :=, ==, =>, <=, >=)
_BUILTIN_TYPES = frozenset({"Prop", "Type", "Sort", "Type*", "Nat", "ℕ", "Int", "ℤ", "Bool"})


def _norm(expr: str) -> str:
    return re.sub(r"\s+", " ", _strip_outer_parens(expr.strip())).strip()


def _exists_body(ty: str) -> Optional[str]:
    """Body of `∃ _ : T, BODY` -> `BODY` (depth-0 comma)."""
    t = ty.strip()
    if not (t.startswith("∃") or t.startswith("Exists")):
        return None
    idx = _depth0_find(t, ",")
    return t[idx + 1:].strip() if idx >= 0 else None


def _is_compound(term: str) -> bool:
    """A term that is a function application / projection, not a bare identifier
    or literal (so `n.succ`, `f a` are compound; `n`, `7`, `m` are not)."""
    t = _strip_outer_parens(term.strip())
    return (" " in t) or ("." in t)


@dataclass
class StateFeatures:
    goal: str
    goal_shape: str
    # hypothesis shape flags
    has_forall_hyp: bool = False
    has_exists_hyp: bool = False
    has_neg_hyp: bool = False
    has_imp_hyp: bool = False
    has_eq_hyp: bool = False
    has_and_hyp: bool = False
    has_or_hyp: bool = False
    numeric_literals: FrozenSet[str] = field(default_factory=frozenset)
    goal_literals: Tuple[str, ...] = ()
    identifiers: FrozenSet[str] = field(default_factory=frozenset)
    type_tokens: FrozenSet[str] = field(default_factory=frozenset)
    connectives: Counter = field(default_factory=Counter)
    required_operation: str = OP_UNKNOWN
    goal_conjunct_position: str = "none"  # left | right | none

    def hyp_shape_vector(self) -> Tuple[bool, ...]:
        return (self.has_forall_hyp, self.has_exists_hyp, self.has_neg_hyp,
                self.has_imp_hyp, self.has_eq_hyp, self.has_and_hyp, self.has_or_hyp)


def _hyp_flags(hyp_types: List[str]):
    has = dict(forall=False, exists=False, neg=False, imp=False, eq=False, and_=False, or_=False)
    conjunctions: List[Tuple[str, str]] = []
    for ty in hyp_types:
        t = ty.strip()
        if "∀" in t:
            has["forall"] = True
        if "∃" in t or t.startswith("Exists"):
            has["exists"] = True
        if t.startswith("¬") or "→ False" in t or "→False" in t or "¬" in t:
            has["neg"] = True
        if _depth0_find(t, "→") >= 0:
            has["imp"] = True
        if _depth0_find(t, "=") >= 0:
            has["eq"] = True
        # conjunctions: inside an ∃-body if present (so `∃ _, a ∧ b` splits the
        # body into (a, b), not the whole type into (∃ _, a) and (b)), else a
        # top-level ∧.
        body = _exists_body(t)
        and_parts = split_binary(body, "∧") if body is not None else split_binary(t, "∧")
        if and_parts is not None:
            has["and_"] = True
            conjunctions.append(and_parts)
        if _depth0_find(t, "∨") >= 0:
            has["or_"] = True
    return has, conjunctions


def _goal_literals(goal: str) -> Tuple[str, ...]:
    return tuple(extract_numeric_literals(goal))


def _classify_goal_shape(goal: str, hyp_flags) -> str:
    g = _strip_outer_parens(goal.strip())
    if not g:
        return ATOM_GOAL
    if g == "True":
        return TRUE_GOAL
    if g == "False":
        return FALSE_GOAL
    if g.startswith("∀"):
        return FORALL_GOAL
    if g.startswith("¬"):
        return NEG_GOAL
    if g.startswith("∃") or g.startswith("Exists"):
        return EXISTS_GOAL
    if _depth0_find(g, "↔") >= 0:
        return IFF_GOAL
    if _depth0_find(g, "→") >= 0:
        return IMPLICATION_GOAL
    if _depth0_find(g, "∨") >= 0:
        return DISJUNCTION_GOAL
    if _depth0_find(g, "∧") >= 0:
        return CONJUNCTION_GOAL
    eq = split_binary(g, "=")
    if eq is not None:
        lhs, rhs = eq
        if hyp_flags["eq"] and (_is_compound(lhs) or _is_compound(rhs)):
            return REWRITE_GOAL
        return EQUALITY_GOAL
    # bare atom
    if hyp_flags["neg"]:
        return CONTRADICTION_GOAL
    return ATOM_GOAL


def _required_operation(goal_shape: str, hyp_flags) -> str:
    # Priority order matters: a ∀-hypothesis instantiation dominates a plain eq goal.
    if hyp_flags["forall"] and goal_shape in (EQUALITY_GOAL, REWRITE_GOAL, ATOM_GOAL, CONTRADICTION_GOAL):
        return OP_INSTANTIATE_FORALL
    if goal_shape == REWRITE_GOAL:
        return OP_REWRITE
    if goal_shape == NEG_GOAL:
        return OP_INTRO_NEGATION
    if goal_shape == IMPLICATION_GOAL and hyp_flags["neg"]:
        return OP_INTRO_NEGATION  # intro the antecedent, then ex falso
    if hyp_flags["exists"] and goal_shape != EXISTS_GOAL:
        return OP_DESTRUCT_EXISTS
    if goal_shape == CONTRADICTION_GOAL:
        return OP_CONTRADICTION
    if hyp_flags["and_"] and goal_shape == ATOM_GOAL:
        return OP_PROJECT_CONJUNCTION
    if goal_shape == REWRITE_GOAL:
        return OP_REWRITE
    return OP_UNKNOWN


def _conjunct_position(goal: str, conjunctions: List[Tuple[str, str]]) -> str:
    g = _norm(goal)
    for lhs, rhs in conjunctions:
        if g == _norm(lhs):
            return "left"
        if g == _norm(rhs):
            return "right"
    return "none"


def _type_tokens(hyp_types: List[str]) -> FrozenSet[str]:
    toks: set = set()
    for ty in hyp_types:
        for t in extract_identifiers(ty):
            if t in _BUILTIN_TYPES:
                toks.add(t)
    return frozenset(toks)


def _connective_counter(text: str) -> Counter:
    c: Counter = Counter()
    for sym in _CONNECTIVE_SYMBOLS:
        n = text.count(sym)
        if n:
            c[sym] = n
    eq = len(_EQ_RE.findall(text))
    if eq:
        c["="] = eq
    return c


def extract_features(theorem_statement: Optional[str], state_before: str) -> StateFeatures:
    """Parse a `(theorem_statement, state_before)` prompt into structured
    retrieval features. Robust to malformed text (never raises)."""
    try:
        goal = extract_goal_line(state_before)
        hyp_types: List[str] = []
        for line in extract_hypotheses(state_before):
            b = parse_binding(line)
            if b is None:
                continue
            _names, ty = b
            ty = ty.strip()
            if ty in _BUILTIN_TYPES or ty == "Prop" or ty.startswith("Type") or ty == "Sort":
                continue  # type/value declaration, not a proof hypothesis
            hyp_types.append(ty)

        flags, conjunctions = _hyp_flags(hyp_types)
        shape = _classify_goal_shape(goal, flags)
        text = f"{theorem_statement or ''}\n{state_before}"
        return StateFeatures(
            goal=goal,
            goal_shape=shape,
            has_forall_hyp=flags["forall"], has_exists_hyp=flags["exists"],
            has_neg_hyp=flags["neg"], has_imp_hyp=flags["imp"], has_eq_hyp=flags["eq"],
            has_and_hyp=flags["and_"], has_or_hyp=flags["or_"],
            numeric_literals=frozenset(extract_numeric_literals(text)),
            goal_literals=_goal_literals(goal),
            identifiers=frozenset(extract_identifiers(state_before)),
            type_tokens=_type_tokens(hyp_types),
            connectives=_connective_counter(state_before),
            required_operation=_required_operation(shape, flags),
            goal_conjunct_position=_conjunct_position(goal, conjunctions),
        )
    except Exception:  # noqa: BLE001 - features must never crash retrieval
        return StateFeatures(goal=state_before, goal_shape=ATOM_GOAL)


# ---- similarity helpers between two feature sets ----


def goal_shape_match(a: StateFeatures, b: StateFeatures) -> float:
    return 1.0 if a.goal_shape == b.goal_shape else 0.0


def operation_match(a: StateFeatures, b: StateFeatures) -> float:
    if a.required_operation == OP_UNKNOWN or b.required_operation == OP_UNKNOWN:
        return 0.0
    return 1.0 if a.required_operation == b.required_operation else 0.0


def hyp_shape_match(a: StateFeatures, b: StateFeatures) -> float:
    va, vb = a.hyp_shape_vector(), b.hyp_shape_vector()
    return sum(1 for x, y in zip(va, vb) if x == y) / len(va)


def connective_overlap(a: StateFeatures, b: StateFeatures) -> float:
    """Cosine over the connective multisets (0 when either is empty)."""
    ca, cb = a.connectives, b.connectives
    if not ca or not cb:
        return 0.0
    dot = sum(v * cb.get(k, 0) for k, v in ca.items())
    na = sum(v * v for v in ca.values()) ** 0.5
    nb = sum(v * v for v in cb.values()) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def token_overlap(a: StateFeatures, b: StateFeatures) -> float:
    """Jaccard over identifier + type tokens."""
    sa = a.identifiers | a.type_tokens
    sb = b.identifiers | b.type_tokens
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def numeric_compatibility(target: StateFeatures, donor: StateFeatures) -> float:
    """1.0 if the donor's literals are all present in the target (verbatim-safe);
    0.5 if the donor has a single literal and the target has literals to
    substitute (adaptable); 0.0 if the donor carries a literal the target lacks
    and cannot be adapted."""
    dl, tl = donor.numeric_literals, target.numeric_literals
    if dl <= tl:
        return 1.0
    if len(dl) == 1 and tl:
        return 0.5
    if not dl:
        return 1.0
    return 0.0
