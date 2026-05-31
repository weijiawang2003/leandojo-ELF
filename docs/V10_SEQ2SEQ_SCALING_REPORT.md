# Mini-ELF v10 — seq2seq scaling report

> **Scope.** v10 measures the **data-scaling** ceiling of the v8 seq2seq when
> the training corpus is enriched with operation×surface-family redundancy.
> The architecture, training loop, and beam decoder are identical to v8.
> `state_after_is_real = false` for every train and test row. No Mathlib.
> No manual oracle is counted as a model output.

## ⚠️ Methodology correction (read this first)

An earlier draft of this report cited combined_v10 numbers on the
`redundancy_cell_holdout` and `redundancy_operation_holdout` regimes that
**were not actually held-out** for that model. The `combined_v10` checkpoint
in `data/models/proof_block_seq2seq_combined_v10/` was trained on the
*interpolation* split of the v10 corpus (`proof_blocks_combined_v10_redundancy_interpolation/train.jsonl`,
581 rows). That split contains **36 of the 40 v10 cells**, including the
exact test theorems used by the `cell_holdout` and `operation_holdout`
folds. The legacy numbers in the prior draft were therefore measuring
in-distribution memorisation, not generalisation.

The bug is pinned by `tests/test_v10_no_leakage.py` (4 assertions). The
`test_legacy_combined_v10_interpolation_overlaps_holdout_test_documented`
case asserts the *known* 36-of-40 overlap so a silent fix later cannot
mask the bug.

### What is preserved

* **`baseline_v8`** (`proof_block_seq2seq_interpolation`) was trained on
  the pure v8 base pool (no v10 cell ever). Its v10 holdout numbers are
  legitimate *zero-shot* baselines and survive the correction.

### What is invalidated

* All `combined_v10` (legacy, interpolation-trained)
  `redundancy_cell_holdout`, `redundancy_operation_holdout`, and v8
  negative-control `pass@k` cited in the prior draft. They are still on
  disk at `data/baselines/v10_eval/`, but **must be relabelled as
  in-distribution diagnostics, not holdout/generalisation results**.
* `redundancy_only` (trained on the 23/28-row interpolation train pool
  of the v10 corpus alone) shares the same leakage pattern. Its op-holdout
  numbers were uniformly 0 anyway (insufficient training data), so the
  practical impact is small — but the diagnostic must be relabelled too.

### What replaces them

Per-operation LOFO models trained from scratch:
`scripts/build_combined_v10_per_op.py` materialises 8 regime dirs at
`data/processed/proof_blocks_combined_v10_per_op/<operation>/{train,test}.jsonl`,
where train = v8 base pool + v10 cells with **the held operation's cells
removed**, test = the held operation's 5 v10 cells. The inline assertions
verify (a) theorem-name disjointness train ⟂ test and (b) no v10 row in
train carries the held operation. `tests/test_v10_no_leakage.py` ratifies
both invariants statically.

`scripts/train_combined_v10_per_op.sh` then trains 8 models (one per fold)
at `data/models/proof_block_seq2seq_combined_v10_per_op/<operation>/`.
`scripts/eval_combined_v10_per_op.sh` runs lean-cli verification on each
per-op model on its matching test set and writes
`data/baselines/v10_eval_clean/per_op/<operation>/combined_v10_per_op/metrics.json`.

The cell_holdout regime (per-(operation, surface_family) LOFO) would
require **40 separate per-cell models**. That's out of scope tonight —
deferred to v11 — and the cell_holdout metrics under the legacy
combined_v10 are explicitly marked invalid in
`docs/RESULTS_SUMMARY.md` and `docs/V10_FULL_EVAL_MATRIX.md`.

## Research question (unchanged)

> *If we create multiple surface families sharing the same proof operation,
> can the seq2seq generalise to held-out families/operations more reliably?*

## Models compared (corrected)

| tag | training pool | size | val (interpolation, 79–81 ex) greedy top-1 | beam@10 contains gold |
| --- | --- | ---: | ---: | ---: |
| `baseline_v8` | v8 base only (basic + hard + planner-blind), interpolation | 553 | 0.288 | 0.808 |
| `combined_v10_per_op/<op>` × 8 | v8 base + v10 cells of the *other* 7 operations | 588 each | 0.30–0.37 | 0.79–0.83 |

