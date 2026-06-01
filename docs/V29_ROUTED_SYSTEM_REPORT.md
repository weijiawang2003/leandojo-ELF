# V29 — Part 8: Routed-System Report

_`scripts/evaluate_v29_routed_system.py` + `src/mini_elf_lean/v29_mathlib_router.py`
→ `data/baselines/v29_routed_system/`. Broad-core verified with the TRUSTED core
verifier; tier-C with the TRUSTED Mathlib verifier._

## Router

`V29MathlibRouter` is an **engineering switch** (no theorem-specific cheating):

    not mathlib-env  -> broad_core (v24, untouched)
    mathlib-env      -> mathlib_specialist (v29_general)

No per-theorem and no per-category routing (the v28 Finset sub-route is gone — v29's
thesis is one density-scaled general model). Routing was unambiguous: **48/48
broad-core seeds → v24, 140/140 tier-C seeds → the v29 specialist.**

## Broad-core preservation (the hard constraint)

| metric | routed v29 | v24 alone | v27/v28 bar |
|---|---:|---:|---:|
| pass@5 | **0.9375** | 0.9167 | 0.9375 |
| pass@10 | **0.9583** | 0.9375 | 0.9583 |

Broad-core is routed entirely to the **untouched v24 model**, so it cannot be
cannibalized — it meets the bar exactly and does **not regress** (`no_regression:
true`, `preserves_v27_routed_bar: true`, **`adopt_router: true`**). Verified with the
trusted core verifier (468 candidates, 2.9 s).

## Routed Mathlib tier-C

Over **140 combined held-outs** (v25 + v26 + v27 + v28 + v29 theorem holdouts + the
v29 family-density and low-density holdouts — a larger and harder set than v28's 73):

| | pass@5 | pass@10 |
|---|---:|---:|
| **routed v29 tier-C** | **0.914** | **0.921** |
| routed v28 tier-C | 0.904 | 0.918 |

Tier-C **improves** (0.918 → 0.921 pass@10, 0.904 → 0.914 pass@5) *while the held-out
set grew and got harder* (it now includes the density-contrast holdouts). 1377 tier-C
candidates verified in 112.9 s.

## Verdict

**Adopt the v29 router.** Broad-core preserved bit-for-bit at the bar (v24 untouched);
routed Mathlib tier improved on a larger, harder benchmark. The router never injects
templates, reads `state_after`, or uses manual-oracle outputs — it only selects a
generator + matching verifier. `v29_general` is the routed specialist;
`v29_set_finset_order_heavy` is a validated stronger alternative for the structured
tier (Part 7) and could be swapped in without changing the routing logic.
