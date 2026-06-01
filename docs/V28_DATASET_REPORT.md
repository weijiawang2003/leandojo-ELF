# V28 Part 4 — Dataset Construction

_Script: `scripts/build_v28_mathlib_dataset.py`.
Output: `data/processed/v28_mathlib_specialist/`._

Combines the **v27 best specialist pool** (`v27_widened` = v26_widened + v27
expanded, 343 rows) with the **v28 expanded** verified rows (350) and produces four
training configs, a fresh 30-theorem v28 holdout, and Set/order/Finset category
holdouts — while preserving v25/v26/v27 benchmarks untouched.

## Pools

| pool | rows |
|------|-----:|
| v27 widened pool (v26_widened + v27 expanded) | 343 |
| v27 shared val | 68 |
| v28 expanded verified | 350 |

## Fresh v28 theorem-holdout (the new benchmark)

Test theorems are drawn ONLY from v28 theorems whose `(statement, state)` is **novel**
vs the v27 pool, stratified by category (every 4th → test). 116 novel v28 theorems,
25 non-novel (always → train).

| | value |
|---|---|
| **test theorems** | **30** (vs v27's 7 — a far more robust benchmark) |
| test rows | 70 |
| val theorems | 29 |
| train theorems | 57 |
| test rows by category | set 24, order 15, finset 13, nat 10, logic 4, list 2, function 2 |
| dropped (v28 train overlap / v27 pool overlap) | 0 / 0 |

The holdout spans **7 categories including the new Finset** — so the fresh-holdout
number measures generalization across the whole skill set, not just Set.

## Training configs

| config | rows | description |
|--------|-----:|-------------|
| `v28_general` | 554 | v27 widened pool + v28 train (the "v27_best + v28") |
| `v28_set_order_heavy` | 816 | general with Set+order rows upsampled 2× |
| `v28_category_balanced` | 442 | per-category cap (cap = 90) |
| `v28_finset_specialist` | 606 | general with Finset rows upsampled 3× |
| shared val | 137 | v27 val + v28 val (checkpoint selection only) |

## Category holdouts (transfer probes)

Each holds out **all** theorems of one category and trains on the rest, to measure
whether the skill transfers without seeing that exact category's held-out members.

| holdout | train rows | test theorems | test seeds |
|---------|-----------:|--------------:|-----------:|
| Set | 352 | 84 | 38 |
| order | 469 | 35 | 27 |
| **Finset (new)** | 528 | 18 | 18 |

## Leakage guards (all asserted in the builder, PASSED)

* **No theorem-name overlap** between any config train and its eval.
* **No `(statement, state)` overlap** between train and: the v28 holdout test, the
  v25 held-out, the v26 holdout, or the v27 holdout (statement-level guard).
* **No held-out benchmark rows** in any training config (v25/v26/v27 test seeds
  banned from every config).
* **No `state_after`** anywhere (asserted on every train/test row).

The v25/v26/v27 benchmarks are referenced by pointer and **never modified** — their
metrics are not retconned.

## Honesty

Only Lean-verified rows enter training. Manual targets are never used as predictions.
Mathlib is real and external. The v24 broad-core model is untouched.
