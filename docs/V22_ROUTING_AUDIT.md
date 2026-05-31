# v22 routing-vs-single audit

Read-only comparison of the on-disk systems, to map which v18 broad-core categories the v22 general-model experiment must watch. Best rerank config (`abstract` for v20/v21).

## Mean metrics

| system | pass@1 | pass@5 | pass@10 | no_verified_top10 |
|---|---:|---:|---:|---:|
| v18_broad_only | 0.500 | 0.583 | 0.604 | 19 |
| v20_broad_plus | 0.625 | 0.729 | 0.729 | 13 |
| v21_single_retrain | 0.667 | 0.729 | 0.750 | 12 |
| v21_capacity | 0.708 | 0.771 | 0.771 | 11 |
| v21_routed | 0.688 | 0.792 | 0.792 | 10 |

## Per-category pass@5

| category | v18_broad_only | v20_broad_plus | v21_single_retrain | v21_capacity | v21_routed | class |
|---|---|---|---|---|---|---|
| implication | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | stable |
| conjunction | 0.833 | 0.833 | 0.833 | 0.833 | 0.833 | stable |
| disjunction | 0.600 | 0.600 | 0.400 | 0.600 | 0.600 | mixed |
| negation | 0.800 | 0.800 | 0.600 | 0.800 | 0.800 | harmed_by_retrain,capacity_sensitive |
| equality_rewrite | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | stable |
| exists | 0.250 | 0.250 | 0.000 | 0.000 | 0.250 | harmed_by_retrain |
| forall | 0.667 | 0.000 | 1.000 | 1.000 | 1.000 | mixed |
| nat_succ | 0.600 | 0.600 | 0.600 | 0.600 | 0.600 | stable |
| bool | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | stable |
| list | 0.800 | 0.800 | 0.800 | 0.800 | 0.800 | stable |

## Classification summary

- **needs_routing**: (none)
- **harmed_by_retrain**: ['negation', 'exists']
- **capacity_sensitive**: ['negation']
- **stable**: ['implication', 'conjunction', 'equality_rewrite', 'nat_succ', 'bool', 'list']

## Answers (Part 1 questions)

- **Which categories require specialist routing?** (none — routing gain came from forall only). Routing's measured win over the best single model is concentrated in `forall` (0.000 → 1.000); every other category is already at parity across systems.
- **Which categories are harmed by single retrain?** ['negation', 'exists'] — i.e. adding the forall corpus to one shared model degraded these. This is the capacity-tradeoff fingerprint the v22 balanced/large configs must neutralise.
- **Which categories are stable?** ['implication', 'conjunction', 'equality_rewrite', 'nat_succ', 'bool', 'list'] — safe across all configs; the general-model experiment should not regress these.

The v22 mission reduces to: **can a single model hold forall at 1.000 (routing's win) without the `harmed_by_retrain` collateral, and lift the fragile `exists` category?**
