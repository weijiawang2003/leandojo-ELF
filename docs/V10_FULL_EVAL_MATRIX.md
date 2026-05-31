# Mini-ELF v10 — full eval matrix (status snapshot)

> **⚠️ Leakage note.** The `redundancy_cell_holdout` and `redundancy_operation_holdout` blocks below cite the **legacy** `combined_v10` (trained on the v10 interpolation split, which leaks 36/40 test theorems into train). They are kept as in-distribution diagnostics, NOT as holdout/generalisation results. The corrected operation_holdout block (per-op LOFO) appears at the bottom. The leakage is pinned by `tests/test_v10_no_leakage.py`.

Cells marked `—` are not yet measured. Missing cells are explicitly *not* `0.000`. Re-running `scripts/build_v10_full_matrix.py` rebuilds this document. Legacy metrics from `data/baselines/v10_eval/<regime>/<fold>/<model>/metrics.json`; clean per-op metrics from `data/baselines/v10_eval_clean/per_op/<op>/<model>/metrics.json`.

## ✅ Clean operation_holdout (per-op LOFO)

> **This is the corrected (leakage-free) operation_holdout matrix.** Each `combined_v10_per_op/<op>` model was trained from scratch with the held op's v10 cells excluded from train; `baseline_v8` is the zero-shot comparison (never saw any v10 cell). See `tests/test_v10_no_leakage.py` for the invariants.

| held operation | model | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `conjunction_projection` | `baseline_v8` | 5 | 0.600 | 1.000 | 1.000 | 10 | 1 | 10 | 10 |
| `conjunction_projection` | `combined_v10_per_op` | 5 | 0.600 | 1.000 | 1.000 | 12 | 1 | 12 | 12 |
| `contradiction` | `baseline_v8` | 5 | 0.200 | 0.800 | 0.800 | 7 | 1 | 7 | 0 |
| `contradiction` | `combined_v10_per_op` | 5 | 0.400 | 0.600 | 0.800 | 6 | 0 | 6 | 0 |
| `disjunction_cases` | `baseline_v8` | 5 | 0.200 | 0.400 | 0.600 | 4 | 0 | 4 | 4 |
| `disjunction_cases` | `combined_v10_per_op` | 5 | 0.200 | 0.400 | 0.400 | 3 | 0 | 3 | 3 |
| `exists_elim` | `baseline_v8` | 5 | 1.000 | 1.000 | 1.000 | 16 | 2 | 16 | 16 |
| `exists_elim` | `combined_v10_per_op` | 5 | 1.000 | 1.000 | 1.000 | 18 | 0 | 18 | 18 |
| `implication_chain` | `baseline_v8` | 5 | 0.200 | 0.200 | 0.200 | 2 | 0 | 2 | 2 |
| `implication_chain` | `combined_v10_per_op` | 5 | 0.200 | 0.400 | 0.400 | 3 | 1 | 3 | 3 |
| `instantiate_forall` | `baseline_v8` | 5 | 0.200 | 0.400 | 0.800 | 6 | 2 | 6 | 0 |
| `instantiate_forall` | `combined_v10_per_op` | 5 | 0.600 | 0.600 | 0.800 | 6 | 0 | 6 | 0 |
| `intro_negation` | `baseline_v8` | 5 | 0.400 | 0.400 | 0.400 | 4 | 0 | 4 | 0 |
| `intro_negation` | `combined_v10_per_op` | 5 | 0.400 | 0.400 | 0.400 | 4 | 0 | 4 | 0 |
| `rewrite_eq` | `baseline_v8` | 5 | 0.400 | 0.400 | 0.400 | 2 | 0 | 2 | 2 |
| `rewrite_eq` | `combined_v10_per_op` | 5 | 0.400 | 0.400 | 0.400 | 3 | 0 | 3 | 3 |

**status:** 16/16 cells measured.

## ❌ redundancy_cell_holdout × model (LEAKED — in-distribution diagnostics)

