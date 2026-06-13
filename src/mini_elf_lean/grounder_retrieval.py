"""Mini-ELF v43 — premise-selection retrieval grounder.

Replaces the v41 neural copy-grounder (ceiling 0.267, premise-selection-limited) with a
BM25 retriever over the 241k-premise Mathlib pool (LeanDojo corpus): given a theorem statement,
retrieve in-scope candidate premises, then fill a plan's argument slots with them by template.
This is the ReProver-style premise selector realized lexically — training-free, sound, and the
direct test of V42's prediction that the grounder wall is *lemma knowledge*, not search.

Interface mirrors the v41 grounder so e2e scripts are drop-in:
    g = RetrievalGrounder(); proofs = g.ground(stmt, state_before, plan_steps, K=24)
returns up to K candidate proof strings, ranked best-first (lower BM25 rank-sum first).
"""
from __future__ import annotations

import json
import re
from heapq import nsmallest
from itertools import product
from pathlib import Path
from typing import List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
PREM = ROOT / "data/v43/premises"

_TOK = re.compile(r"[A-Za-z][A-Za-z0-9']*")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")

# heads that take no argument (slot ignored)
NOARG = {"rfl", "simp", "ring", "ring_nf", "omega", "norm_num", "tauto", "decide",
         "aesop", "constructor", "trivial", "positivity", "linarith", "nlinarith",
         "field_simp", "assumption", "rfl'", "ext", "intro", "intros"}
# heads whose args go in [ ... ]
BRACKET = {"rw", "simp", "simp_all", "simp_only", "rw_mod_cast", "erw", "unfold",
           "rewrite", "simpa"}
# heads whose arg is a bare term
BARE = {"exact", "apply", "refine", "exact_mod_cast", "have", "use", "convert"}


def _q_tokens(text: str) -> List[str]:
    return [t.lower() for t in _TOK.findall(text)]


def hyp_names(statement: str) -> List[str]:
    """Local hypothesis binder names from `(h : …)` / `(h h2 : …)` groups."""
    out = []
    for m in re.finditer(r"\(([^():]+):", statement):
        for nm in m.group(1).split():
            if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_']*", nm) and len(nm) <= 12:
                out.append(nm)
    return out


class BM25Retriever:
    def __init__(self, index_dir: Path = PREM, k1: float = 1.5, b: float = 0.75):
        self.names = json.loads((index_dir / "premises.json").read_text())["names"]
        bm = json.loads((index_dir / "bm25.json").read_text())
        self.idf = bm["idf"]
        self.postings = bm["postings"]
        self.dl = bm["dl"]
        self.avgdl = bm["avgdl"]
        self.k1, self.b = k1, b

    def retrieve(self, query: str, topn: int = 20, exclude: Sequence[str] = ()) -> List[str]:
        q = set(_q_tokens(query))
        ex = set(exclude)
        scores: dict[int, float] = {}
        for t in q:
            idf = self.idf.get(t)
            if idf is None:
                continue
            for doc_i, tf in self.postings.get(t, ()):  # type: ignore[union-attr]
                denom = tf + self.k1 * (1 - self.b + self.b * self.dl[doc_i] / self.avgdl)
                scores[doc_i] = scores.get(doc_i, 0.0) + idf * (tf * (self.k1 + 1)) / denom
        ranked = nsmallest(topn + len(ex), scores.items(), key=lambda kv: -kv[1])
        return [self.names[i] for i, _ in ranked if self.names[i] not in ex][:topn]


def _render_step(head: str, slot_count: int, fills: List[str]) -> str:
    """Render one plan step (head + chosen arg fills) into a tactic string."""
    h = head
    if h in NOARG and slot_count == 0:
        return h
    args = [f for f in fills if f]
    if not args:
        return h if h in NOARG else f"{h}"
    if h in BRACKET:
        return f"{h} [{', '.join(args)}]"
    if h in BARE:
        return f"{h} {args[0]}"
    # default: treat like a bracket lemma application for unknown heads
    if h in NOARG:
        return f"{h} [{', '.join(args)}]"
    return f"{h} {args[0]}"


class RetrievalGrounder:
    def __init__(self, index_dir: Path = PREM, topn: int = 24, per_slot: int = 8):
        self.r = BM25Retriever(index_dir)
        self.topn = topn
        self.per_slot = per_slot

    def ground(self, statement: str, state_before: str, plan_steps: Sequence[Tuple[str, list]],
               *, K: int = 24, exclude: Sequence[str] = ()) -> List[str]:
        """Return up to K candidate proof strings, ranked best-first."""
        query = f"{statement} {state_before or ''}"
        premises = self.r.retrieve(query, topn=self.topn, exclude=exclude)
        hyps = hyp_names(statement)
        # arg pool per slot type: LEMMA/TERM -> premises (+ hyps for TERM), HYP -> hyps
        lemma_pool = premises[: self.per_slot] or ["rfl"]
        term_pool = (hyps + premises)[: self.per_slot] or ["rfl"]
        hyp_pool = (hyps or ["this"])[: self.per_slot]

        # Build per-step slot choice lists with rank (index = rank, lower=better)
        step_choices = []  # list over steps of (head, list-of-(fill-tuple, rankcost))
        for head, slot_types in plan_steps:
            real_slots = [s for s in slot_types if s in ("LEMMA", "TERM", "HYP")]
            if not real_slots:
                step_choices.append((head, [((), 0)]))
                continue
            per = []
            for st in real_slots:
                pool = {"LEMMA": lemma_pool, "TERM": term_pool, "HYP": hyp_pool}[st]
                per.append(list(enumerate(pool)))
            # joint fills for this step: top combos by rank-sum, capped
            combos = []
            for combo in product(*per):
                cost = sum(rank for rank, _ in combo)
                fills = tuple(v for _, v in combo)
                combos.append((fills, cost))
            combos = nsmallest(min(len(combos), max(K, 8)), combos, key=lambda c: c[1])
            step_choices.append((head, combos))

        # joint over steps: best-first by total rank-cost, cap K
        joint = []
        # cap branching: take top few combos per step before product
        capped = [(head, choices[: max(2, K // max(1, len(step_choices)))]) for head, choices in step_choices]
        for combo in product(*[c for _, c in capped]):
            cost = sum(cc[1] for cc in combo)
            joint.append((combo, cost))
            if len(joint) > 4000:
                break
        joint = nsmallest(K * 3, joint, key=lambda c: c[1])

        seen, out = set(), []
        for combo, _cost in joint:
            lines = []
            for (head, _ch), (fills, _c) in zip(capped, combo):
                lines.append(_render_step(head, len(fills), list(fills)))
            proof = "\n".join(lines)
            if proof not in seen:
                seen.add(proof)
                out.append(proof)
            if len(out) >= K:
                break
        return out


__all__ = ["BM25Retriever", "RetrievalGrounder", "hyp_names"]
