# V30 — Part 5: Dataset Report

_`scripts/build_v30_mathlib_dataset.py` → `data/processed/v30_mathlib_specialist/`._

## Pools

| pool | rows |
|---|---:|
| v29_general pool | 839 |
| v29_best pool (`set_finset_order_heavy`) | 1330 |
| **v30 targeted repair rows** | **155** |

## Configs

| config | rows | role |
|---|---:|---|
| **`v30_general_targeted`** | **905** | v29_general + v30 (unweighted) — **recommended** [A] |
| `v30_v29best_plus` | 1396 | v29_best + v30 [B] |
| `v30_targeted_only` | 66 | v30 rows only — **ablation** [C] |
| `v30_targeted_upsample` | 971 | general + v30 again (2× repair, NOT balanced) [D] |
| shared val | 207 | checkpoint selection |

**No category-balanced config is built** — v29 confirmed balancing is a negative
control.

## Splits

| split | test theorems | purpose |
|---|---:|---|
| `theorem_holdout` (fresh v30) | 15 | new benchmark (stratified novel) |
| `targeted_family_holdout` | 10 | density-repair probe (one sibling held out per family) |
| v25/v26/v27/v28/v29 + v29 family/low-density holdouts | (preserved) | the headline eval, incl. v25 recovery |

The targeted-family holdout's per-family training densities are now mostly **5–12**
(`set::mem_inter_proj` 12, `set::mem_union_intro` 12, `finset::mem_inter_proj` 8,
`order::le_refl` 7, `nat::add_assoc` 5) — i.e., the repaired families now sit in the
reliable ≥4 regime, so their held-out members test the density law directly. (Two
remain thin — `set::empty_subset` 3, `finset::empty_subset` 0 — kept honestly as
low-density contrast points.)

## Leakage guards (asserted, passed)

No name/statement/triple overlap train↔(v30 splits ∪ v25–v29 benchmarks); no
`state_after`; manual targets never used as predictions; v24 untouched.
