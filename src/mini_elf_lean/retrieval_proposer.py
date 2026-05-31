"""Mini-ELF v5 — a train-free *retrieval* proof-block proposer.

The honest alternative to hand-authoring a symbolic template per proof shape
(v4's whack-a-mole): **retrieve verified tactic blocks from training data by
state/theorem similarity and adapt them lightly**. This is *example reuse*, not
reasoning — and it is reported as such. It works on the planner-blind families
only because the corpus uses consistent hypothesis names within a family, so a
same-family donor's verified tactic is (after light adaptation) correct on a
held-out sibling.

Mechanism (`fit` then `propose`):

  1. ``fit(train)`` indexes every training row's ``(theorem_statement,
     state_before) -> tactic`` as a char-n-gram vector (the same pure-Python
     cosine the retrieval baseline uses; no sklearn required).
  2. ``propose`` scores the query against the index, walks the nearest donors
     (skipping any sharing the query's ``theorem_name`` — a leakage guard), and
     emits each donor tactic **verbatim** plus light **adaptations**:

       * *numeric substitution* — copy a literal from the query goal into the
         donor's single numeric slot (`exact h 7` ⟶ `exact h 5`); this is what
         lets retrieval solve `forall_inst`, which no v4 template covered.
       * *hypothesis remap* — when a donor identifier is absent from the query
         but a query hypothesis of identical type exists, rename it. Inert on
         this corpus (names are constant) but kept for robustness.

Adaptation only ever *adds* candidates; the verbatim donor tactic is always
kept, and the lean-cli verifier is the sole arbiter of correctness. Never reads
``state_after``. Pure-Python / torch-free.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .baselines import _char_trigrams, _cosine_from_counters
from .elf_structure import extract_goal_line, extract_hypotheses, parse_binding
from .proposer import CandidateProposer, ProposedCandidate
from .retrieval_features import (
    NEG_GOAL,
    IMPLICATION_GOAL,
    OP_CONTRADICTION,
    OP_INTRO_NEGATION,
    OP_UNKNOWN,
    StateFeatures,
    connective_overlap,
    extract_features,
    goal_shape_match,
    hyp_shape_match,
    numeric_compatibility,
    operation_match,
    token_overlap,
)

RETRIEVAL_SOURCE = "retrieval"
RETRIEVAL_ADAPTED_SOURCE = "retrieval_adapted"

# Standalone non-negative integer literals: a digit run not glued to a word char
# or a `.` (so projections like `h.1` / `h.2.1` are NOT treated as literals).
_NUM_RE = re.compile(r"(?<![\w.])\d+(?!\w)")
# Word-boundary identifier replacement (Lean identifiers may carry `'`).
_IDENT_BOUNDARY = r"(?<![\w'.])"


@dataclass
class _Donor:
    counter: Counter
    norm: float
    tactic: str
    theorem_name: str
    state_before: str
    theorem_statement: str = ""


def _attr(row: Any, name: str) -> Any:
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _query_literals(state_before: str) -> List[str]:
    """Distinct integer literals in the prompt, **goal literals first** (so the
    goal's left-hand-side number — the intended ∀-instantiation witness — is the
    first substitution tried)."""
    goal = extract_goal_line(state_before)
    ordered: List[str] = []
    seen: set = set()
    for src in (goal, state_before):
        for m in _NUM_RE.finditer(src):
            tok = m.group(0)
            if tok not in seen:
                seen.add(tok)
                ordered.append(tok)
    return ordered


def _hyp_types(state_before: str) -> List[Tuple[str, str]]:
    """``[(name, type), …]`` for the prompt's hypotheses (best-effort, reusing
    the planner's binding parser)."""
    out: List[Tuple[str, str]] = []
    for line in extract_hypotheses(state_before):
        b = parse_binding(line)
        if b is None:
            continue
        names, ty = b
        for n in names:
            out.append((n, ty.strip()))
    return out