| fold | model | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `conjunction_projection__left_ab` | `baseline_v8` | 1 | 1.000 | 1.000 | 1.000 | 3 | 2 | 3 | 0 |
| `conjunction_projection__left_ab` | `redundancy_only` | 1 | 1.000 | 1.000 | 1.000 | 1 | 0 | 1 | 0 |
| `conjunction_projection__left_ab` | `combined_v10` | 1 | 1.000 | 1.000 | 1.000 | 2 | 1 | 2 | 0 |
| `contradiction__arrow_false` | `baseline_v8` | 1 | 0.000 | 1.000 | 1.000 | 1 | 1 | 1 | 0 |
| `contradiction__arrow_false` | `redundancy_only` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `contradiction__arrow_false` | `combined_v10` | 1 | 0.000 | 1.000 | 1.000 | 1 | 1 | 1 | 0 |
| `contradiction__exfalso_pq` | `baseline_v8` | 1 | 1.000 | 1.000 | 1.000 | 4 | 4 | 4 | 0 |
| `contradiction__exfalso_pq` | `redundancy_only` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `contradiction__exfalso_pq` | `combined_v10` | 1 | 1.000 | 1.000 | 1.000 | 3 | 3 | 3 | 0 |
| `contradiction__exfalso_with_extra` | `baseline_v8` | 1 | 1.000 | 1.000 | 1.000 | 2 | 1 | 2 | 0 |
| `contradiction__exfalso_with_extra` | `redundancy_only` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `contradiction__exfalso_with_extra` | `combined_v10` | 1 | 1.000 | 1.000 | 1.000 | 2 | 1 | 2 | 0 |
| `disjunction_cases__or_self` | `baseline_v8` | 1 | 1.000 | 1.000 | 1.000 | 1 | 1 | 1 | 0 |
| `disjunction_cases__or_self` | `redundancy_only` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `disjunction_cases__or_self` | `combined_v10` | 1 | 0.000 | 1.000 | 1.000 | 1 | 1 | 1 | 0 |
| `disjunction_cases__or_with_false` | `baseline_v8` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `disjunction_cases__or_with_false` | `redundancy_only` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `disjunction_cases__or_with_false` | `combined_v10` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `exists_elim__reuse_witness_3` | `baseline_v8` | 1 | 0.000 | 1.000 | 1.000 | 3 | 3 | 3 | 0 |
| `exists_elim__reuse_witness_3` | `redundancy_only` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `exists_elim__reuse_witness_3` | `combined_v10` | 1 | 0.000 | 1.000 | 1.000 | 2 | 2 | 2 | 0 |
| `exists_elim__reuse_witness_5` | `baseline_v8` | 1 | 1.000 | 1.000 | 1.000 | 3 | 3 | 3 | 0 |
| `exists_elim__reuse_witness_5` | `redundancy_only` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `exists_elim__reuse_witness_5` | `combined_v10` | 1 | 1.000 | 1.000 | 1.000 | 4 | 4 | 4 | 0 |
| `implication_chain__two_step_abc` | `baseline_v8` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `implication_chain__two_step_abc` | `redundancy_only` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `implication_chain__two_step_abc` | `combined_v10` | 1 | 1.000 | 1.000 | 1.000 | 1 | 1 | 1 | 0 |
| `implication_chain__two_step_pqr` | `baseline_v8` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `implication_chain__two_step_pqr` | `redundancy_only` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `implication_chain__two_step_pqr` | `combined_v10` | 1 | 0.000 | 0.000 | 1.000 | 1 | 1 | 1 | 0 |
| `instantiate_forall__nat_add_zero_4` | `baseline_v8` | 1 | 0.000 | 0.000 | 1.000 | 1 | 1 | 1 | 0 |
| `instantiate_forall__nat_add_zero_4` | `redundancy_only` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `instantiate_forall__nat_add_zero_4` | `combined_v10` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `instantiate_forall__nat_eq_3` | `baseline_v8` | 1 | 0.000 | 0.000 | 1.000 | 1 | 1 | 1 | 0 |
| `instantiate_forall__nat_eq_3` | `redundancy_only` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `instantiate_forall__nat_eq_3` | `combined_v10` | 1 | 1.000 | 1.000 | 1.000 | 1 | 1 | 1 | 0 |
| `instantiate_forall__prop_self_imp` | `baseline_v8` | 1 | 0.000 | 1.000 | 1.000 | 3 | 3 | 3 | 0 |
| `instantiate_forall__prop_self_imp` | `redundancy_only` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `instantiate_forall__prop_self_imp` | `combined_v10` | 1 | 1.000 | 1.000 | 1.000 | 3 | 3 | 3 | 0 |
| `intro_negation__contrapos_ab` | `baseline_v8` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `intro_negation__contrapos_ab` | `redundancy_only` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `intro_negation__contrapos_ab` | `combined_v10` | 1 | 1.000 | 1.000 | 1.000 | 1 | 1 | 1 | 0 |
| `rewrite_eq__mul_one` | `baseline_v8` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `rewrite_eq__mul_one` | `redundancy_only` | 1 | 0.000 | 1.000 | 1.000 | 1 | 0 | 1 | 0 |
| `rewrite_eq__mul_one` | `combined_v10` | 1 | 1.000 | 1.000 | 1.000 | 1 | 0 | 1 | 0 |
| `rewrite_eq__swap_under_z` | `baseline_v8` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `rewrite_eq__swap_under_z` | `redundancy_only` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `rewrite_eq__swap_under_z` | `combined_v10` | 1 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |

