"""Mini-ELF v43 — coarse plan representation (the C1 intermediate granularity).

Three granularities span the abstraction axis:
  * head-only   `rw ; simp ; exact`                       (V40 headplan; 1 token/step)
  * COARSE      `rw ( ARG , ARG ) ; simp ( NONE ) ; exact ( ARG )`   (this module: arity kept,
                arg TYPES collapsed to a single generic ARG symbol)
  * full-typed  `rw ( LEMMA , LEMMA ) ; simp ( NONE ) ; exact ( TERM )`  (v41 plangen)

Coarse drops the LEMMA/HYP/TERM distinction (which V42-H16 implicated as flow's tokenization
wall) while keeping arity, so the plan stays groundable: the retrieval grounder fills each ARG
slot with a retrieved premise. This is the "head-mostly, args delegated to the grounder" plan the
V42 brief mandated. Built on the v41 factorizer so head coverage is identical.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from v41_plan_factorize import factorize_proof  # type: ignore


def to_coarse(typed_steps: Sequence[Tuple[str, List[str]]]) -> List[Tuple[str, List[str]]]:
    """Collapse a typed plan's arg slots to generic ARG (NONE stays NONE)."""
    out = []
    for head, args in typed_steps:
        if args == ["NONE"] or not args:
            out.append((head, ["NONE"]))
        else:
            out.append((head, ["ARG"] * len(args)))
    return out


def coarse_plan(proof: str, max_steps: int = 8) -> Optional[List[Tuple[str, List[str]]]]:
    typed = factorize_proof(proof, max_steps=max_steps)
    return to_coarse(typed) if typed else None


def coarse_to_str(steps: Sequence[Tuple[str, List[str]]]) -> str:
    return " ; ".join(f"{h} ( {' , '.join(a)} )" for h, a in steps)


def parse_coarse_str(s: str, max_steps: int = 8) -> List[Tuple[str, List[str]]]:
    """Inverse of coarse_to_str, tolerant of model-generated noise."""
    steps = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        if "(" in part and ")" in part:
            head = part[:part.index("(")].strip()
            inner = part[part.index("(") + 1:part.rindex(")")]
            args = [t.strip() for t in inner.split(",") if t.strip() in ("ARG", "NONE")]
        else:
            head = part.split()[0] if part.split() else ""
            args = ["NONE"]
        if head:
            steps.append((head, args or ["NONE"]))
        if len(steps) >= max_steps:
            break
    return steps


__all__ = ["to_coarse", "coarse_plan", "coarse_to_str", "parse_coarse_str"]
