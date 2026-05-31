# v24 regression analysis (Part 8)

v24 broad+residual vs v22 plus_exists on v18 broad-core (`abstract`). Mean pass@5 0.812 → 0.917; pass@10 0.833 → 0.938; no_verify 8 → 3.

## Per-category pass@5 (v22 → v24, Δ)

| category | v22 | v24 | Δ |
|---|---:|---:|---:|
| implication | 1.000 | 1.000 | +0.000 |
| conjunction | 0.833 | 0.833 | +0.000 |
| disjunction | 0.600 | 0.600 | +0.000 |
| negation | 0.600 | 1.000 | +0.400 |
| equality_rewrite | 1.000 | 1.000 | +0.000 |
| exists | 0.750 | 1.000 | +0.250 |
| forall | 1.000 | 1.000 | +0.000 |
| nat_succ | 0.600 | 0.800 | +0.200 |
| bool | 1.000 | 1.000 | +0.000 |
| list | 0.800 | 1.000 | +0.200 |

## Protected categories held (forall/impl/bool=1.0, negation≥0.8): **True**

## Regressions (pass@5 drop ≥ 0.1 or protected broken): **none**

No category regressed — the targeted residual corpus closed generator-bound failures **without** a category tradeoff.
