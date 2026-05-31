"""Mini-ELF v3 — a small *structured proof-block planner*.

v2's diagnosis (`docs/V2_GENERALIZATION_REPORT.md`) was that the learned
generator + reranker recover in-distribution-hard problems but achieve **no
compositional generalization**: training on easy/medium proofs does not teach
the model to *compose* a multi-step proof it never saw (difficulty-holdout
`pass@5` stuck at 0.06). The flat tactic-string generator has no notion of
"chain three implications" or "project the third conjunct".

This module attacks that directly and *symbolically*. It (1) parses the
theorem-level prompt into typed hypotheses + a goal structure (the parser,
Part 2) and (2) enumerates **structured candidate proof blocks** from a small
template / backward-search library (Part 3): implication chains, conjunction
projection / construction, disjunction elimination & introduction, iff
directionality, and equality trans/symm chains. Existential witnesses are left
to the existing :mod:`mini_elf_lean.elf_witness` copy augmenter.

Honesty (unchanged from v0–v2):

  * This is **not** full ELF and **not** neural generation. The planner is a
    deterministic *symbolic / heuristic* search over a hand-written template
    library. Its candidates are tagged with a ``planner_*`` source so their
    contribution is auditable, and every candidate is checked by the **same**
    lean-cli verifier as every other source.
  * It reads only ``theorem_statement`` + ``state_before`` text — **never**
    ``state_after`` (there is no such field here). Parsing is a string
    heuristic, not a Lean AST.
  * The goal it targets is *compositional generalization*, measured by the
    hard-corpus ``difficulty_holdout`` split.

Pure-Python and torch-free, so the whole parser + template library is
unit-testable without torch or Lean.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .elf_structure import (
    _depth0_find,
    _strip_outer_parens,
    classify_goal_shape,
    extract_goal_line,
    extract_hypotheses,
    parse_binding,
)

# ---------------- candidate source labels (Part 4 contract) ----------------

PLANNER_TEMPLATE = "planner_template"   # and-intro / or-intro / uncurry blocks
PLANNER_CHAIN = "planner_chain"         # implication / modus-ponens composition
PLANNER_CASES = "planner_cases"         # ∨-elimination case splits
PLANNER_PROJECTION = "planner_projection"  # (nested) conjunction projection
PLANNER_EQ = "planner_eq"               # equality trans/symm chains
PLANNER_IFF = "planner_iff"             # iff .mp/.mpr direction composition

PLANNER_SOURCES: Tuple[str, ...] = (
    PLANNER_TEMPLATE, PLANNER_CHAIN, PLANNER_CASES,
    PLANNER_PROJECTION, PLANNER_EQ, PLANNER_IFF,
)

# Builtin value types so `a b : Nat` is read as values, not a proof hypothesis.
_BUILTIN_TYPES = frozenset({"Nat", "ℕ", "Int", "ℤ", "Bool", "String", "Char", "Float"})
_TYPE_DECLS = frozenset({"Prop", "Type", "Sort", "Type*"})

_IDENT_RE = re.compile(r"[^\W\d][\w']*", re.UNICODE)
# Fresh intro-binder name pool (avoids colliding with existing identifiers).
_INTRO_POOL = ("ha", "hb", "hc", "hd", "he", "hf", "hg")
_CASE_POOL = ("hx", "hcase", "hy", "hz")

_MAX_DEPTH = 4
_MAX_PER_NODE = 6


def _norm(expr: str) -> str:
    """Normalize a proposition string for equality matching: strip a single
    enclosing paren layer and collapse internal whitespace."""
    return re.sub(r"\s+", " ", _strip_outer_parens(expr.strip())).strip()


def _wrap(arg: str) -> str:
    """Parenthesize ``arg`` iff it has a *depth-0* space (a compound application
    like ``h1 h`` or ``h2.trans h3``). A bracket group ``⟨a, b⟩`` whose only
    spaces are inside ``⟨⟩`` is left bare — matching the corpus convention
    ``h ⟨ha, hb⟩`` rather than ``h (⟨ha, hb⟩)``."""
    arg = arg.strip()
    return f"({arg})" if _depth0_find(arg, " ") >= 0 else arg


def _app(func: str, arg: str) -> str:
    """Function application ``func arg`` with corpus-style parenthesization."""
    return f"{func} {_wrap(arg)}"


def _block(*lines: str) -> str:
    """Join tactic lines with the corpus continuation convention (newline +
    two-space indent), so the result drops cleanly into ``by\\n  __TACTIC__``."""
    return "\n  ".join(lines)


# ---------------- Part 2: typed hypothesis / goal parser ----------------


@dataclass(frozen=True)
class PlannerHyp:
    """One hypothesis decomposed by its *top-level* connective (Lean precedence:
    ``↔`` loosest, then ``→``, ``∨``, ``∧``, ``=``)."""

    name: str
    type: str
    kind: str  # imp | iff | eq | and | or | atom | other
    parts: Optional[Tuple[str, str]] = None  # (lhs, rhs) for binary connectives


def _classify_prop(ty: str) -> Tuple[str, Optional[Tuple[str, str]]]:
    """``(kind, parts)`` for a proposition type string, by loosest connective."""
    t = _strip_outer_parens(ty.strip())
    for op, kind in (("↔", "iff"), ("→", "imp"), ("∨", "or"), ("∧", "and")):
        idx = _depth0_find(t, op)
        if idx >= 0:
            return kind, (t[:idx].strip(), t[idx + len(op):].strip())
    idx = _depth0_find(t, "=")
    if idx >= 0:
        return "eq", (t[:idx].strip(), t[idx + 1:].strip())
    return "atom", None


@dataclass
class PlannerState:
    """Heuristic structured view of a tactic-state prompt for the planner."""

    theorem_statement: Optional[str]
    state_before: str
    goal: str
    goal_shape: str
    hyps: List[PlannerHyp]
    declared_props: frozenset
    declared_types: frozenset
    value_vars: Dict[str, str]  # name -> value type
    pattern_family: Optional[str] = None

    # convenience views ------------------------------------------------------
    def by_kind(self, kind: str) -> List[PlannerHyp]:
        return [h for h in self.hyps if h.kind == kind]

    @property
    def imp_hyps(self) -> List[PlannerHyp]:
        return self.by_kind("imp")

    @property
    def iff_hyps(self) -> List[PlannerHyp]:
        return self.by_kind("iff")

    @property
    def eq_hyps(self) -> List[PlannerHyp]:
        return self.by_kind("eq")

    @property
    def and_hyps(self) -> List[PlannerHyp]:
        return self.by_kind("and")

    @property
    def or_hyps(self) -> List[PlannerHyp]:
        return self.by_kind("or")


def parse_planner_state(
    theorem_statement: Optional[str],
    state_before: str,
    *,
    pattern_family: Optional[str] = None,
) -> PlannerState:
    """Parse a ``(theorem_statement, state_before)`` prompt into a
    :class:`PlannerState`. Two passes: first collect ``: Prop`` / ``: Type``
    declarations, then classify the remaining bindings as typed proof
    hypotheses or value variables."""
    goal = extract_goal_line(state_before)
    bindings: List[Tuple[List[str], str]] = []
    for line in extract_hypotheses(state_before):
        b = parse_binding(line)
        if b is not None:
            bindings.append(b)

    declared_props: set = set()
    declared_types: set = set()
    # pass 1: type/prop declarations
    for names, ty in bindings:
        t = ty.strip()
        if t == "Prop":
            declared_props.update(names)
        elif t in _TYPE_DECLS or t.startswith("Type"):
            declared_types.update(names)

    known_value_types = declared_types | _BUILTIN_TYPES
    value_vars: Dict[str, str] = {}
    hyps: List[PlannerHyp] = []
    # pass 2: classify the rest
    for names, ty in bindings:
        t = ty.strip()
        if t == "Prop" or t in _TYPE_DECLS or t.startswith("Type"):
            continue
        if t in known_value_types:
            for n in names:
                value_vars[n] = t
            continue
        kind, parts = _classify_prop(t)
        for n in names:
            hyps.append(PlannerHyp(name=n, type=t, kind=kind, parts=parts))

    return PlannerState(
        theorem_statement=theorem_statement,
        state_before=state_before,
        goal=goal,
        goal_shape=classify_goal_shape(goal),
        hyps=hyps,
        declared_props=frozenset(declared_props),
        declared_types=frozenset(declared_types),
        value_vars=value_vars,
        pattern_family=pattern_family,
    )


# ---------------- Part 3: backward proof-term search ----------------


def _expand_projections(name: str, ty: str, out: List[Tuple[str, str, str]], depth: int) -> None:
    """Append ``(term, normed_type, "proj")`` for every conjunction projection
    of hypothesis ``name : ty`` (both ``.1/.2`` and ``.left/.right`` spellings,
    recursively). The root term itself is added by the caller."""
    if depth <= 0:
        return
    kind, parts = _classify_prop(ty)
    if kind != "and" or parts is None:
        return
    lhs, rhs = parts
    for proj_l, proj_r in ((".1", ".2"), (".left", ".right")):
        out.append((f"{name}{proj_l}", _norm(lhs), "proj"))
        out.append((f"{name}{proj_r}", _norm(rhs), "proj"))
        _expand_projections(f"{name}{proj_l}", lhs, out, depth - 1)
        _expand_projections(f"{name}{proj_r}", rhs, out, depth - 1)


class _Prover:
    """Bounded backward-chaining proof-term builder over a :class:`PlannerState`.

    ``prove(goal)`` returns an ordered, deduplicated list of ``(term, kind)``
    where ``kind`` is the *outermost* rule that produced the term
    (``base``/``proj``/``app``/``iff``/``and``) — used to label the candidate
    source. Deterministic; depth-bounded so it cannot loop on ``A ↔ B``.
    """

    def __init__(self, state: PlannerState, extra_terms: Optional[List[Tuple[str, str]]] = None) -> None:
        # base terms: (term_string, normed_type, kind)
        self.base: List[Tuple[str, str, str]] = []
        for h in state.hyps:
            self.base.append((h.name, _norm(h.type), "base"))
            if h.kind == "and":
                _expand_projections(h.name, h.type, self.base, _MAX_DEPTH)
        for term, ty in (extra_terms or []):
            self.base.append((term, _norm(ty), "base"))
        self.imp_hyps = state.imp_hyps
        self.iff_hyps = state.iff_hyps

    def prove(self, goal: str, depth: int = _MAX_DEPTH) -> List[Tuple[str, str]]:
        g = _norm(goal)
        results: List[Tuple[str, str]] = []
        seen: set = set()

        def add(term: str, kind: str) -> None:
            if term not in seen:
                seen.add(term)
                results.append((term, kind))

        # rule A/B: a base term (hypothesis or projection) of exactly this type
        for term, ty, kind in self.base:
            if ty == g:
                add(term, kind)
        if depth <= 0:
            return results[:_MAX_PER_NODE]

        # rule C: apply an implication hypothesis whose consequent is the goal
        for h in self.imp_hyps:
            if h.parts is None:
                continue
            ant, con = h.parts
            if _norm(con) == g:
                for pa, _ in self.prove(ant, depth - 1):
                    add(_app(h.name, pa), "app")

        # rule D: iff direction — h : A ↔ B gives h.mp : A → B, h.mpr : B → A
        for h in self.iff_hyps:
            if h.parts is None:
                continue
            a, b = h.parts
            if _norm(b) == g:
                for pa, _ in self.prove(a, depth - 1):
                    add(_app(f"{h.name}.mp", pa), "iff")
            if _norm(a) == g:
                for pb, _ in self.prove(b, depth - 1):
                    add(_app(f"{h.name}.mpr", pb), "iff")

        # rule E: build a conjunction goal from proofs of each side
        parts = _split_top(g, "∧")
        if parts is not None:
            lefts = self.prove(parts[0], depth - 1)
            rights = self.prove(parts[1], depth - 1)
            if lefts and rights:
                add(f"⟨{lefts[0][0]}, {rights[0][0]}⟩", "and")

        return results[:_MAX_PER_NODE]


def _split_top(expr: str, op: str) -> Optional[Tuple[str, str]]:
    e = _strip_outer_parens(expr.strip())
    idx = _depth0_find(e, op)
    if idx < 0:
        return None
    return e[:idx].strip(), e[idx + len(op):].strip()


# ---------------- intro-name allocation ----------------


def _existing_identifiers(state: PlannerState) -> set:
    toks: set = set(state.value_vars)
    toks |= set(state.declared_props) | set(state.declared_types)
    for h in state.hyps:
        toks.add(h.name)
        toks.update(_IDENT_RE.findall(h.type))
    toks.update(_IDENT_RE.findall(state.goal))
    return toks


def _fresh_names(n: int, taken: set, pool: Tuple[str, ...] = _INTRO_POOL) -> List[str]:
    out: List[str] = []
    used = set(taken)
    for cand in pool:
        if cand not in used:
            out.append(cand)
            used.add(cand)
        if len(out) >= n:
            return out
    i = 0
    while len(out) < n:  # pathological fallback
        cand = f"h_{i}"
        if cand not in used:
            out.append(cand)
            used.add(cand)
        i += 1
    return out


# ---------------- candidate dataclass ----------------


@dataclass(frozen=True)
class PlannerCandidate:
    tactic: str
    source: str
    strategy: str
    priority: int  # lower ranks earlier


_KIND_TO_SOURCE = {
    "base": PLANNER_PROJECTION,  # a direct hypothesis match; treat like projection-tier
    "proj": PLANNER_PROJECTION,
    "app": PLANNER_CHAIN,
    "iff": PLANNER_IFF,
    "and": PLANNER_TEMPLATE,
}
_KIND_PRIORITY = {"base": 10, "proj": 12, "and": 20, "iff": 22, "app": 24}


# ---------------- Part 3: template strategies ----------------


def _peel_arrows(goal: str) -> Tuple[List[str], str]:
    """Peel leading depth-0 ``→`` antecedents: ``A → B → C`` -> (["A","B"], "C")."""
    antecedents: List[str] = []
    cur = _strip_outer_parens(goal.strip())
    while True:
        idx = _depth0_find(cur, "→")
        if idx < 0:
            break
        antecedents.append(cur[:idx].strip())
        cur = _strip_outer_parens(cur[idx + len("→"):].strip())
    return antecedents, cur


def _and_tree(expr: str):
    e = _strip_outer_parens(expr.strip())
    parts = _split_top(e, "∧")
    if parts is None:
        return ("leaf", e)
    return ("and", _and_tree(parts[0]), _and_tree(parts[1]))


def _anon_constructor(tree, prover: "_Prover") -> Optional[str]:
    if tree[0] == "leaf":
        ps = prover.prove(tree[1])
        return ps[0][0] if ps else None
    left = _anon_constructor(tree[1], prover)
    right = _anon_constructor(tree[2], prover)
    if left is None or right is None:
        return None
    return f"⟨{left}, {right}⟩"


def _and_intro_term(tree, prover: "_Prover") -> Optional[str]:
    if tree[0] == "leaf":
        ps = prover.prove(tree[1])
        return ps[0][0] if ps else None
    left = _and_intro_term(tree[1], prover)
    right = _and_intro_term(tree[2], prover)
    if left is None or right is None:
        return None
    return f"And.intro {_wrap(left)} {_wrap(right)}"


def _right_spine_leaves(tree) -> Optional[List[str]]:
    """Leaf list if ``tree`` is a right-leaning spine (every left child a leaf),
    else None — flat ``⟨a, b, c⟩`` is only valid for right-assoc conjunctions."""
    leaves: List[str] = []
    node = tree
    while node[0] == "and":
        if node[1][0] != "leaf":
            return None
        leaves.append(node[1][1])
        node = node[2]
    leaves.append(node[1])
    return leaves


def _eq_chain_candidates(state: PlannerState) -> List[PlannerCandidate]:
    """Equality goal ``a = d``: search a trans/symm path through the eq hyps."""
    parts = _split_top(state.goal, "=")
    if parts is None or not state.eq_hyps:
        return []
    src, dst = _norm(parts[0]), _norm(parts[1])

    # directed edges: forward (h) and reversed (h.symm)
    edges: List[Tuple[str, str, str]] = []  # (from, to, term)
    for h in state.eq_hyps:
        if h.parts is None:
            continue
        a, b = _norm(h.parts[0]), _norm(h.parts[1])
        edges.append((a, b, h.name))
        edges.append((b, a, f"{h.name}.symm"))

    # shortest path (fewest edges) src -> dst, no repeated nodes
    best: Optional[List[str]] = None
    stack: List[Tuple[str, List[str], set]] = [(src, [], {src})]
    while stack:
        node, path_terms, visited = stack.pop(0)
        if node == dst and path_terms:
            if best is None or len(path_terms) < len(best):
                best = path_terms
            continue
        if len(path_terms) >= len(state.eq_hyps) + 1:
            continue
        for a, b, term in edges:
            if a == node and b not in visited:
                stack.append((b, path_terms + [term], visited | {b}))
    if not best:
        return []

    out: List[PlannerCandidate] = []
    if len(best) == 1:
        out.append(PlannerCandidate(f"exact {best[0]}", PLANNER_EQ, "eq_direct", 14))
    else:
        out.append(PlannerCandidate(f"exact {_trans_right(best)}", PLANNER_EQ, "eq_trans_right", 18))
        out.append(PlannerCandidate(f"exact {_trans_left(best)}", PLANNER_EQ, "eq_trans_left", 19))
    return out


def _trans_right(edges: List[str]) -> str:
    expr = edges[-1]
    for e in reversed(edges[:-1]):
        expr = f"{e}.trans {_wrap(expr)}"
    return expr


def _trans_left(edges: List[str]) -> str:
    expr = edges[0]
    for e in edges[1:]:
        expr = f"{_wrap(expr)}.trans {e}" if _depth0_find(expr, " ") >= 0 else f"{expr}.trans {e}"
    return expr


def _or_elim_candidates(state: PlannerState) -> List[PlannerCandidate]:
    """For each ``h : A ∨ B`` build a case split proving the current goal in each
    branch (the disjunct is added as a fresh hypothesis and the goal re-planned)."""
    out: List[PlannerCandidate] = []
    taken = _existing_identifiers(state)
    binder = _fresh_names(1, taken, _CASE_POOL)[0]
    for h in state.or_hyps:
        if h.parts is None:
            continue
        a, b = h.parts
        prover_a = _Prover(state, extra_terms=[(binder, a)])
        prover_b = _Prover(state, extra_terms=[(binder, b)])
        pa = prover_a.prove(state.goal)
        pb = prover_b.prove(state.goal)
        if not (pa and pb):
            continue
        ta, tb = pa[0][0], pb[0][0]
        out.append(PlannerCandidate(
            _block(f"cases {h.name} with",
                   f"| inl {binder} => exact {ta}",
                   f"| inr {binder} => exact {tb}"),
            PLANNER_CASES, "or_elim_cases", 40,
        ))
        out.append(PlannerCandidate(
            _block(f"rcases {h.name} with {binder} | {binder}",
                   f"exact {ta}", f"exact {tb}"),
            PLANNER_CASES, "or_elim_rcases", 41,
        ))
        # Or.elim with named branch functions, when A→goal / B→goal are hyps.
        fa = _branch_fn(state, a)
        fb = _branch_fn(state, b)
        if fa and fb:
            out.append(PlannerCandidate(
                f"exact Or.elim {h.name} {fa} {fb}", PLANNER_CASES, "or_elim_term", 42))
    return out


def _branch_fn(state: PlannerState, antecedent: str) -> Optional[str]:
    """Name of a hypothesis ``f : antecedent → goal`` (for ``Or.elim``)."""
    g = _norm(state.goal)
    ant = _norm(antecedent)
    for h in state.imp_hyps:
        if h.parts and _norm(h.parts[0]) == ant and _norm(h.parts[1]) == g:
            return h.name
    return None


def _and_goal_candidates(state: PlannerState, prover: "_Prover") -> List[PlannerCandidate]:
    out: List[PlannerCandidate] = []
    tree = _and_tree(state.goal)
    if tree[0] != "and":
        return out
    anon = _anon_constructor(tree, prover)
    if anon is not None:
        out.append(PlannerCandidate(f"exact {anon}", PLANNER_TEMPLATE, "and_intro_anon", 26))
        spine = _right_spine_leaves(tree)
        if spine is not None and len(spine) > 2:
            leaves = [prover.prove(lf) for lf in spine]
            if all(leaves):
                flat = ", ".join(lf[0][0] for lf in leaves)
                out.append(PlannerCandidate(
                    f"exact ⟨{flat}⟩", PLANNER_TEMPLATE, "and_intro_flat", 27))
    ai = _and_intro_term(tree, prover)
    if ai is not None:
        out.append(PlannerCandidate(f"exact {ai}", PLANNER_TEMPLATE, "and_intro_named", 28))
    # binary constructor block
    parts = _split_top(state.goal, "∧")
    if parts is not None:
        pl = prover.prove(parts[0])
        pr = prover.prove(parts[1])
        if pl and pr:
            out.append(PlannerCandidate(
                _block("constructor", f"exact {pl[0][0]}", f"exact {pr[0][0]}"),
                PLANNER_TEMPLATE, "and_constructor", 29))
    return out


def _or_goal_candidates(state: PlannerState, prover: "_Prover") -> List[PlannerCandidate]:
    out: List[PlannerCandidate] = []
    parts = _split_top(state.goal, "∨")
    if parts is None:
        return out
    left, right = parts
    pl = prover.prove(left)
    if pl:
        out.append(PlannerCandidate(f"exact Or.inl {_wrap(pl[0][0])}", PLANNER_TEMPLATE, "or_intro_left", 24))
        out.append(PlannerCandidate(_block("left", f"exact {pl[0][0]}"), PLANNER_TEMPLATE, "or_intro_left_tac", 30))
    pr = prover.prove(right)
    if pr:
        out.append(PlannerCandidate(f"exact Or.inr {_wrap(pr[0][0])}", PLANNER_TEMPLATE, "or_intro_right", 24))
        out.append(PlannerCandidate(_block("right", f"exact {pr[0][0]}"), PLANNER_TEMPLATE, "or_intro_right_tac", 30))
    return out


def _implication_goal_candidates(state: PlannerState) -> List[PlannerCandidate]:
    """Goal ``A → B (→ C ...)``: intro the antecedents, then prove the final
    consequent with the intro'd hypotheses available."""
    antecedents, consequent = _peel_arrows(state.goal)
    if not antecedents:
        return []
    taken = _existing_identifiers(state)
    names = _fresh_names(len(antecedents), taken)
    extra = list(zip(names, antecedents))
    prover = _Prover(state, extra_terms=extra)
    proofs = prover.prove(consequent)
    if not proofs:
        return []
    out: List[PlannerCandidate] = []
    term, kind = proofs[0]
    source = _KIND_TO_SOURCE.get(kind, PLANNER_CHAIN)
    names_str = " ".join(names)
    out.append(PlannerCandidate(
        _block(f"intro {names_str}", f"exact {term}"), source, "intro_exact", 32))
    out.append(PlannerCandidate(
        f"exact fun {names_str} => {term}", source, "intro_lambda", 33))
    return out


