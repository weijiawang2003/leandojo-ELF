# V29 — Part 10: Remaining Failures + v24 Cleanup Decision

_`scripts/analyze_v29_remaining_failures.py` →
`data/baselines/v29_remaining_failures/report.json`. No Lean run; expected proofs are
Lean-verified references, never predictions._

## Remaining failures of the best v29 model (`v29_general`)

Over the fresh + density holdouts (v28 + v29 theorem + family/low-density),
**8 residuals**:

| theorem | bench | family | class |
|---|---|---|---|
| `v28_fs_empty_subset` | v28 | finset::empty_subset | api_syntax |
| `v28_ord_le_refl_pre_1` | v28 | order::le_refl | lemma_vocabulary |
| `v29_fs_mem_inter_right_3` | family_density | finset::mem_inter_proj | api_syntax |
| `v29_fs_mem_union_right_3` | family_density | finset::mem_union_intro | lemma_vocabulary |
| `v29_set_mem_inter_left_3` | family_density | set::mem_inter_proj | lemma_vocabulary |
| `v29_set_mem_inter_right_3` | family_density | set::mem_inter_proj | lemma_vocabulary |
| `v29_set_mem_union_of_left_3` | family_density | set::mem_union_intro | lemma_vocabulary |
| `v29_set_mem_union_of_right_3` | family_density | set::mem_union_intro | lemma_vocabulary |

Failure-class split: **6 lemma_vocabulary, 2 api_syntax, 0 multi-step, 0
architecture, 0 proof-state.**

## Classification

- **Data/coverage (8/8).** Every residual is a **single-tactic** goal whose correct
  proof verifies; the small seq2seq simply misranks/mis-binds the identifier. The 6
  family-density misses are all the **`_3` surface-token variants** (`u,v` sets,
  element `w`, hyp `hw`) of the projection/membership families — density lifted these
  from ~0.25 (v28) / 0.16–0.26 (density-0 transfer) to ~0.70, but the last mile under
  unusual identifiers still slips. The 2 v28 misses are the **un-densified**
  `finset::empty_subset` and `order::le_refl` (v29 densified set/finset projection,
  not these). Fix in v30: a handful more siblings for the `_3` token forms and for
  `empty_subset`/`le_refl`.
- **No multi-step / proof-state / architecture failures.** Statement arrow counts are
  ≤ 1 throughout; nothing requires intermediate-state reasoning.

## Is LeanDojo next-state supervision now relevant? **Not yet.**

`leandojo_next_state_relevant: false` — 0 of 8 residuals are multi-step. The wall is
still **single-tactic coverage/binding**, exactly where more siblings help. Hold
LeanDojo next-state until single-tactic coverage saturates (residuals stop being
"more siblings would fix it").

## Optional v24 broad-core cleanup — **audited, not retrained**

The protected v24 broad-core model is **never retrained** (constraint). Audit of the
v24 broad-core eval found **3 old core residuals**, orthogonal to the Mathlib tier.
**Recommendation:** defer to a dedicated core-residual corpus pass; do not touch v24
inside v29 (broad-core preservation is the hard constraint, and the routed system
already meets the bar by sending all core theorems to the untouched v24 model).
