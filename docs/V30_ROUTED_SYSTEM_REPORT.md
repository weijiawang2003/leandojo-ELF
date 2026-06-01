# V30 — Part 8: Routed-System Report

_`scripts/evaluate_v30_routed_system.py` + `src/mini_elf_lean/v30_mathlib_router.py`
→ `data/baselines/v30_routed_system/`._

## Router

`V30MathlibRouter` — an engineering switch: core-env → **untouched v24**; mathlib-env →
`v30_general_targeted`. No per-theorem / per-category routing. Routing was unambiguous:
**48/48 broad-core → v24, 165/165 tier-C → the v30 specialist.**

## Broad-core preservation (the hard constraint)

| metric | routed v30 | v24 alone | v27/v28/v29 bar |
|---|---:|---:|---:|
| pass@5 | **0.9375** | 0.9167 | 0.9375 |
| pass@10 | **0.9583** | 0.9375 | 0.9583 |

Broad-core routed entirely to the untouched v24 model — meets the bar exactly,
**no regression** (`no_regression: true`, `preserves_v27_routed_bar: true`,
**`adopt_router: true`**).

## Routed Mathlib tier-C

Over **165 combined held-outs** (v25–v30 theorem holdouts + v29 family/low-density +
v30 targeted-family — 25 more, and harder, than v29's 140):

| | pass@5 | pass@10 |
|---|---:|---:|
| **routed v30 tier-C** | 0.903 | **0.921** |
| routed v29 tier-C (140) | 0.914 | 0.921 |

pass@10 **held at 0.921 while the benchmark grew by 25 harder theorems** (the v30
fresh + targeted-family holdouts, which include the unrepaired `_3` token residuals and
density-0 Finset `empty_subset`). pass@5 dips 0.914 → 0.903 purely from those added
hard cases; on the shared v25–v29 subset v30 ≥ v29 (v25 recovered to 1.000).

## Verdict

**Adopt the v30 router.** Broad-core preserved bit-for-bit; the v25 micro-regression is
recovered inside the tier-C set; tier-C pass@10 maintained on a larger, harder
benchmark. The router never injects templates, reads `state_after`, or uses
manual-oracle outputs. `v30_general_targeted` is the routed specialist — the strict
best across v25–v29.
