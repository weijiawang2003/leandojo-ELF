"""Mini-ELF v1 — lightweight structure-aware parsing of Lean tactic states.

A *heuristic* parser (no Lean AST) for the theorem-level prompts the rest of the
project already uses: ``theorem_statement`` plus a ``state_before`` of the form

    p q : Prop
    h : p ∧ q
    ⊢ p

It splits around the turnstile ``⊢`` — everything before is context /
hypotheses, everything after is the goal — and exposes rough features the v1
condition encoder and reranker consume: goal shape, goal/hypothesis token
symbols, numeric literals, identifiers, and the parsed binary structure of
conjunction hypotheses / disjunction goals (the relational signal that tells
``and_elim_left`` from ``and_elim_right`` and ``or_intro_left`` from
``or_intro_right``).

Honesty: this reads only ``theorem_statement`` + ``state_before`` text. It never
touches ``state_after`` (there is no such field here). It is *not* a claim of
real proof-state modeling — the parser is a string heuristic over the existing
theorem-level prompts.

Pure-Python and torch-free, so it can be unit-tested without torch. The optional
:class:`StructuredConditionEncoder` (used by v1 training) is defined in a
``torch``-guarded block at the bottom of the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

TURNSTILE = "⊢"

# Goal-shape labels (rough; top-level connective only).
AND_GOAL = "and_goal"
OR_GOAL = "or_goal"
IFF_GOAL = "iff_goal"
IMPLICATION_GOAL = "implication_goal"
EQUALITY_GOAL = "equality_goal"
EXISTS_GOAL = "exists_goal"
TRUE_GOAL = "true_goal"
FALSE_GOAL = "false_goal"
UNKNOWN_GOAL = "unknown"

GOAL_SHAPES: Tuple[str, ...] = (
    AND_GOAL, OR_GOAL, IFF_GOAL, IMPLICATION_GOAL, EQUALITY_GOAL,
    EXISTS_GOAL, TRUE_GOAL, FALSE_GOAL, UNKNOWN_GOAL,
)

# Identifiers: start with a (unicode) letter or underscore, not a digit. Greek
# letters like α/β are word characters, so `[^\W\d]` admits them. We deliberately
# do *not* include `.` so `Or.inl` tokenizes to `Or`, `inl` (head + projection).
_IDENT_RE = re.compile(r"[^\W\d][\w']*", re.UNICODE)
_NUMERIC_RE = re.compile(r"\d+")

# Brackets tracked for depth-0 scanning (so `(a ∧ b)` inside `(a ∧ b) → c` is not
# mistaken for the top-level connective).
_OPEN = {"(": ")", "[": "]", "{": "}", "⟨": "⟩"}
_CLOSE = {v: k for k, v in _OPEN.items()}


# ---------------- low-level scanning ----------------


def _depth0_find(expr: str, op: str) -> int:
    """Index of the first occurrence of ``op`` at bracket depth 0, else -1.

    ``=`` is matched only as a standalone equality (not part of ``:=``, ``==``,
    ``=>``, ``≤``/``≥`` which do not use a bare ``=``)."""
    depth = 0
    i = 0
    n = len(expr)
    L = len(op)
    while i < n:
        ch = expr[i]
        if ch in _OPEN:
            depth += 1
            i += 1
            continue
        if ch in _CLOSE:
            depth = max(depth - 1, 0)
            i += 1
            continue
        if depth == 0 and expr[i : i + L] == op:
            if op == "=":
                prev = expr[i - 1] if i > 0 else ""
                nxt = expr[i + 1] if i + 1 < n else ""
                if prev == ":" or nxt in ("=", ">"):
                    i += 1
                    continue
            return i
        i += 1
    return -1


def split_binary(expr: str, op: str) -> Optional[Tuple[str, str]]:
    """Split ``expr`` on the first depth-0 ``op`` into ``(lhs, rhs)`` (stripped).

    Returns ``None`` if ``op`` does not occur at depth 0. Used to pull the two
    sides of ``A ∧ B`` / ``A ∨ B`` for the relational sibling features."""
    idx = _depth0_find(expr, op)
    if idx < 0:
        return None
    return expr[:idx].strip(), expr[idx + len(op) :].strip()


def _strip_outer_parens(expr: str) -> str:
    """Drop a single layer of fully-enclosing parens: ``(a ∧ b)`` -> ``a ∧ b``."""
    e = expr.strip()
    while len(e) >= 2 and e[0] == "(" and e[-1] == ")":
        depth = 0
        enclosing = True
        for j, ch in enumerate(e):
            if ch in _OPEN:
                depth += 1
            elif ch in _CLOSE:
                depth -= 1
                if depth == 0 and j != len(e) - 1:
                    enclosing = False
                    break
        if enclosing:
            e = e[1:-1].strip()
        else:
            break
    return e


# ---------------- public feature helpers ----------------


def extract_goal_line(text: str) -> str:
    """Goal = everything after the first ``⊢`` (its line + any continuation
    lines), stripped. If there is no turnstile, the whole text is treated as the
    goal (so a bare ``theorem_statement`` body still classifies)."""
    idx = text.find(TURNSTILE)
    if idx < 0:
        return text.strip()
    return text[idx + len(TURNSTILE) :].strip()


def _is_binding_line(line: str) -> bool:
    """True if ``line`` is a hypothesis binding ``names : type`` whose left side
    is a plain space-separated identifier list. This excludes a prepended
    theorem-statement signature line like ``(p q : Prop) (h : p ∧ q) : p`` whose
    left side starts with ``(``."""
    if " : " not in line:
        return False
    lhs = line.split(" : ", 1)[0].strip()
    if not lhs:
        return False
    return all(_IDENT_RE.fullmatch(tok) for tok in lhs.split())


def extract_hypotheses(text: str) -> List[str]:
    """Raw hypothesis lines (``name(s) : type``) appearing before the turnstile.

    Robust to a prepended statement line: only genuine ``names : type`` bindings
    are returned (see :func:`_is_binding_line`)."""
    idx = text.find(TURNSTILE)
    head = text[:idx] if idx >= 0 else text
    out: List[str] = []
    for raw in head.split("\n"):
        line = raw.strip()
        if line and _is_binding_line(line):
            out.append(line)
    return out


def parse_binding(line: str) -> Optional[Tuple[List[str], str]]:
    """``"p q : Prop"`` -> ``(["p", "q"], "Prop")``; ``None`` if not a binding."""
    if not _is_binding_line(line):
        return None
    lhs, rhs = line.split(" : ", 1)
    return lhs.split(), rhs.strip()


def extract_numeric_literals(text: str) -> List[str]:
    """Digit-string literals in order of first appearance (dedup-preserving).
    ``∃ n : Nat, n = 5`` -> ``["5"]``; ``n = n`` -> ``[]``."""
    seen: set = set()
    out: List[str] = []
    for m in _NUMERIC_RE.findall(text):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def extract_identifiers(text: str) -> List[str]:
    """Identifier tokens in order of first appearance (dedup-preserving)."""
    seen: set = set()
    out: List[str] = []
    for m in _IDENT_RE.findall(text):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def classify_goal_shape(goal: str) -> str:
    """Rough top-level shape of a goal expression. Scans at bracket depth 0 and
    returns the loosest-binding connective present; binders/atoms handled first."""
    g = _strip_outer_parens(goal.strip())
    if not g:
        return UNKNOWN_GOAL
    if g == "True":
        return TRUE_GOAL
    if g == "False":
        return FALSE_GOAL
    if g.startswith("∃") or g.startswith("Exists"):
        return EXISTS_GOAL
    # Loosest-binding first: ↔ , → , ∨ , ∧ , = .
    if _depth0_find(g, "↔") >= 0:
        return IFF_GOAL
    if _depth0_find(g, "→") >= 0:
        return IMPLICATION_GOAL
    if _depth0_find(g, "∨") >= 0:
        return OR_GOAL
    if _depth0_find(g, "∧") >= 0:
        return AND_GOAL
    if _depth0_find(g, "=") >= 0:
        return EQUALITY_GOAL
    return UNKNOWN_GOAL


# ---------------- structured state ----------------


@dataclass
class StructuredState:
    """Heuristic structured view of a tactic-state prompt."""

    raw_text: str
    theorem_statement: Optional[str]
    hypotheses: List[str]
    goal: str
    goal_shape: str
    goal_symbols: List[str]
    hypothesis_symbols: List[str]
    numeric_literals: List[str]
    identifiers: List[str]
    pattern_family: Optional[str] = None
    # Parsed relational structure (the sibling-disambiguation signal):
    hyp_bindings: List[Tuple[List[str], str]] = field(default_factory=list)
    conjunction_hyps: List[Tuple[str, str, str]] = field(default_factory=list)  # (name, lhs, rhs)
    goal_disjuncts: Optional[Tuple[str, str]] = None  # (lhs, rhs) if goal is A ∨ B

    @property
    def value_witnesses(self) -> List[str]:
        """Hypothesis names whose declared type is *not* ``Prop`` and not itself a
        ``Type``/``Sort`` binder — i.e. plausible value witnesses for ``∃`` goals
        (e.g. ``a : α`` -> ``a``). Heuristic, used only as candidate witnesses."""
        out: List[str] = []
        type_names = {
            n for names, ty in self.hyp_bindings if ty in ("Type", "Sort", "Type*")
            for n in names
        }
        for names, ty in self.hyp_bindings:
            if ty in ("Prop", "Type", "Sort", "Type*"):
                continue
            # value-level: its type is one of the declared type variables, or any
            # non-Prop atom. Skip hypotheses that are proofs of compound props.
            if ty in type_names or _IDENT_RE.fullmatch(ty):
                out.extend(names)
        return out


def parse_tactic_state_text(
    text: str,
    *,
    theorem_statement: Optional[str] = None,
    pattern_family: Optional[str] = None,
) -> StructuredState:
    """Parse a tactic-state prompt into a :class:`StructuredState`.

    ``text`` may be a bare ``state_before`` or a combined
    ``theorem_statement\\nstate_before`` prompt — a prepended statement line is
    automatically excluded from the hypothesis list. Numeric literals are scanned
    over both ``theorem_statement`` (if given) and ``text`` so witness numbers in
    the statement are captured."""
    goal = extract_goal_line(text)
    hyp_lines = extract_hypotheses(text)
    bindings: List[Tuple[List[str], str]] = []
    for line in hyp_lines:
        b = parse_binding(line)
        if b is not None:
            bindings.append(b)

    conj_hyps: List[Tuple[str, str, str]] = []
    for names, ty in bindings:
        parts = split_binary(ty, "∧")
        if parts is not None:
            for nm in names:
                conj_hyps.append((nm, parts[0], parts[1]))

    shape = classify_goal_shape(goal)
    goal_disjuncts = None
    if shape == OR_GOAL:
        goal_disjuncts = split_binary(_strip_outer_parens(goal), "∨")

    numeric_src = (theorem_statement or "") + "\n" + text
    return StructuredState(
        raw_text=text,
        theorem_statement=theorem_statement,
        hypotheses=hyp_lines,
        goal=goal,
        goal_shape=shape,
        goal_symbols=extract_identifiers(goal),
        hypothesis_symbols=extract_identifiers("\n".join(hyp_lines)),
        numeric_literals=extract_numeric_literals(numeric_src),
        identifiers=extract_identifiers(text),
        pattern_family=pattern_family,
        hyp_bindings=bindings,
        conjunction_hyps=conj_hyps,
        goal_disjuncts=goal_disjuncts,
    )


def parse_prompt(
    theorem_statement: str, state_before: str, *, pattern_family: Optional[str] = None
) -> StructuredState:
    """Convenience wrapper that keeps ``theorem_statement`` separate from
    ``state_before`` (the form the v1 pipeline uses)."""
    return parse_tactic_state_text(
        state_before, theorem_statement=theorem_statement, pattern_family=pattern_family
    )


# ---------------- optional torch condition encoder ----------------

try:  # pragma: no cover - exercised by import, gated in tests
    import torch
    import torch.nn as nn

    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch = None  # type: ignore
    nn = None  # type: ignore
    _TORCH_AVAILABLE = False


# Stable index for the goal-shape embedding (kept here so train + load agree).
GOAL_SHAPE_TO_IDX = {s: i for i, s in enumerate(GOAL_SHAPES)}


def goal_shape_index(goal: str) -> int:
    return GOAL_SHAPE_TO_IDX[classify_goal_shape(goal)]


def numeric_feature_vector(state: StructuredState) -> List[float]:
    """A tiny fixed-width dense feature vector summarizing structure (used by the
    structured condition encoder). Order is stable; values are mildly scaled."""
    n_num = len(state.numeric_literals)
    n_hyp = len(state.hypotheses)
    return [
        min(n_num, 5) / 5.0,
        1.0 if n_num else 0.0,
        min(n_hyp, 5) / 5.0,
        1.0 if state.goal_shape == EXISTS_GOAL else 0.0,
        1.0 if state.conjunction_hyps else 0.0,
        1.0 if state.goal_disjuncts is not None else 0.0,
    ]


NUMERIC_FEATURE_DIM = 6


if _TORCH_AVAILABLE:

    class StructuredConditionEncoder(nn.Module):
        """v1 condition encoder: keeps the v0 raw-prompt bi-GRU and *adds* a goal
        bi-GRU, a learned goal-shape embedding, and a small structural feature
        MLP. The four signals are concatenated and projected to ``cond_dim``.

        Drop-in for :class:`mini_elf_lean.elf_embed.ConditionEncoder` from the
        flow's point of view: ``forward(...)`` returns a ``(B, cond_dim)`` tensor.
        The extra structured inputs are supplied as separate padded tensors so the
        v0 model and tests that use the plain encoder are unaffected.
        """

        def __init__(
            self,
            vocab_size: int,
            cond_dim: int = 128,
            *,
            emb: int = 48,
            raw_hidden: int = 128,
            goal_hidden: int = 48,
            shape_dim: int = 8,
            n_shapes: int = len(GOAL_SHAPES),
            num_feat_dim: int = NUMERIC_FEATURE_DIM,
            dropout: float = 0.1,
            pad_id: int = 0,
        ) -> None:
            super().__init__()
            self.cond_dim = cond_dim
            self.pad_id = pad_id
            self.embedding = nn.Embedding(vocab_size, emb, padding_idx=pad_id)
            self.raw_gru = nn.GRU(emb, raw_hidden, batch_first=True, bidirectional=True)
            self.goal_gru = nn.GRU(emb, goal_hidden, batch_first=True, bidirectional=True)
            self.shape_emb = nn.Embedding(n_shapes, shape_dim)
            self.num_mlp = nn.Sequential(nn.Linear(num_feat_dim, shape_dim), nn.SiLU())
            fused = 2 * raw_hidden + 2 * goal_hidden + shape_dim + shape_dim
            self.proj = nn.Sequential(nn.Linear(fused, cond_dim), nn.SiLU())
            self.dropout = nn.Dropout(dropout)

        def _encode_seq(self, gru, src, src_len):
            emb = self.dropout(self.embedding(src))
            packed = nn.utils.rnn.pack_padded_sequence(
                emb, src_len.cpu(), batch_first=True, enforce_sorted=False
            )
            _, hidden = gru(packed)  # (2, B, H)
            return torch.cat([hidden[0], hidden[1]], dim=-1)  # (B, 2H)

        def forward(self, raw_src, raw_len, goal_src, goal_len, shape_idx, num_feats):
            raw = self._encode_seq(self.raw_gru, raw_src, raw_len)  # (B, 2*raw_hidden)
            goal = self._encode_seq(self.goal_gru, goal_src, goal_len)  # (B, 2*goal_hidden)
            shape = self.shape_emb(shape_idx)  # (B, shape_dim)
            num = self.num_mlp(num_feats)  # (B, shape_dim)
            return self.proj(torch.cat([raw, goal, shape, num], dim=-1))  # (B, cond_dim)

    def _encode_source_batch(texts, vocab, max_len, device):
        pad = vocab.pad_id
        ids = [vocab.encode_source(t)[:max_len] or [pad] for t in texts]
        m = max(len(s) for s in ids)
        src = torch.tensor([s + [pad] * (m - len(s)) for s in ids], dtype=torch.long, device=device)
        src_len = torch.tensor([len(s) for s in ids], dtype=torch.long)
        return src, src_len

    def structured_inputs_from_prompts(pairs, vocab, max_cond_len, max_goal_len, device):
        """Build the six structured-encoder input tensors from a list of
        ``(theorem_statement, state_before)`` pairs. Shared by v1 train + sample
        so the encoder always sees identically-constructed inputs."""
        prompts, goals, shapes, nums = [], [], [], []
        for stmt, state in pairs:
            st = parse_prompt(stmt, state)
            prompts.append(f"{stmt}\n{state}")
            goals.append(st.goal)
            shapes.append(GOAL_SHAPE_TO_IDX[st.goal_shape])
            nums.append(numeric_feature_vector(st))
        raw_src, raw_len = _encode_source_batch(prompts, vocab, max_cond_len, device)
        goal_src, goal_len = _encode_source_batch(goals, vocab, max_goal_len, device)
        shape_idx = torch.tensor(shapes, dtype=torch.long, device=device)
        num = torch.tensor(nums, dtype=torch.float32, device=device)
        return raw_src, raw_len, goal_src, goal_len, shape_idx, num
