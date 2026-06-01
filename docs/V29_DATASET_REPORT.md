# V29 — Part 5: Dataset Report

_`scripts/build_v29_mathlib_dataset.py` → `data/processed/v29_mathlib_specialist/`.
Combines the v28 pools with the v29 sibling-density corpus; no Lean run._

## Pools

| pool | rows |
|---|---:|
| v28_general pool (v27 widened + v28) | 554 |
| v28_best pool (v28 finset_specialist) | 606 |
| v28 shared val | 137 |
| **v29 density rows** | **492** |

107/187 v29 theorems are statement-novel vs the v28 pool (the rest are non-novel
re-statements that go to train).

## Training configs

| config | rows | role |
|---|---:|---|
| **`v29_general`** | **839** | v28_general + v29 (unweighted) — **recommended** (serves A/C/density_general) |
| `v29_v28best_plus` | 891 | v28_best pool + v29 (B) |
| `v29_set_finset_order_heavy` | 1330 | set+finset+order upsampled 2× (D) |
| `v29_category_balanced` | 674 | category-capped — **NEGATIVE CONTROL only** (E); cap 142/cat |
| `v29_function_order` | 1005 | function+order upsampled 2× (optional specialist) |
| shared val | 177 | checkpoint selection |

Per the v27/v28 finding that balancing is harmful, `v29_category_balanced` is built
**only as a labelled negative control** and is never adopted.

## Splits — the density law made causal

| split | test theorems | mean training family density | purpose |
|---|---:|---:|---|
| `theorem_holdout` | 20 | (mixed) | fresh v29 benchmark (stratified novel) |
| **`family_density_holdout`** | **34** | **6.53** | siblings held out from **dense** families |
| **`low_density_holdout`** | **13** | **0.92** | siblings held out from **sparse** families |
| `category_holdout_set` | 48 | 0 (in-category) | whole-category transfer probe |
| `category_holdout_finset` | 44 | 0 | whole-category transfer probe |
| `category_holdout_order` | 36 | 0 | whole-category transfer probe |

The crux: **the same `v29_general` model** is evaluated on `family_density_holdout`
(its families had ~6.5 training siblings) and `low_density_holdout` (~0.9). Same
architecture, same eval pipeline — the *only* difference is training density. The gap
between them (Part 9) is the density law measured causally, not just observed. The
dense holdout families include `set::subset_union` (11 train siblings),
`order::min_max` (9), `set::mem_inter_proj` (8), `order::le_of_eq` (8); the sparse
ones include `function::comp_app` (0), `nat::add_assoc` (0), `logic::and_symm` (0),
`finset::union_subset` (1).

The four v25/v26/v27/v28 benchmarks are preserved unchanged (pointers only).

## Leakage guards (all asserted, passed)

- no theorem-name overlap between any train config and any v29 split test;
- no `(statement, state)` overlap train↔(v29 splits ∪ v25/v26/v27/v28 benchmarks);
- no `(statement, state, tactic)` triple overlap train↔test;
- no `state_after` anywhere; manual targets never used as predictions; v24 untouched.
