# Mini-ELF v26 — Part 4: Specialist Train/Eval Splits

`scripts/build_v26_mathlib_specialist_dataset.py` →
`data/processed/v26_mathlib_specialist_splits/`.

## Specialist pool

| source | rows | note |
|---|---|---|
| v26 verified | 237 | this version's corpus |
| v25 verified (TRAIN theorems only) | 68 | reused; v25 *test* rows excluded |
| **pool (deduped by name+tactic)** | **305** | over **101 theorems** |

Pool theorems by category: nat 28, set 20, logic 22, bool_option 12, list 16,
function 5 (plus the v25-train carry-overs folded in by category).

The **v25 held-out test theorems (14)** are excluded from the pool entirely and
preserved as `v25_heldout_benchmark/test_seeds.jsonl` for the v24/v25/v26
comparison.

## Splits

### `theorem_holdout/` — the main specialist split

Stratified by theorem within each category (every 5th → test, next → val, rest
→ train), so each category contributes to all three splits.

| file | rows |
|---|---|
| `train_rows.jsonl` | 149 |
| `val_rows.jsonl` | 61 |
| `test_rows.jsonl` | 67 (**22 test theorems**) |
| `train_rows_plus_core.jsonl` | 207 (= 149 train + **58** curated v18 core) |

Test theorems by category: nat 20, set 13, logic 13, bool_option 10, list 9,
function 2 (rows). The `plus_core` set adds a **small** v18 broad-core subset
(implication/conjunction/disjunction/negation/equality/nat_succ/list — 58 rows,
`mathlib=False`) — **not** the 3,138-row v24 corpus — to give the specialist
shared logic/list/nat tactic shapes.

### `category_holdout_set/` — Q3: is Set reachable from transfer alone?

All 20 Set theorems held out as test (65 rows); train = 240 non-Set rows.

### `category_holdout_order/` — order/≤ transfer

All 11 order theorems held out as test (37 rows); train = 261 rows.

### `v25_heldout_benchmark/` — preserved

The 14 v25 held-out test theorems, unchanged.

## Leakage guards (independently re-verified)

| guard | result |
|---|---|
| theorem_name in train ∩ test (theorem_holdout) | ∅ |
| theorem_name in train ∩ val | ∅ |
| (stmt, state, tactic) triple train ∩ test | 0 |
| (stmt, state, tactic) triple train ∩ val | 0 |
| v25 held-out test theorems leaked into any train | ∅ |
| Set rows in `category_holdout_set` train | 0 |
| order rows in `category_holdout_order` train | 0 |
| 28 train rows dropped for triple-collision with eval | recorded |
| `state_after` anywhere | never present |

The 28 dropped train rows are statement collisions where a v26 theorem and a
v25-train theorem share an identical `(statement, state, tactic)` triple but
different names; the train copy is removed so no eval triple is ever seen in
training.

## Honesty

Only Lean-verified rows enter any split. Manual candidates are verified targets,
never model predictions. No `state_after`. Mathlib is real and external.
