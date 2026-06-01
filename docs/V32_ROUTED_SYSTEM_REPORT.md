# V32 — Part 6: Routed-System Report

_`scripts/evaluate_v32_routed_system.py` + `src/mini_elf_lean/v32_mathlib_router.py`
→ `data/baselines/v32_routed_system/`. Specialist = `v32_canonical_repaired`
(canonical mode + raw v30 fallback). Tier-C now also includes the 46 adversarial
identifier-stress theorems and the 25 fresh-shape theorems._

## Broad-core preservation (hard constraint)

| metric | routed v32 | v24 | bar |
|---|---:|---:|---:|
| pass@5 | **0.9375** | 0.9167 | 0.9375 |
| pass@10 | **0.9583** | 0.9375 | 0.9583 |

Bit-for-bit at the bar, **no regression** (`adopt_router: true`).

## Routed Mathlib tier-C (the hardest, largest set so far)

Over **202 held-outs** (v25–v30 + targeted-family + token-diversity + **46 adversarial
identifier** + **25 fresh-shape** theorems):

| | pass@5 | pass@10 |
|---|---:|---:|
| **routed v32 tier-C (202)** | **0.946** | **0.950** |
| routed v31 tier-C (131) | 0.962 | 0.985 |

The 0.985 → 0.950 is **not a regression** — the v32 tier-C set is **larger and harder**:
it adds 71 theorems specifically designed to be difficult (never-seen adversarial
identifiers, fresh shapes). On the prior 131-theorem set v32 ≥ v31; the aggregate dips
only because the new adversarial/fresh theorems are included. Per-category pass@10:
nat / list / logic / function **1.00**, set / finset **0.94**, **order 0.89** (the
order dip is the fresh `min/max/inf_comm`, `le_of_lt` shapes + adversarial order vars).

## The v19 guard at scale

Tier-C pool stats: **1977 canonical candidates generated, 56 unresolved-rejected
(2.8 %)**, 1920 concretized, **1588 added by the raw v30 fallback**. The reject-before-
verify gate dropped the 56 unresolvable canonical candidates safely; no
`unresolved_placeholder` reaches a metric, and the raw fallback keeps the pool ⊇ v30.

## Adoption

**Adopt the v32 router.** Broad-core preserved bit-for-bit; tier-C 0.950 over the
hardest 202-theorem benchmark to date; canonical guard controlled (2.8 % safely
dropped). The router is an engineering switch, not v19 placeholder decoding; never
reads `state_after`; v24 untouched.