def _numeric_variants(tactic: str, query_lits: Sequence[str], max_variants: int) -> List[str]:
    """Variants of ``tactic`` with its single numeric literal replaced by each
    query literal. Empty unless the donor has exactly one distinct literal."""
    donor_lits = {m.group(0) for m in _NUM_RE.finditer(tactic)}
    if len(donor_lits) != 1:
        return []
    donor_lit = next(iter(donor_lits))
    out: List[str] = []
    for q in query_lits:
        if q == donor_lit:
            continue
        variant = _NUM_RE.sub(q, tactic)
        if variant != tactic and variant not in out:
            out.append(variant)
        if len(out) >= max_variants:
            break
    return out


def _hyp_remap_variant(tactic: str, donor_state: str, query_state: str) -> Optional[str]:
    """Rename donor identifiers to query hypotheses of identical type, when the
    donor name is absent from the query. Returns ``None`` when no remap applies
    or the corpus already shares names."""
    donor_hyps = _hyp_types(donor_state)
    query_hyps = _hyp_types(query_state)
    if not donor_hyps or not query_hyps:
        return None
    query_names = {n for n, _ in query_hyps}
    type_to_query: Dict[str, str] = {}
    for n, t in query_hyps:
        type_to_query.setdefault(t, n)
    name_map: Dict[str, str] = {}
    for dn, dt in donor_hyps:
        if dn in query_names:
            continue  # donor name already valid in the query
        repl = type_to_query.get(dt)
        if repl and repl != dn:
            name_map[dn] = repl
    if not name_map:
        return None
    remapped = tactic
    for dn, qn in name_map.items():
        remapped = re.sub(_IDENT_BOUNDARY + re.escape(dn) + r"(?![\w'])", qn, remapped)
    return remapped if remapped != tactic else None


class RetrievalProofBlockProposer(CandidateProposer):
    """k-NN retrieval of verified tactic blocks + light adaptation.

    ``neighbors`` donors are scored per query; their tactics are emitted in
    similarity order (verbatim, then adapted) until ``max_candidates``. Set
    ``enable_numeric_adapt`` / ``enable_hyp_remap`` to ablate the adaptation
    rules (retrieval-verbatim-only is the baseline-of-the-baseline)."""

    name = "retrieval"

    def __init__(
        self,
        *,
        neighbors: int = 24,
        enable_numeric_adapt: bool = True,
        enable_hyp_remap: bool = True,
        max_numeric_variants: int = 4,
    ) -> None:
        self.neighbors = max(neighbors, 1)
        self.enable_numeric_adapt = enable_numeric_adapt
        self.enable_hyp_remap = enable_hyp_remap
        self.max_numeric_variants = max_numeric_variants
        self._donors: List[_Donor] = []

    @property
    def mode(self) -> str:
        bits = [f"neighbors={self.neighbors}"]
        if self.enable_numeric_adapt:
            bits.append("numeric")
        if self.enable_hyp_remap:
            bits.append("hyp_remap")
        return "retrieval(" + ",".join(bits) + ")"

    def fit(self, train: Sequence[Any]) -> "RetrievalProofBlockProposer":
        donors: List[_Donor] = []
        for row in train:
            stmt = _attr(row, "theorem_statement") or ""
            state = _attr(row, "state_before") or ""
            tactic = _attr(row, "tactic")
            name = _attr(row, "theorem_name") or ""
            if not tactic:
                continue
            text = f"{stmt}\n{state}"
            counter = _char_trigrams(text)
            norm = math.sqrt(sum(v * v for v in counter.values()))
            donors.append(_Donor(counter=counter, norm=norm, tactic=tactic,
                                 theorem_name=name, state_before=state,
                                 theorem_statement=stmt))
        self._donors = donors
        return self

    def propose(
        self,
        theorem_statement: str,
        state_before: str,
        *,
        theorem_name: Optional[str] = None,
        pattern_family: Optional[str] = None,
        max_candidates: int = 10,
    ) -> List[ProposedCandidate]:
        if not self._donors:
            return []
        q = _char_trigrams(f"{theorem_statement}\n{state_before}")
        scored: List[Tuple[float, int]] = []
        for i, d in enumerate(self._donors):
            if theorem_name is not None and d.theorem_name == theorem_name:
                continue  # leakage guard: never retrieve the query theorem itself
            s = _cosine_from_counters(q, d.counter, b_norm=d.norm)
            if s > 0.0:
                scored.append((s, i))
        scored.sort(key=lambda si: (-si[0], self._donors[si[1]].tactic))

        query_lits = _query_literals(state_before) if self.enable_numeric_adapt else []
        out: List[ProposedCandidate] = []
        seen: set = set()

        def add(tac: str, source: str, score: float, meta: Dict[str, Any]) -> None:
            if tac in seen:
                return
            seen.add(tac)
            out.append(ProposedCandidate(tactic=tac, source=source, score=score, metadata=meta))

        for score, i in scored[: self.neighbors]:
            if len(out) >= max_candidates:
                break
            d = self._donors[i]
            base_meta = {"neighbor_theorem": d.theorem_name, "similarity": round(score, 4)}
            add(d.tactic, RETRIEVAL_SOURCE, score, dict(base_meta))
            if self.enable_numeric_adapt:
                for variant in _numeric_variants(d.tactic, query_lits, self.max_numeric_variants):
                    add(variant, RETRIEVAL_ADAPTED_SOURCE, score,
                        {**base_meta, "adaptation": "numeric", "from": d.tactic})
            if self.enable_hyp_remap:
                remapped = _hyp_remap_variant(d.tactic, d.state_before, state_before)
                if remapped is not None:
                    add(remapped, RETRIEVAL_ADAPTED_SOURCE, score,
                        {**base_meta, "adaptation": "hyp_remap", "from": d.tactic})

        return out[:max_candidates]


