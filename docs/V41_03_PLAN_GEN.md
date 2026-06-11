# V41 Phase 3 — Plan generators (H14)

plan-AR / plan-flow / plan-MDLM, 10M (d_model 256), `statement → plan_str`, matched 1e8-token budget,
seed 3407 (+ flow 4242). Dev = 606 held-out plans.

## Plan-level dev metrics (pooled)
| model | plan exact-seq | per-token | distinct@4 |
|-------|------------|-----------|-----------|
| plan-AR | **0.122** | 0.652 | 15.6 |
| plan-MDLM | 0.070 | 0.611 | 7.75 |
| plan-flow (3407) | **0.0045** | **0.701** | 30.6 |

Flow's per-token is again the **highest** (0.701) while its exact-seq is the **lowest** (0.0045) — the
coherence signature, unchanged. Critically, flow's plan exact-seq is **19× worse than v40's head-only
plan probe** (0.085): the **typed-slot plan reintroduced the gap.** v40's success was specific to a
1-token-per-step head plan; here each step is multi-token (`rw ( LEMMA , LEMMA )`), and flow's
inter-token incoherence returns.

## H14 (abstraction, not length) — **REFUTED**
Stratified flow/AR plan exact-seq ratio (the v40 length-confound fix):
| plan length L | AR | FLOW | ratio |
|---|----|----|----|
| 1 | 0.198 | 0.008 | 0.041 |
| **2** | 0.061 | 0.0013 | **0.021** |
| **3+** | 0.0076 | 0.000 | **0.000** |

*Criterion:* ratio on L≥2 ≥ 0.4. *Result:* **0.021 (L=2), 0.000 (L≥3) → REFUTED.** Flow does **not**
abstract better at the typed-plan level. The v40 plan-probe headline (ratio 0.643) was a **representation
artifact** of the minimal head-only plan; the moment a plan step carries typed slots (multi-token), the
coherence gap is back. This is a clean, grounder-independent refutation — flow's plan *generation* is
poor regardless of downstream grounding. **Seed-4242 flow confirms** (dev exact 0.007 ≈ seed-3407's
0.0045) — both seeds far below plan-AR's 0.122, so the negative is two-seed-stable.
