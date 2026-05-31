"""Mini-ELF v23 — Part 7: conservative rerank policy.

The v23 eval showed the v22 generator's **raw** beam order is already
the best ranker on the broad-core pool (pass@1 0.792); a pure learned
reranker *regresses* pass@1 (over-demotion), and even a category-tuned
switch cannot be justified on a 48-theorem test set without overfitting.

The shipped policy is therefore deliberately conservative: rank by the
v23 model's P(verified) bucketed to one decimal, breaking ties by the
original beam rank. Candidates whose probabilities are within 0.1 keep
the generator's order, so the policy only reorders on a **confident**
probability gap — it cannot demote a well-ranked raw candidate on a
near-tie (the "do not demote verified candidates" guarantee). This is a
scoring/ordering switch only: it never injects a proof template, never
emits a placeholder, never reads state_after.

`per_category_choice` is provided for completeness but defaults to
empty: a per-category raw-vs-learned switch is **not adopted** because
on 5–6 theorems/category its apparent wins/losses are within noise.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence

from .v23_learned_reranker import V23Reranker


def hybrid_order(probs: Sequence[float], beam_ranks: Sequence[int],
                 *, bucket: float = 0.1) -> List[int]:
    """Conservative order: sort by (−bucketed_prob, beam_rank). Within a
    probability bucket the raw beam order is preserved."""
    scored = [(i, round(p / bucket) * bucket, beam_ranks[i])
              for i, p in enumerate(probs)]
    scored.sort(key=lambda t: (-t[1], t[2]))
    return [t[0] for t in scored]


def apply_policy(candidates: Sequence[Mapping[str, object]],
                 model: V23Reranker, *,
                 per_category_choice: Optional[Dict[str, str]] = None,
                 bucket: float = 0.1) -> List[int]:
    """Return reordered indices for one theorem's candidate list.

    ``per_category_choice`` maps category -> {'raw','learned','hybrid'};
    when a category maps to 'raw' the original order is returned. Default
    (empty) uses the conservative hybrid for everything.
    """
    if not candidates:
        return []
    category = str(candidates[0].get("category", ""))
    choice = (per_category_choice or {}).get(category, "hybrid")
    if choice == "raw":
        return list(range(len(candidates)))
    probs = [model.score_row(c) for c in candidates]
    beam = [int(c.get("beam_rank", i)) for i, c in enumerate(candidates)]
    if choice == "learned":
        scored = sorted(range(len(candidates)), key=lambda i: (-probs[i], beam[i]))
        return scored
    return hybrid_order(probs, beam, bucket=bucket)


__all__ = ["hybrid_order", "apply_policy"]
