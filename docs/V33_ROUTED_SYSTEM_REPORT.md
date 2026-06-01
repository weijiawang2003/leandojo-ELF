# V33 — Part 7: Routed-System Report

_`scripts/evaluate_v33_routed_system.py` + `src/mini_elf_lean/v33_mathlib_router.py`
→ `data/baselines/v33_routed_system/`. Specialist = `v33_general_residual` (canonical
mode + raw v30 fallback). Tier-C = all prior held-outs + v32 stress + v33 fresh robustness._

## Broad-core preservation (hard constraint)

| metric | routed v33 | v24 | bar |
|---|---:|---:|---:|
| pass@5 | **0.9375** | 0.9167 | 0.9375 |
| pass@10 | **0.9583** | 0.9375 | 0.9583 |

Bit-for-bit at the bar, **no regression** (`adopt_router: true`).

## Routed Mathlib tier-C — essentially saturated

Over **244 held-outs** (the largest set to date — adds the v33 fresh-robustness holdout):

| | pass@5 | pass@10 |
|---|---:|---:|
| **routed v33 tier-C (244)** | **0.980** | **0.992** |
| routed v32 tier-C (202) | 0.946 | 0.950 |

Tier-C **0.950 → 0.992** on an even larger, harder set. Per-category pass@10:
nat / logic / function / **order** / finset / bool_option **1.00**, set 0.987,
list 0.941 — only ~2/244 miss (a couple of fresh list/set shapes, single-tactic).
**`order` jumped 0.89 → 1.00** (the residual-coverage `min/max/inf_comm` + `le_trans`
chains).

## v19 guard at scale

2401 canonical candidates generated, **64 unresolved-rejected (2.7 %)** dropped before
the verifier; raw fallback added 2019. The hardened decode reduced unresolvable forms;
the guard keeps the rest safe — no `unresolved_placeholder` reaches a metric.

## Adoption

**Adopt the v33 router.** Broad-core preserved bit-for-bit; routed tier-C 0.992 over the
hardest 244-theorem benchmark; canonical guard controlled. The router is an engineering
switch, not v19 placeholder decoding; never reads `state_after`; v24 untouched.
