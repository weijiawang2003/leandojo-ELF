# V31 — Part 7: Routed-System Report

_`scripts/evaluate_v31_routed_system.py` + `src/mini_elf_lean/v31_mathlib_router.py`
→ `data/baselines/v31_routed_system/`. Specialist = `v31_canonical_general` in
**canonical mode** (canonicalize → decode → concretize-or-reject → union with raw v30
fallback)._

## Router

`V31MathlibRouter` — engineering switch: core-env → **untouched v24**; mathlib-env →
the v31 canonical specialist. Routing unambiguous: **48/48 broad-core → v24,
131/131 tier-C → the v31 specialist.**

## Broad-core preservation (the hard constraint)

| metric | routed v31 | v24 alone | bar |
|---|---:|---:|---:|
| pass@5 | **0.9375** | 0.9167 | 0.9375 |
| pass@10 | **0.9583** | 0.9375 | 0.9583 |

Bit-for-bit at the bar, **no regression** (`adopt_router: true`).

## Routed Mathlib tier-C

Over **131 combined held-outs** (v25–v30 + v30 targeted-family + the token-diversity
residuals):

| | pass@5 | pass@10 |
|---|---:|---:|
| **routed v31 tier-C** | **0.962** | **0.985** |
| routed v30 tier-C | 0.903 | 0.921 |

**Tier-C pass@10 jumps 0.921 → 0.985** (+0.064) — the canonical specialist + raw
fallback dissolves the token-coverage residuals that dragged v30 down.

## The v19 guard at scale

Pool stats over the tier-C theorems: **1267 canonical candidates generated, 11
unresolved-rejected (0.9 %)**, 1254 concretized cleanly, **968 added by the raw v30
fallback**. The 11 unmapped-slot candidates were dropped **before** the verifier — the
`unresolved_placeholder` failure that sank v19 simply does not occur, and the raw
fallback guarantees the routed pool ⊇ the v30 pool (so tier-C can only rise).

## Adoption decision

**Adopt the v31 canonical router.** All adoption-rule conditions hold: broad-core
preserved (bit-for-bit); v25/v26/v29 not regressed (all 1.000); token-diversity
improves (0 → 0.92); unresolved/concretization controlled (0.9 %, dropped pre-verify).
The router never injects templates, reads `state_after`, or uses manual-oracle outputs
— and it is **not** v19 placeholder decoding.
