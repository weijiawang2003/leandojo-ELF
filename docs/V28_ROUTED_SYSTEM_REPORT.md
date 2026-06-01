# V28 Part 7 — Routed System & Broad-Core Preservation

_Script: `scripts/evaluate_v28_routed_system.py`.
Router: `src/mini_elf_lean/v28_mathlib_router.py`.
Output: `data/baselines/v28_routed_system/`._

The router is an **engineering switch**, not theorem reasoning:

```
core-env theorem    -> v24 broad-core model (UNTOUCHED) + core verifier
mathlib-env theorem -> best v28 specialist (v28_general) + import-Mathlib verifier
(optional finset sub-route OFF unless validated; see below)
```

Specialist auto-selected by Part 6 as **`v28_general`** (best on the 30-theorem v28
holdout). Both tiers verified with the **trusted** verifier (core / `import Mathlib`).

## Routing

| | value |
|---|---|
| broad-core seeds → v24 | **48 / 48** |
| tier-C seeds → specialist | **73 / 73** |

No theorem-specific routing; routing is purely by environment (imports / mathlib
flag / corpus source).

## Broad-core preservation (the hard requirement)

| metric | routed v28 | v27 routed bar | raw v24 eval | verdict |
|--------|:---:|:---:|:---:|:---|
| broad-core pass@5 | **0.9375** | 0.9375 | 0.9167 | ✅ = v27 bar, ≥ v24 |
| broad-core pass@10 | **0.9583** | 0.9583 | 0.9375 | ✅ = v27 bar, ≥ v24 |
| pass@1 | 0.7708 | — | — | — |

`preserves_v27_routed_bar = True`, `no_regression = True`, **`adopt_router = True`**.
Because the v24 model is untouched and every broad-core theorem routes to it, routed
broad-core is **bit-identical to the v27 routed bar** — the Mathlib tier improved
with **zero** cost to broad-core. The router is safe to adopt.

## Routed Mathlib tier (v25 + v26 + v27 + v28 holdouts combined, n = 73)

| config | pass@1 | pass@5 | pass@10 |
|--------|:---:|:---:|:---:|
| best (`abstract`) | 0.589 | 0.904 | **0.918** |

This is the combined routed Mathlib-tier number across all four held-out benchmarks
(it is intentionally **not** collapsed with broad-core into one misleading score —
the two tiers are reported separately).

## Optional Finset sub-route

`V28MathlibRouter` supports an optional `category == finset → finset_specialist`
sub-route, **off by default**. It is *not* enabled in the adopted configuration:
`v28_general` already reaches 0.833 on held-out Finset, and `v28_finset_specialist`
is weaker on the overall v28 holdout (0.800 vs 0.867), so a dedicated Finset route is
not justified yet. The hook exists for when a validated Finset specialist clearly
beats the general model on Finset without hurting the rest.

## Honesty

Real Lean (core + `import Mathlib`). No `state_after`. No manual oracle. The v24
broad-core model is untouched; the router only selects a generator + verifier
backend. No naive verifier used for any number here.
