# V40 Phase 2 — Three-way on whole-proofs (H6, H10 first look)

AR / MDLM / FLOW(x-pred) at 30M on the whole-proof corpus (U=MAX 45,820), matched 1.5e8-token
budget (10.77 epochs each), batch 128, seed 3407. Object = a complete `example stmt := by <proof>`,
not a mid-proof single tactic. Dev = 614 held-out novel-theorem pairs (full-set eval).

## Dev metrics (whole-proof, novel theorems)
| family | dev exact-seq | per-token | distinct | val_loss |
|--------|-----------|-----------|----------|----------|
| AR | **0.0346** | 0.320 | 28.1 | 2.011 |
| MDLM | 0.0252 | 0.224 | 13.4 | 1.736 |
| FLOW (1-step) | **0.0008** | 0.323 | 32.0 | 1.117 |

## H6 (object) — **REFUTED**
*Criterion:* flow/AR whole-proof dev-exact ratio ≥ 0.146 (2× v39's token-level 0.073).
*Result:* **0.0008 / 0.0346 = 0.023** (final/matched-budget checkpoint) — not only below 0.146, it is
**~3× worse** than v39's token-level ratio. **Non-monotone caveat:** flow's dev exact-seq peaks **early** —
at the 25% checkpoint flow=0.0033, AR=0.0114 → ratio **0.289 (> 0.146)** — then *collapses* to 0.0008 by
100% (v37 overfit pattern). H6's pre-registered metric is the matched-budget checkpoint ⇒ REFUTED stands,
but had it been judged at flow's peak it would have passed. The object change made flow **relatively
worse** at convergence: assembling a coherent whole multi-tactic
proof punishes the inter-token-coherence gap *more* than a single tactic does. Flow's per-token (0.323)
is again as high as AR's (0.320) with maximal distinct (32) — the same "salad" signature, now on a
longer object.

## Verified pass@k on tier-dev (45 real-Mathlib theorems, K=24, top-10)
| model | pass@1 | pass@5 | pass@10 | solved | multi-tactic verified |
|-------|--------|--------|---------|--------|------|
| AR | 0.289 | 0.422 | **0.422** | 19/45 | 4 |
| MDLM | 0.289 | 0.333 | 0.356 | 16/45 | 4 |
| FLOW @1-step | 0.000 | 0.000 | **0.000** | 0/45 | 0 |
| FLOW @16-step | 0.000 | 0.000 | 0.000 | 0/45 | 0 |

**Flow produces ZERO verifiable whole proofs on real Mathlib** at both samplers — the strongest
statement of the coherence failure in the whole v35–v40 line, now at the *object* level. AR and MDLM
each verify **4 genuine multi-tactic proofs**. So the qualitative H6 sub-question ("does flow produce
jointly-valid multi-tactic proofs at all?") is answered **NO (0)**.

## H10 (real-world MDLM≈AR) — first look on tier-dev
AR 19/45 vs MDLM 16/45 (pass@10 0.422 vs 0.356) — MDLM is **3 theorems behind** AR on whole-proofs,
*not* within 1 (the H10 criterion). Unlike v39's single-tactic regime (MDLM ≈ AR), MDLM falls behind on
the harder whole-proof object (its per-token 0.224 is notably lower than AR's 0.320). The H10 verdict is
decided on **tier-final** in Phase 7; tier-dev leans against it. (novel counts 17 AR / 14 MDLM noted but
not yet audited — v39B taught that exact-string "novelty" is often a whitespace artifact.)

Detail JSONs: `outputs/v40/wholeproof/detail_devtier/`.
