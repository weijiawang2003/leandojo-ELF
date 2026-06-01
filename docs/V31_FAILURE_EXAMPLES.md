# V31 — Part 9/10: Remaining Failures + Core Note

_`scripts/analyze_v31_remaining_failures.py` →
`data/baselines/v31_remaining_failures/report.json`. No Lean run._

## Remaining failures of the best v31 model (`v31_canonical_general`)

Over the standard + token-diversity holdouts: **1 residual** (down from v30's 13).

| theorem | family | class | expected | model's beam (wrong) |
|---|---|---|---|---|
| `v30_set_empty_inter_subset` | set::empty_subset | api_syntax | `intro x hx; cases hx.1` / `simp` | `Set.inter_subset_left`, `intro x h; exact` (truncated) |

Failure-class split: **api_syntax 1, token_coverage 0, vocabulary 0, multi_step 0,
architecture 0, proof_state 0.**

## Classification

The single remaining residual is **not** a token-coverage case — it is the
low-frequency *shape* `∅ ∩ s ⊆ t`, which closes by `cases hx.1` (`x ∈ ∅` is `False`)
or `simp`, not by the projection pattern the model reaches for. Canonicalization fixed
**every pure surface-token residual** (the `_3`/`_mgh` projection members); this one
remains because it is a sparse *shape*, i.e. a **density** gap (axis 1), not a
token-coverage gap (axis 2). It would be fixed by a couple of verified `∅ ∩ s ⊆ t`
siblings — the v29/v30 density recipe.

## Is LeanDojo next-state relevant now? **Still no.**

`leandojo_next_state_relevant: false`. **0 multi-step / proof-state residuals.** The
project has now driven the single-tactic Mathlib tier to **1 residual**, and it is a
sparse-shape (density) case, not a planning one. LeanDojo next-state supervision
remains premature; the cheaper move is one more density sibling for the `∅∩` shape.

## Optional v24 core-residual note — **audited, not retrained**

The protected v24 model is **never retrained**. The v31 finding generalises to the old
core residuals (`and_assoc_one`, `or_inr`, `or_elim_to_common`): they are the same
class of single-tactic, surface-sensitive misses. **Recommendation:** apply the v31
recipe to core — a small **rename-augmented / canonicalized core sibling corpus** + a
**core specialist** routed to, never an edit to the protected v24 model. Out of v31
scope (the routed system already preserves broad-core bit-for-bit by sending all core
theorems to v24).
