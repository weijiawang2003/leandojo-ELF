# v23 reranker data audit (Part 1)

Pooled candidate-outcome dataset for the refreshed reranker. Each candidate's `verified` label is lean-cli-deterministic at the theorem level (consistent across generators). **No state_after, no manual oracle.** Leakage is controlled at eval time by **leave-one-theorem-out** (rows carry `theorem_name`).

- total rows: **6011** (78 theorems, 2927 unique theorem×candidate)
- positives / negatives: **944 / 5067** (positive fraction 0.157 — class imbalance handled by class-weighting, not resampling)

## Positives by category (all sources)

| category | rows | verified |
|---|---:|---:|
| bool | 261 | 62 |
| conjunction | 536 | 127 |
| disjunction | 435 | 58 |
| equality_rewrite | 824 | 138 |
| exists | 655 | 77 |
| forall | 679 | 56 |
| implication | 518 | 145 |
| list | 443 | 64 |
| nat_succ | 445 | 55 |
| negation | 1215 | 162 |

## Rows by source model

| source_model | rows | verified |
|---|---:|---:|
| v15_v12_literal_adapt | 293 | 19 |
| v15_v12_literal_adapt_rerank | 293 | 22 |
| v15_v12_raw | 300 | 22 |
| v15_v12_rerank | 300 | 22 |
| v15_v14_literal_adapt_rerank | 293 | 29 |
| v15_v14_raw | 300 | 27 |
| v18_broad_only | 471 | 62 |
| v20_broad_plus | 474 | 94 |
| v21_capacity | 465 | 85 |
| v21_routed | 473 | 102 |
| v21_single_retrain | 470 | 80 |
| v22_balanced | 472 | 100 |
| v22_balanced_large | 465 | 76 |
| v22_large | 472 | 103 |
| v22_plus_exists | 470 | 101 |

## v22 plus_exists broad-core positives by category (the v23 target distribution)

| category | rows | verified |
|---|---:|---:|
| bool | 29 | 10 |
| conjunction | 60 | 15 |
| disjunction | 48 | 7 |
| equality_rewrite | 59 | 12 |
| exists | 40 | 8 |
| forall | 29 | 6 |
| implication | 56 | 19 |
| list | 50 | 7 |
| nat_succ | 49 | 7 |
| negation | 50 | 10 |

## Error-class distribution

- `type_mismatch`: 1432
- `unknown_identifier`: 1297
- `parse_error`: 1195
- `ok`: 944
- `other`: 757
- `timeout`: 206
- `unknown_tactic`: 105
- `unsolved_goals`: 75

**Leakage control:** leave-one-theorem-out at eval time; each row carries theorem_name so the held theorem's rows are excluded when scoring it.