# ---------------- v6: structure-aware retrieval ----------------

# Default scoring weights. Override via data/configs/v6_retrieval.json or the
# StructureAwareRetrievalProposer(weights=...) argument.
DEFAULT_V6_WEIGHTS: Dict[str, float] = {
    "alpha_char": 1.0,            # char-n-gram similarity
    "beta_goal_shape": 1.0,       # goal-shape match
    "gamma_operation": 1.0,       # required-operation match
    "delta_connective": 0.5,      # connective-multiset cosine
    "epsilon_numeric": 0.5,       # numeric compatibility
    "zeta_hyp_shape": 0.75,       # hypothesis-shape-flag agreement
    "eta_token": 0.25,            # identifier/type token Jaccard
    "theta_conjunct_match": 1.0,  # F2: donor projects the SAME conjunct side as target
    # penalties (subtracted)
    "pen_operation_mismatch": 1.0,
    "pen_projection_mismatch": 1.5,   # F2: wrong conjunct side
    "pen_stale_literal": 2.0,         # F1: verbatim with a literal absent from target
    "pen_missing_intro": 1.5,         # F3: needs intro but donor tactic has none
    "pen_contradiction_noproof": 0.75,  # F4/Part5: plain `exact h` for a contradiction goal
    # bonus (added)
    "bonus_adapted": 0.25,            # F1: nudge a safe adaptation above the verbatim donor
}


def load_v6_weights(path: Optional[str | Path] = None) -> Dict[str, float]:
    """Default weights merged with an optional JSON override file."""
    w = dict(DEFAULT_V6_WEIGHTS)
    if path:
        p = Path(path)
        if p.exists():
            w.update({k: float(v) for k, v in json.loads(p.read_text(encoding="utf-8")).items()})
    return w


