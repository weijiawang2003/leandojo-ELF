# v22 category-interference analysis (Part 6)

Read-only synthesis of the Part-5 evaluations and the Part-2 training-pool compositions. Best rerank config = `abstract`; no state_after, no manual oracle, no Mathlib.

## Mean metrics

| system | pass@1 | pass@5 | pass@10 | MRR | no_verified_top10 |
|---|---:|---:|---:|---:|---:|
| v18_broad_only | 0.500 | 0.583 | 0.604 | 0.537 | 19 |
| v20_broad_plus | 0.625 | 0.729 | 0.729 | 0.666 | 13 |
| v21_single_retrain | 0.667 | 0.729 | 0.750 | 0.698 | 12 |
| v21_capacity | 0.708 | 0.771 | 0.771 | 0.734 | 11 |
| v21_routed | 0.688 | 0.792 | 0.792 | 0.728 | 10 |
| v22_general_plus_exists | 0.729 | 0.812 | 0.833 | 0.774 | 8 |
| v22_general_balanced | 0.625 | 0.792 | 0.792 | 0.705 | 10 |
| v22_general_large | 0.667 | 0.771 | 0.812 | 0.725 | 9 |
| v22_general_balanced_large | 0.625 | 0.792 | 0.792 | 0.700 | 10 |

## Per-category pass@5

| category | v18_broad_only | v20_broad_plus | v21_single_retrain | v21_capacity | v21_routed | v22_general_plus_exists | v22_general_balanced | v22_general_large | v22_general_balanced_large |
|---|---|---|---|---|---|---|---|---|---|
| implication | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.833 |
| conjunction | 0.833 | 0.833 | 0.833 | 0.833 | 0.833 | 0.833 | 0.833 | 0.833 | 0.833 |
| disjunction | 0.600 | 0.600 | 0.400 | 0.600 | 0.600 | 0.600 | 0.600 | 0.600 | 0.400 |
| negation | 0.800 | 0.800 | 0.600 | 0.800 | 0.800 | 0.600 | 0.600 | 0.600 | 0.600 |
| equality_rewrite | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| exists | 0.250 | 0.250 | 0.000 | 0.000 | 0.250 | 0.750 | 0.750 | 0.750 | 1.000 |
| forall | 0.667 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| nat_succ | 0.600 | 0.600 | 0.600 | 0.600 | 0.600 | 0.600 | 0.400 | 0.400 | 0.600 |
| bool | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| list | 0.800 | 0.800 | 0.800 | 0.800 | 0.800 | 0.800 | 0.800 | 0.600 | 0.800 |

## Single-axis effects (per-category pass@5 delta)


**+exists (plus_exists − v21_single_retrain)**

- disjunction: +0.200
- exists: +0.750

**+balance (balanced − plus_exists)**

- nat_succ: -0.200

**+capacity (large − plus_exists)**

- nat_succ: -0.200
- list: -0.200

**+capacity (v21_capacity − v21_single_retrain)**

- disjunction: +0.200
- negation: +0.200

**+balance+capacity (balanced_large − plus_exists)**

- disjunction: -0.200
- implication: -0.167
- exists: +0.250

## Does exists interfere with the dominant operations?

- categories **dropped** by adding exists: (none)
- categories **improved**: ['disjunction', 'exists']
- categories **stable**: ['implication', 'conjunction', 'negation', 'equality_rewrite', 'forall', 'nat_succ', 'bool', 'list']

## Training volume by category (rows, by required_operation)

| pool(system) | implication | conjunction | disjunction | negation | equality_rewrite | exists | forall | nat_succ | bool | list | (unmapped) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v22_general_plus_exists | 764 | 89 | 4 | 513 | 0 | 510 | 689 | 0 | 189 | 0 | 489 |
| v22_general_balanced | 1159 | 800 | 400 | 800 | 0 | 905 | 689 | 0 | 400 | 0 | 1264 |
| v22_general_large | 764 | 89 | 4 | 513 | 0 | 510 | 689 | 0 | 189 | 0 | 489 |
| v22_general_balanced_large | 1159 | 800 | 400 | 800 | 0 | 905 | 689 | 0 | 400 | 0 | 1264 |

## Verdicts

- **Best single model**: `v22_general_plus_exists` at mean pass@5 = 0.812 (forall=1.0, exists=0.75).
- **Routed reference**: mean pass@5 = 0.792.
- **Routed − best single = -0.020** → single MATCHES/BEATS routing.
- Best single holds forall=1.0 AND implication=1.0 AND bool=1.0: **True**.

### Imbalance vs capacity vs interference vs architecture (data-driven)

- **Data imbalance? NO.** Oversampling the minority operations (`balanced`, mean pass@5 0.792) did **not** beat the un-rebalanced `plus_exists` (0.812); it only *hurt* ['nat_succ']. The fragile categories were already moved by simply *adding* the exists shapes, not by reweighting them.
- **Capacity? NO.** embed128/hidden192 (`large`, mean pass@5 0.771) did **not** beat `plus_exists` (0.812); it *hurt* ['nat_succ', 'list']. The base model was not capacity-bound on this benchmark.
- **Interference? NO.** Adding the exists corpus dropped **no** category relative to the same-recipe single retrain — `+exists` is pure gain (exists +0.75, disjunction +0.20).
- **Architecture / routing? NOT necessary.** The single `plus_exists` model reaches pass@5 0.812 ≥ routed 0.792 **and** pass@10 0.833 > routed 0.792, while holding forall=implication=bool=1.0. The residual gap was a **data-shape coverage gap** (missing exists/forall proof shapes), not a property of one shared decoder. Routing was a proxy for that missing coverage.

### Honest residuals

- **negation** is 0.600 under the `abstract` reranker for *every* v22 single model **and** for `v21_single_retrain` (not caused by exists). It is 0.800 under `raw` beam order for `plus_exists` (pass@10 confirms the verifying candidate is in the beam) — a reranker-ordering artifact, not a model deficiency. Routed keeps 0.800 only because it freezes the v20 model for negation.
- **balanced_large** reaches exists=1.0 but breaks implication (1.0→0.833) and disjunction (0.6→0.4): proof that pushing the minority harder *does* eventually re-introduce a tradeoff. `plus_exists` sits at the sweet spot.
