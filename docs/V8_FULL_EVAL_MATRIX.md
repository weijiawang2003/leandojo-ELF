# Mini-ELF v8 — full eval matrix (status snapshot)

Per-cell `lean-cli` `pass@k` for the v8 seq2seq proposer, plus any v8
fusion cells that ran to completion. Cells marked `—` are **not yet
measured** — the eval loop in
`scripts/run_v8_seq2seq_eval_loop.sh` is timeout-guarded (15 min/fold)
and the lean-cli verifier slows substantially on tactics outside the
verification cache. Missing cells are explicitly *not* `0.000`; the
v8 brief forbids faking metrics.

All numbers below come from `data/baselines/v8_seq2seq_*/metrics.json`
(produced by `scripts/evaluate_proof_block_seq2seq.py`) and
`data/baselines/v8_eval/<regime>/<config>/metrics.json` (produced by
`scripts/evaluate_mini_elf_v8.py`). Run `scripts/build_v8_full_matrix.py`
to regenerate this document.

## family_holdout × seq2seq_only

LOFO: held PB family is absent from train; the *9 other* PB families
remain. Train pool ≈ 658–683 verified rows per fold.

| regime | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `family_holdout/neg_exfalso` | 8 | 0.125 | 0.625 | 0.625 | 9 | 9 | 9 | 0 |
| `family_holdout/neg_imp_exfalso` | 5 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `family_holdout/neg_double_intro` | 5 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `family_holdout/neg_contrapositive` | 6 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `family_holdout/neg_or_cases` | 6 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `family_holdout/exists_elim_conj` | 8 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `family_holdout/exists_elim_prop` | 6 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `family_holdout/exists_reconstruct` | 5 | 0.200 | 0.400 | 0.400 | 2 | 0 | 2 | 0 |
| `family_holdout/forall_inst` | 7 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `family_holdout/rewrite_succ` | 5 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |

**status**: 10/10 folds measured.

## operation_holdout × seq2seq_only

LOOO: held operation (and every theorem with that operation) is absent
from train. `unknown` is reserved for the operation the heuristic can't
classify (mostly `exists_reconstruct`); it is excluded from the trained
set on principle.

| regime | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `operation_holdout/contradiction` | 14 | 0.000 | 0.000 | 0.071 | 1 | 1 | 1 | 1 |
| `operation_holdout/destruct_exists` | 14 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `operation_holdout/instantiate_forall` | 7 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| `operation_holdout/intro_negation` | 16 | 0.000 | 0.125 | 0.188 | 3 | 3 | 3 | 3 |
| `operation_holdout/project_conjunction` | — | — | — | — | — | — | — | — |
| `operation_holdout/rewrite` | 5 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |

**status**: 5/6 folds measured.

## donorless_eval (no planner-blind family in train)

| regime / config | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `donorless_eval (v8_seq2seq direct)` | — | — | — | — | — | — | — | — |
| `donorless_eval / seq2seq_only (fusion eval)` | 61 | 0.000 | 0.033 | 0.033 | 3 | 0 | 3 | 0 |
| `donorless_eval / retrieval_only (fusion eval)` | — | — | — | — | — | — | — | — |
| `donorless_eval / retrieval_seq2seq (fusion eval)` | — | — | — | — | — | — | — | — |
| `donorless_eval / full_fusion (fusion eval)` | — | — | — | — | — | — | — | — |

## current / kshot / literal_holdout (gradient cells)

These are the v7 donor-scarcity splits, re-measured under v8 configs
when the eval loop completes them.

| regime / config | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `current / seq2seq_only` | — | — | — | — | — | — | — | — |
| `current / retrieval_only` | — | — | — | — | — | — | — | — |
| `current / retrieval_seq2seq` | — | — | — | — | — | — | — | — |
| `kshot_0 / seq2seq_only` | — | — | — | — | — | — | — | — |
| `kshot_0 / retrieval_only` | — | — | — | — | — | — | — | — |
| `kshot_0 / retrieval_seq2seq` | — | — | — | — | — | — | — | — |
| `kshot_1 / seq2seq_only` | — | — | — | — | — | — | — | — |
| `kshot_1 / retrieval_only` | — | — | — | — | — | — | — | — |
| `kshot_1 / retrieval_seq2seq` | — | — | — | — | — | — | — | — |
| `kshot_2 / seq2seq_only` | — | — | — | — | — | — | — | — |
| `kshot_2 / retrieval_only` | — | — | — | — | — | — | — | — |
| `kshot_2 / retrieval_seq2seq` | — | — | — | — | — | — | — | — |
| `literal_holdout / seq2seq_only` | — | — | — | — | — | — | — | — |
| `literal_holdout / retrieval_only` | — | — | — | — | — | — | — | — |
| `literal_holdout / retrieval_seq2seq` | — | — | — | — | — | — | — | — |

## Summary

Measured cells with a non-zero pass@5 (any v8 config):

| cell | pass@5 | novel | xfam |
|---|---:|---:|---:|
| `family_holdout/neg_exfalso` | 0.625 | 9 | 9 |
| `family_holdout/exists_reconstruct` | 0.400 | 0 | 2 |
| `operation_holdout/intro_negation` | 0.125 | 3 | 3 |
| `donorless_eval` | 0.033 | 0 | 3 |

Missing-cell semantics: a cell is missing because either
`scripts/run_v8_seq2seq_eval_loop.sh` has not yet reached it, or the
per-fold 15-minute timeout fired before the verifier completed all
candidates. The output is identical in either case — there is no
metrics.json on disk. **Re-running `build_v8_full_matrix.py`** rebuilds
this table from whatever cells are present at that moment.