class StructureAwareRetrievalProposer(RetrievalProofBlockProposer):
    """v6 — re-ranks the same retrieval candidate set (verbatim + adaptations) by a
    weighted **structural** score instead of char-similarity alone, fixing v5's
    ranking failures (`docs/V6_RETRIEVAL_FAILURE_ANALYSIS.md`). It changes
    *ranking*, not proof construction — still example reuse, never a template."""

    name = "retrieval_v6"

    def __init__(
        self,
        *,
        weights: Optional[Dict[str, float]] = None,
        neighbors: int = 64,
        enable_numeric_adapt: bool = True,
        enable_hyp_remap: bool = True,
        max_numeric_variants: int = 4,
        enable_structural: bool = True,
        enable_adapt_preference: bool = True,
        forbid_same_family: bool = False,
        forbid_same_operation: bool = False,
        family_map: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(neighbors=neighbors, enable_numeric_adapt=enable_numeric_adapt,
                         enable_hyp_remap=enable_hyp_remap, max_numeric_variants=max_numeric_variants)
        self.weights = dict(DEFAULT_V6_WEIGHTS)
        if weights:
            self.weights.update(weights)
        self.enable_structural = enable_structural        # ablation: structural terms off
        self.enable_adapt_preference = enable_adapt_preference  # ablation: F1 fix off
        # v7 donor-scarcity probes (default OFF -> identical to v6). When on, the
        # retriever may not reuse a donor sharing the query's family / operation,
        # so any verified candidate must transfer from a different proof family.
        self.forbid_same_family = forbid_same_family
        self.forbid_same_operation = forbid_same_operation
        self.family_map: Dict[str, str] = dict(family_map or {})
        self._donor_feats: List[StateFeatures] = []

    @property
    def mode(self) -> str:
        bits = [f"neighbors={self.neighbors}"]
        bits.append("structural" if self.enable_structural else "char_only")
        if self.enable_numeric_adapt:
            bits.append("numeric")
        if self.enable_adapt_preference:
            bits.append("adapt_pref")
        if self.forbid_same_family:
            bits.append("no_same_family")
        if self.forbid_same_operation:
            bits.append("no_same_operation")
        return "retrieval_v6(" + ",".join(bits) + ")"

    def fit(self, train: Sequence[Any]) -> "StructureAwareRetrievalProposer":
        super().fit(train)
        self._donor_feats = [extract_features(d.theorem_statement, d.state_before) for d in self._donors]
        return self

    def _candidate_variants(self, d, query_lits, query_state) -> List[Tuple[str, str, Dict[str, Any]]]:
        """(tactic, source, adapt_meta) — verbatim + enabled adaptations."""
        out = [(d.tactic, RETRIEVAL_SOURCE, {"adapted": False, "adaptation_kind": "none"})]
        if self.enable_numeric_adapt:
            for v in _numeric_variants(d.tactic, query_lits, self.max_numeric_variants):
                out.append((v, RETRIEVAL_ADAPTED_SOURCE, {"adapted": True, "adaptation_kind": "numeric"}))
        if self.enable_hyp_remap:
            rm = _hyp_remap_variant(d.tactic, d.state_before, query_state)
            if rm is not None:
                out.append((rm, RETRIEVAL_ADAPTED_SOURCE, {"adapted": True, "adaptation_kind": "hyp_rename"}))
        return out

    def _donor_score(self, char: float, tf: StateFeatures, df: StateFeatures) -> Tuple[float, float]:
        """Return (donor_score, structural_component)."""
        w = self.weights
        if not self.enable_structural:
            return w["alpha_char"] * char, 0.0
        structural = (
            w["beta_goal_shape"] * goal_shape_match(tf, df)
            + w["gamma_operation"] * operation_match(tf, df)
            + w["delta_connective"] * connective_overlap(tf, df)
            + w["epsilon_numeric"] * numeric_compatibility(tf, df)
            + w["zeta_hyp_shape"] * hyp_shape_match(tf, df)
            + w["eta_token"] * token_overlap(tf, df)
        )
        if (tf.goal_conjunct_position in ("left", "right")
                and df.goal_conjunct_position == tf.goal_conjunct_position):
            structural += w["theta_conjunct_match"]
        pen = 0.0
        if (tf.required_operation != OP_UNKNOWN and df.required_operation != OP_UNKNOWN
                and tf.required_operation != df.required_operation):
            pen += w["pen_operation_mismatch"]
        if (tf.goal_conjunct_position != "none" and df.goal_conjunct_position != "none"
                and tf.goal_conjunct_position != df.goal_conjunct_position):
            pen += w["pen_projection_mismatch"]
        return w["alpha_char"] * char + structural - pen, structural

    def _candidate_adjustment(self, tac: str, adapted: bool, tf: StateFeatures, query_lits) -> float:
        w = self.weights
        adj = 0.0
        # F1: stale-literal penalty on a verbatim donor whose literal is absent from
        # the target (and a numeric adaptation is therefore available).
        if self.enable_adapt_preference:
            donor_lits = {m.group(0) for m in _NUM_RE.finditer(tac)}
            if not adapted and donor_lits and tf.numeric_literals and not (donor_lits <= tf.numeric_literals):
                adj -= w["pen_stale_literal"]
            if adapted:
                adj += w["bonus_adapted"]
        # F3: target needs an `intro` (¬/→ goal via ex falso) but the candidate has none.
        if self.enable_structural:
            needs_intro = (tf.required_operation == OP_INTRO_NEGATION
                           and tf.goal_shape in (NEG_GOAL, IMPLICATION_GOAL))
            if needs_intro and not (tac.lstrip().startswith("intro") or "fun " in tac):
                adj -= w["pen_missing_intro"]
            # F4/Part5: a contradiction goal wants an actual ex-falso proof, not a bare `exact h`.
            if tf.required_operation == OP_CONTRADICTION:
                body = tac.strip()
                if body.startswith("exact ") and not any(
                        k in body for k in ("absurd", "False", "elim", "⟨")):
                    adj -= w["pen_contradiction_noproof"]
        return adj

    def propose(
        self,
        theorem_statement: str,
        state_before: str,
        *,
        theorem_name: Optional[str] = None,
        pattern_family: Optional[str] = None,
        max_candidates: int = 10,
    ) -> List[ProposedCandidate]:
        if not self._donors:
            return []
        tf = extract_features(theorem_statement, state_before)
        q = _char_trigrams(f"{theorem_statement}\n{state_before}")
        query_lits = _query_literals(state_before) if self.enable_numeric_adapt else []

        query_family = self.family_map.get(theorem_name) if theorem_name is not None else None
        scored: List[Tuple[float, int, int, ProposedCandidate]] = []
        gen = 0  # generation order: LHS-first within a donor (numeric adaptation)
        for i, d in enumerate(self._donors):
            if theorem_name is not None and d.theorem_name == theorem_name:
                continue  # leakage guard
            df = self._donor_feats[i] if i < len(self._donor_feats) else extract_features(d.theorem_statement, d.state_before)
            donor_family = self.family_map.get(d.theorem_name)
            # v7 donor-scarcity filters (no-ops unless explicitly enabled).
            if (self.forbid_same_family and query_family is not None
                    and donor_family == query_family):
                continue
            if (self.forbid_same_operation
                    and tf.required_operation != OP_UNKNOWN
                    and df.required_operation == tf.required_operation):
                continue
            char = _cosine_from_counters(q, d.counter, b_norm=d.norm)
            donor_score, structural = self._donor_score(char, tf, df)
            for tac, source, adapt_meta in self._candidate_variants(d, query_lits, state_before):
                adj = self._candidate_adjustment(tac, adapt_meta["adapted"], tf, query_lits)
                total = donor_score + adj
                meta = {
                    "neighbor_theorem": d.theorem_name,
                    "donor_family": donor_family,
                    "char_score": round(char, 4),
                    "structural_score": round(structural, 4),
                    "adaptation_score": round(adj, 4),
                    "total_score": round(total, 4),
                    "donor_operation": df.required_operation,
                    "donor_goal_shape": df.goal_shape,
                    "donor_tactic": d.tactic,
                    "target_operation": tf.required_operation,
                    "target_goal_shape": tf.goal_shape,
                    "target_literals": sorted(tf.numeric_literals),
                    **adapt_meta,
                }
                # tie-break rank: adapted candidates first, then generation order
                # (which is LHS-first for numeric variants, so `exact h 9` beats
                # `exact h 4` on goal `9 = 4`).
                tie = (0 if adapt_meta["adapted"] else 1, gen)
                scored.append((total, tie[0], tie[1], ProposedCandidate(
                    tactic=tac, source=source, score=total, metadata=meta)))
                gen += 1

        # Rank by total score; tie-break (adapted-first, generation order).
        scored.sort(key=lambda t: (-t[0], t[1], t[2]))
        out: List[ProposedCandidate] = []
        seen: set = set()
        for _total, _adapted, _gen, cand in scored:
            if cand.tactic in seen:
                continue
            seen.add(cand.tactic)
            out.append(cand)
            if len(out) >= max_candidates:
                break
        return out
