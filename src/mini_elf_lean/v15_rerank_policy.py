"""Mini-ELF v15 — operation-aware confidence-gated rerank policy.

The v15 evaluator's three configurations (raw / rule / learned) each
**win on different families**:

  * **rule** wins pass@1 on ``instantiate_forall`` (forall_inst) and
    ``rewrite`` (rewrite_succ) — the v12 hand-tuned features
    perfectly surface ``exact h <num>`` and ``rw [h]`` to rank 0.
  * **raw / learned** win on ``intro_negation`` (neg_imp_exfalso) and
    on ``exists_reconstruct`` (op=``unknown``) — rule actively
    de-ranks the verifying contrapositive / witness candidates.

The Part-5 brief calls this out and suggests a *confidence-gated*
operation-aware policy that picks the right sub-scorer per row. This
module implements that policy with a tiny, fully inspectable routing
table — **no new generation**, **no new templates**, **no manual
oracle**: it just selects which existing ranker (rule, learned, raw)
to use based on ``required_operation`` and (when both are applicable)
a learned-vs-rule confidence margin.

Honest scope:
  * The policy decides *which existing ranker to apply*. It cannot
    invent new candidates.
  * pass@10 is therefore strictly identical to v14's generator
    ceiling — only the order changes.
  * No ``state_after``.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from .learned_reranker import LearnedReranker
from .proof_block_reranker import rerank as rule_rerank_fn
from .rerank_dataset import CandidateRow


# --------------------------------------------------------------------------- #
# Routing table
# --------------------------------------------------------------------------- #


#: Operations where the v12 rule-based reranker is **strictly better
#: than learned** in the v15 audit (pass@1 = 1.000 vs 0.000 / 0.429).
#: For these we always use ``rule``.
USE_RULE: frozenset = frozenset({
    "instantiate_forall",  # forall_inst — `exact h <num>` schema is highly specific
    "rewrite",             # rewrite_succ — `rw [h]` schema is highly specific
})

#: Operations where the **raw / learned** ordering matches or beats rule
#: in v15 / v16 audits. For these we prefer ``learned`` (matches raw on
#: every case, falls through to raw on ties via the score-tie-break
#: logic).
#:
#: **v17 edit:** ``contradiction`` moved here from ``USE_DEFAULT_RULE``.
#: Under v14/v15 candidates, raw / rule / learned tied at neg_exfalso
#: pass@5 = 0.625 (so v15 used DEFAULT_RULE for continuity). Under v16
#: candidates the tie breaks: learned pass@1 = 0.625, rule pass@1 =
#: 0.375. The audit in ``docs/V17_RESIDUAL_FAILURE_AUDIT.md`` confirms
#: this; the test ``tests/test_v17_policy_edit.py`` pins the new
#: routing.
USE_LEARNED: frozenset = frozenset({
    "intro_negation",      # neg_imp_exfalso — rule pushes contrapositive past top-5
    "unknown",             # exists_reconstruct — rule promotes malformed ⟨...⟩
    "contradiction",       # v17: neg_exfalso — learned beats rule on v16 candidates
})

#: Operations where rule and learned are tied — historically defaulted
#: to ``rule`` for continuity with v12. The v17 edit emptied this set;
#: kept as a hook for future additions.
USE_DEFAULT_RULE: frozenset = frozenset()

#: The minimum learned-score margin (top1 vs top2) required for the
#: policy to *trust* learned in ambiguous cases. Below this margin,
#: fall back to ``rule``. Empirically tuned to be conservative.
LEARNED_CONFIDENCE_THRESHOLD: float = 0.10


# --------------------------------------------------------------------------- #
# Order primitives (mirror evaluate_v15_reranker.py)
# --------------------------------------------------------------------------- #


def _order_raw(cand_rows: Sequence[CandidateRow]) -> List[int]:
    seq2seq_idx: List[int] = []
    la_idx: List[int] = []
    other_idx: List[int] = []
    for i, r in enumerate(cand_rows):
        if r.candidate_source == "seq2seq_literal_adapt":
            la_idx.append(i)
        elif r.candidate_source in ("seq2seq", "token_seq2seq"):
            seq2seq_idx.append(i)
        else:
            other_idx.append(i)
    seq2seq_idx.sort(key=lambda i: cand_rows[i].beam_rank)
    la_idx.sort(key=lambda i: cand_rows[i].beam_rank)
    other_idx.sort(key=lambda i: cand_rows[i].beam_rank)
    return seq2seq_idx + la_idx + other_idx


def _order_rule(cand_rows: Sequence[CandidateRow], *, state_before: str,
                required_operation: Optional[str]) -> List[int]:
    items = [(r.candidate, r.candidate_source) for r in cand_rows]
    reranked = rule_rerank_fn(items, state_before=state_before,
                              required_operation=required_operation)
    idx_by_tactic = {}
    for j, r in enumerate(cand_rows):
        idx_by_tactic.setdefault(r.candidate, []).append(j)
    order: List[int] = []
    for c in reranked:
        js = idx_by_tactic.get(c.tactic, [])
        if js:
            order.append(js.pop(0))
    seen = set(order)
    for j in range(len(cand_rows)):
        if j not in seen:
            order.append(j)
    return order


def _order_learned(model: LearnedReranker,
                   cand_rows: Sequence[CandidateRow]) -> List[int]:
    scored = []
    for i, r in enumerate(cand_rows):
        p = model.score_row(r)
        scored.append((i, p, r.beam_rank))
    scored.sort(key=lambda t: (-t[1], t[2]))
    return [t[0] for t in scored]


def _learned_confidence_margin(model: LearnedReranker,
                               cand_rows: Sequence[CandidateRow]) -> float:
    scores = sorted(
        (model.score_row(r) for r in cand_rows), reverse=True)
    if len(scores) < 2:
        return 1.0
    return scores[0] - scores[1]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def choose_strategy(*, required_operation: Optional[str],
                    learned_confidence: float) -> str:
    """Return one of ``rule`` / ``learned`` / ``raw`` given the
    operation tag and the learned reranker's top-2 score margin.

    The choice is fully deterministic and inspectable — no learned
    decision layer on top of the route, just a switch.
    """
    op = (required_operation or "").lower().strip()
    if op in USE_RULE:
        return "rule"
    if op in USE_LEARNED:
        return "learned"
    if op in USE_DEFAULT_RULE:
        return "rule"
    # Unknown operation: defer to learned if confident, else rule.
    if learned_confidence >= LEARNED_CONFIDENCE_THRESHOLD:
        return "learned"
    return "rule"


def reorder(
    cand_rows: Sequence[CandidateRow],
    *,
    model: LearnedReranker,
    state_before: str = "",
    required_operation: Optional[str] = None,
) -> List[int]:
    """Apply the operation-aware policy to ``cand_rows``. Returns a
    permutation of ``range(len(cand_rows))``. Strategy selection is
    logged in the returned ``CandidateRow``s' metadata only if the
    caller asks (we keep this lightweight)."""
    if not cand_rows:
        return []
    margin = _learned_confidence_margin(model, cand_rows)
    strategy = choose_strategy(required_operation=required_operation,
                               learned_confidence=margin)
    if strategy == "rule":
        return _order_rule(cand_rows, state_before=state_before,
                           required_operation=required_operation)
    if strategy == "learned":
        return _order_learned(model, cand_rows)
    return _order_raw(cand_rows)


__all__ = [
    "USE_RULE", "USE_LEARNED", "USE_DEFAULT_RULE",
    "LEARNED_CONFIDENCE_THRESHOLD",
    "choose_strategy", "reorder",
]