def _direct_goal_candidates(state: PlannerState, prover: "_Prover") -> List[PlannerCandidate]:
    """Prove the goal directly (no intro): hypothesis match, conjunction
    projection, modus-ponens chain, or iff-direction composition."""
    out: List[PlannerCandidate] = []
    for term, kind in prover.prove(state.goal):
        source = _KIND_TO_SOURCE.get(kind, PLANNER_CHAIN)
        priority = _KIND_PRIORITY.get(kind, 24)
        strategy = {"base": "exact_hyp", "proj": "exact_projection",
                    "app": "exact_chain", "iff": "exact_iff",
                    "and": "exact_and"}.get(kind, "exact_chain")
        out.append(PlannerCandidate(f"exact {term}", source, strategy, priority))
    return out


# ---------------- public API ----------------


def plan_candidates(
    theorem_statement: Optional[str],
    state_before: str,
    *,
    pattern_family: Optional[str] = None,
    max_candidates: int = 24,
) -> List[PlannerCandidate]:
    """Enumerate structured proof-block candidates for a prompt, deduplicated by
    tactic string and ordered by ``(priority, length, tactic)``.

    Existential goals are intentionally skipped — the symbolic witness-copy
    (:mod:`mini_elf_lean.elf_witness`) already handles them robustly and is a
    separate, audited source."""
    state = parse_planner_state(theorem_statement, state_before, pattern_family=pattern_family)
    if state.goal_shape == "exists_goal":
        return []

    prover = _Prover(state)
    cands: List[PlannerCandidate] = []
    cands.extend(_direct_goal_candidates(state, prover))
    cands.extend(_implication_goal_candidates(state))
    cands.extend(_and_goal_candidates(state, prover))
    cands.extend(_or_goal_candidates(state, prover))
    cands.extend(_eq_chain_candidates(state))
    cands.extend(_or_elim_candidates(state))

    # dedup by tactic, keep the lowest-priority (most confident) occurrence
    best: Dict[str, PlannerCandidate] = {}
    for c in cands:
        prev = best.get(c.tactic)
        if prev is None or c.priority < prev.priority:
            best[c.tactic] = c
    ordered = sorted(best.values(), key=lambda c: (c.priority, len(c.tactic), c.tactic))
    return ordered[:max_candidates]


def plan_candidate_strings(
    theorem_statement: Optional[str], state_before: str,
    *, pattern_family: Optional[str] = None,
) -> List[str]:
    """Just the ordered tactic strings (convenience for the sampler)."""
    return [c.tactic for c in plan_candidates(theorem_statement, state_before, pattern_family=pattern_family)]