(`redundancy_only` and the legacy `combined_v10` checkpoints exist on
disk but are not part of the corrected matrix.)

## Clean per-op matrix (operation_holdout pass@5, lean-cli verified, 16/16 cells)

> The result the v10 brief was after, measured under proper LOFO methodology.

| held operation | baseline_v8 (zero-shot) | **combined_v10_per_op** | delta | direction |
|---|---:|---:|---:|---|
| `conjunction_projection` (n=5) | 1.000 | 1.000 | 0 | tie |
| `contradiction` (n=5) | **0.800** | 0.600 | -0.200 | baseline wins |
| `disjunction_cases` (n=5) | 0.400 | 0.400 | 0 | tie |
| `exists_elim` (n=5) | 1.000 | 1.000 | 0 | tie |
| `implication_chain` (n=5) | 0.200 | **0.400** | +0.200 | v10 wins |
| `instantiate_forall` (n=5) | 0.400 | **0.600** | +0.200 | v10 wins |
| `intro_negation` (n=5) | 0.400 | 0.400 | 0 | tie |
| `rewrite_eq` (n=5) | 0.400 | 0.400 | 0 | tie |

**Aggregate**: combined_v10_per_op mean pass@5 = **0.600**; baseline_v8 mean
pass@5 = **0.575**. **Net +0.025**, with 2 wins / 1 loss / 5 ties. Total
verified candidates: 55 vs 51 (+4). Total `cross_operation_verified`:
**39 vs 34 (+5)** — every one a Lean-typechecked novel cross-operation
tactic the model had no in-training-pool example of.

### What this means

Under correct per-op LOFO methodology, **the v10 redundancy corpus
provides a small, mixed positive contribution** to operation_holdout
generalisation:

- **Wins on 2 of 8 operations** (`implication_chain`,
  `instantiate_forall`) where baseline_v8's v8 base pool lacked
  shape-compatible siblings and the v10 redundancy filled the gap.
- **Loses on 1 operation** (`contradiction`) — the v8 base pool already
  carried abundant `neg_exfalso` / `neg_or_cases` examples; adding more
  same-shape v10 cells appears to have caused a minor capacity-
  reallocation regression.
- **Ties on 5 operations** — either both models verify everything
  (`conjunction_projection`, `exists_elim` at 1.000) or both stay on
  the same plateau (`disjunction_cases`, `intro_negation`, `rewrite_eq`
  at 0.400).

The dramatic 5/8 wins reported in the prior leaked draft are **not
reproduced** under clean LOFO. The honest signal is: the v10 data is
*occasionally* useful when the v8 base pool happens not to cover an
operation's tactic shape; it does not deliver a consistent across-the-
board lift.

`cell_holdout` results (40 per-cell LOFO models, ~3 hours of training)
are deferred to v11.

The legacy in-distribution combined_v10 numbers from the prior draft
live at `data/baselines/v10_eval/` and are visible in the bottom of
`V10_FULL_EVAL_MATRIX.md` under their `LEAKED` labels for forensic
reference.

## Honest framing

* The seq2seq is the v8 model. v10 is **data scaling**, not a new
  architecture. The brief explicitly forbids changing the model first.
* No hand-written templates are folded into a model output. v3-era
  symbolic planner blocks are *not* part of any v10 model proposal.
* The v10 redundancy corpus is synthetic. *Verifying* on a held-out
  redundancy cell shows the model recombined tokens correctly; it is not
  evidence of "concept learning" of the operation.
* No `state_after`. No `obtain`/`rcases` (Mathlib). No `aesop`/`omega`.
  No `sorry`/`admit`/`unsafe`.

## What this report does **not** claim

* It does **not** claim full theorem proving.
* It does **not** claim multi-step ELF proof-state modelling — the
  embedded latent / flow stack is unchanged from v0/v1/v8.
* It does **not** count oracle / manual candidate strings as model
  outputs. Manual candidates exist in `data/manual/redundancy_candidates.jsonl`
  but are used only as the *pre-commit verification target* for the corpus
  builder, never as a decoder output.
* It does **not** claim a `cell_holdout` improvement under the v10
  hypothesis — the cell_holdout numbers from the prior draft are
  *invalid* due to leakage and have not yet been replaced by a clean
  per-cell LOFO matrix.
