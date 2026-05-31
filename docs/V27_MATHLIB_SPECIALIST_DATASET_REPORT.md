# Mini-ELF v27 — Specialist Dataset Report (Part 5)

Source: `scripts/build_v27_mathlib_specialist_dataset.py` →
`data/processed/v27_mathlib_specialist/`. Combines the v26 specialist pool with
the 181 v27 expanded rows; produces four training configs, a fresh v27
theorem-holdout, and Set/order category-holdouts, while preserving the v25
held-out and v26 holdout benchmarks. Leakage guard is **statement-level**
(stricter than v26's triple-level).

## Pools

| Pool | rows |
|------|------|
| v26 base train | 149 |
| v26 widened train | ~196 (149 + Set-widen) |
| v26 val | 61 |
| v27 expanded (new) | 181 |

## v27 theorem-holdout (fresh, novel-only)

Test theorems are drawn ONLY from v27 theorems whose (statement, state) is **novel**
(absent from every v26 train/val row), stratified by category. Of 60 v27 theorems
with new rows, **16 are statement-novel** (44 reuse a canonical shape already in
v26 train and are routed to train). Stratified split of the 16 novel: train 5,
val 4, **test 7** (20 rows; Set-heavy: set 7, order 6, nat 3, logic 3, list 1 rows).
This guarantees the held-out test statements never appear in any training config.

## Training configs

| Config | rows | description |
|--------|------|-------------|
| v27_base | 296 | v26 base train + v27 expanded |
| v27_widened | 343 | v26 widened train + v27 expanded |
| v27_category_balanced | 275 | per-category cap over widened (median×1.5) |
| v27_set_heavy | 462 | widened with Set rows upsampled 2× |
| (shared) val | 68 | v26 val + v27 val |

## Category-holdout transfer probes

| Split | train rows (no target cat) | test theorems | test seeds |
|-------|----------------------------|---------------|-----------|
| category_holdout_set | 224 | 48 | 16 |
| category_holdout_order | 283 | 17 | 10 |

These hold out an *entire* category from training to probe pure cross-category
transfer (0 in-category training); evaluated with dedicated holdout-trained models
in Part 7.

## Preserved benchmarks (unchanged)

- v25 held-out tier-C (14 theorems) — pointer to `data/seeds/v25_mathlib_tierc_test_seeds.jsonl`
- v26 theorem-holdout (22 theorems) — pointer to the v26 splits dir

## Leakage guards (asserted in the builder, all PASSED)

- no v27 holdout-test statement (statement,state) in any train config;
- no v25/v26 benchmark statement in any train config;
- no holdout-test theorem name in train;
- no `state_after` anywhere.

Honesty: only Lean-verified rows; manual targets never used as predictions;
Mathlib real and external; v24 broad-core model untouched.
