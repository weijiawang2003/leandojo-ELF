# V21 capacity-tradeoff analysis

Answers the v21 brief's Part 6 questions using the four-config
comparison on the v18 broad-core benchmark (best rerank config =
`abstract`, timeout-stable; cache shared across configs).

## The four configs

| config | what it is | mean pass@5 | pass@1 | pass@10 |
|---|---|---:|---:|---:|
| v20 baseline | single broad-plus model (2,099 rows) | 0.729 | 0.625 | 0.729 |
| **A** = v20 | (same as baseline) | 0.729 | 0.625 | 0.729 |
| **B** single-retrain | v20 pool + 677 forall rows (2,776), same arch | 0.729 | 0.667 | 0.750 |
| **C** routed | v20 broad-plus + forall specialist, category router | **0.792** | 0.688 | **0.792** |
| **D** higher-capacity | config-B pool, embed 128 / hidden 192 | 0.771 | 0.708 | 0.771 |

## Per-category pass@5 (the diagnostic)

| category | v20 | B single | C routed | D capacity |
|---|---:|---:|---:|---:|
| **forall** | 0.000 | **1.000** | **1.000** | **1.000** |
| implication | 1.000 | 1.000 | 1.000 | 1.000 |
| bool | 1.000 | 1.000 | 1.000 | 1.000 |
| equality_rewrite | 1.000 | 1.000 | 1.000 | 1.000 |
| conjunction | 0.833 | 0.833 | 0.833 | 0.833 |
| disjunction | 0.600 | **0.400** | 0.600 | 0.600 |
| negation | 0.800 | **0.600** | 0.800 | 0.800 |
| exists | 0.250 | **0.000** | 0.250 | **0.000** |
| nat_succ | 0.600 | 0.600 | 0.600 | 0.600 |
| list | 0.800 | 0.800 | 0.800 | 0.800 |

(Bold = changed vs v20.)

## Q1 — Did adding implication/bool examples overwrite forall behavior?

**Yes — confirmed directly by the v21 regression audit**
([`V21_FORALL_REGRESSION_AUDIT.md`](V21_FORALL_REGRESSION_AUDIT.md)).
The v20 broad-plus model's beam on forall goals contained **zero**
`exact h <arg>` instantiation candidates; it emitted only
destructuring shapes (`exact h with ⟨n, hp⟩`, `exact h ⟨ha, hb⟩`)
learned from the 948 implication+bool rows (45 % of the 2,099-row
pool). The schema was **absent from generation**, not merely demoted —
so no reranker could recover it. This is a single-model
capacity/distribution tradeoff.

## Q2 — Did the higher-capacity model help?

**Partially.** Config D (embed 128 / hidden 192 on the B pool)
recovers forall to 1.000 **and** — unlike single-retrain B — preserves
disjunction (0.600) and negation (0.800). Its pass@1 is the highest of
all configs (0.708), and val-time capacity clearly absorbs more
schemas than the embed-96/hidden-128 model. **But it still drops
`exists` 0.250 → 0.000.** Higher capacity *mitigates* the tradeoff
(fewer categories sacrificed) without *eliminating* it. Mean pass@5
0.771 — better than B/v20, worse than routing.

## Q3 — Did routing beat single-model retraining?

**Yes, decisively.** Config C (routing) is the only config with
**zero collateral damage**: every non-forall category's pass@5 is
**identical to v20**, while forall flips 0.000 → 1.000. Mean pass@5
**0.792** — the best of all four, +0.063 over v20.

The mechanism is structural: the router sends forall goals to a
specialist trained only on forall instantiation (val_exact 0.56 on its
focused pool) and everything else to the unchanged v20 broad-plus
model. Because the broad model is *literally the v20 model*, the
non-forall categories cannot regress — they reproduce v20 exactly.
Single-retrain (B) cannot offer this guarantee: every gradient step on
the forall rows perturbs the shared weights that also serve
disjunction/negation/exists, so the tradeoff merely **relocates**
(disjunction 0.60→0.40, negation 0.80→0.60, exists 0.25→0.00).

## Q4 — Are failures category-specific enough to justify panel routing?

**Yes.** The v18 broad-core categories are cleanly separable by the
text features the router uses (goal connective / hypothesis types →
`category` + `required_operation`), and the failure modes are
category-local: forall needs `exact h <arg>`, implication needs bare
`exact hp`, bool needs `cases b`. A single model trades these against
each other under a fixed parameter budget; a router lets each category
be served by a model that has not had its forall (or exists, or
disjunction) capacity spent on other shapes. The empirical zero-
collateral result is the justification.

## Conclusion (ranking)

**routing (C, 0.792) > higher-capacity (D, 0.771) > single-retrain
(B, 0.729) = v20 (0.729).**

- **Routing** is the right fix for the v20 forall regression: it
  recovers forall to 1.000, preserves implication/bool/everything-else
  exactly, and lifts the mean to 0.792.
- **Capacity** is a useful secondary lever (best pass@1, recovers most
  categories) but does not fully escape the fixed-budget tradeoff.
- **Single-model retraining** is a trap: it fixes the targeted
  category while silently breaking others — the v20→v21 forall story
  repeating at the disjunction/negation/exists level.

This is an **engineering** result about model selection under a
capacity budget, **not** a claim about theorem reasoning. The router
chooses a generator by category; it injects no proof templates, reads
no `state_after`, and uses no manual oracle.