**status:** 48/48 cells measured.

## ❌ redundancy_operation_holdout × model (LEAKED — in-distribution diagnostics)

| fold | model | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `conjunction_projection` | `baseline_v8` | 5 | 1.000 | 1.000 | 1.000 | 13 | 13 | 13 | 13 |
| `conjunction_projection` | `redundancy_only` | 5 | 0.400 | 0.400 | 0.600 | 3 | 3 | 3 | 3 |
| `conjunction_projection` | `combined_v10` | 5 | 1.000 | 1.000 | 1.000 | 13 | 13 | 13 | 13 |
| `contradiction` | `baseline_v8` | 3 | 0.333 | 0.667 | 0.667 | 5 | 5 | 5 | 5 |
| `contradiction` | `redundancy_only` | 3 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `contradiction` | `combined_v10` | 3 | 0.333 | 0.667 | 0.667 | 4 | 4 | 4 | 4 |
| `disjunction_cases` | `baseline_v8` | 4 | 0.250 | 0.250 | 0.500 | 3 | 3 | 3 | 3 |
| `disjunction_cases` | `redundancy_only` | 4 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `disjunction_cases` | `combined_v10` | 4 | 0.500 | 1.000 | 1.000 | 5 | 5 | 5 | 5 |
| `exists_elim` | `baseline_v8` | 4 | 0.750 | 1.000 | 1.000 | 12 | 12 | 12 | 12 |
| `exists_elim` | `redundancy_only` | 4 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `exists_elim` | `combined_v10` | 4 | 0.750 | 1.000 | 1.000 | 14 | 14 | 14 | 14 |
| `implication_chain` | `baseline_v8` | 4 | 0.250 | 0.250 | 0.250 | 2 | 2 | 2 | 2 |
| `implication_chain` | `redundancy_only` | 4 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `implication_chain` | `combined_v10` | 4 | 0.750 | 1.000 | 1.000 | 7 | 7 | 7 | 7 |
| `instantiate_forall` | `baseline_v8` | 3 | 0.333 | 0.333 | 0.667 | 2 | 2 | 2 | 2 |
| `instantiate_forall` | `redundancy_only` | 3 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `instantiate_forall` | `combined_v10` | 3 | 1.000 | 1.000 | 1.000 | 3 | 3 | 3 | 3 |
| `intro_negation` | `baseline_v8` | 5 | 0.400 | 0.400 | 0.400 | 4 | 4 | 4 | 4 |
| `intro_negation` | `redundancy_only` | 5 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `intro_negation` | `combined_v10` | 5 | 0.800 | 1.000 | 1.000 | 10 | 10 | 10 | 10 |
| `rewrite_eq` | `baseline_v8` | 4 | 0.500 | 0.500 | 0.500 | 2 | 2 | 2 | 2 |
| `rewrite_eq` | `redundancy_only` | 4 | 0.000 | 0.750 | 0.750 | 3 | 3 | 3 | 3 |
| `rewrite_eq` | `combined_v10` | 4 | 0.750 | 0.750 | 0.750 | 4 | 4 | 4 | 4 |

**status:** 24/24 cells measured.

## redundancy_family_holdout × model

_no folds measured yet_

## redundancy_low_shot × model

_no folds measured yet_

## v8 negative-control cells × model

| fold | model | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `family_holdout_forall_inst` | `baseline_v8` | 7 | 1.000 | 1.000 | 1.000 | 7 | 7 | 7 | 7 |
| `family_holdout_forall_inst` | `redundancy_only` | 7 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `family_holdout_forall_inst` | `combined_v10` | 7 | 0.857 | 0.857 | 0.857 | 6 | 6 | 6 | 6 |
| `family_holdout_rewrite_succ` | `baseline_v8` | 5 | 0.600 | 1.000 | 1.000 | 14 | 14 | 14 | 14 |
| `family_holdout_rewrite_succ` | `redundancy_only` | 5 | 0.000 | 0.200 | 0.600 | 3 | 3 | 3 | 3 |
| `family_holdout_rewrite_succ` | `combined_v10` | 5 | 0.800 | 1.000 | 1.000 | 12 | 12 | 12 | 12 |

**status:** 6/6 cells measured.

## donorless_eval × model

| model | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `baseline_v8` | — | — | — | — | — | — | — | — |
| `redundancy_only` | — | — | — | — | — | — | — | — |
| `combined_v10` | — | — | — | — | — | — | — | — |

**status:** 0/3 cells measured.
