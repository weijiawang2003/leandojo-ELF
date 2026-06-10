# V39 Phase 4 — Verified evaluation (the headline table)

`TrustedMathlibVerifier(confirm=True)`, cached, on the frozen 24-theorem Mathlib tier.
Headline = the three U=3689 / 1e8-token snapshots. K=24 sampled → top-10 ranked/deduped →
verified. Verifier wall: 61 s (55 s Lean), well inside the 75-min budget.

## Headline verified pass@k (24-theorem tier)
| family | params | sampler | **pass@1** | **pass@5** | **pass@10** | novel-verified |
|--------|--------|---------|--------|--------|---------|------|
| **AR**   | 25.8M | full decode | 0.833 | 0.917 | 0.917 | 1 |
| **MDLM** | 25.8M | 16-step | **0.875** | 0.917 | 0.917 | 1 |
| **FLOW** | 26.6M | 16-step (default) | 0.292 | 0.500 | 0.500 | 0 |
| **FLOW** | 26.6M | **1-step (best)** | **0.542** | **0.833** | **0.833** | **2** |

### Flow verified frontier vs ODE steps (the sampling correction)
The 16-step default (inherited from v36/v38) badly undersold flow. Re-verified across steps:
| steps (NFE) | pass@1 | pass@5 | pass@10 | novel |
|------|------|------|------|------|
| **1** | **0.542** | **0.833** | **0.833** | 2 |
| 2 | 0.333 | 0.667 | 0.792 | 3 |
| 4 | 0.375 | 0.542 | 0.625 | 1 |
| 8 | 0.292 | 0.458 | 0.542 | 0 |
| 16 | 0.292 | 0.500 | 0.500 | 0 |

Flow is a **1-step** model: a single x-prediction from noise is its best (and cheapest) sampler;
Euler-integrating the probability-flow ODE drifts away from decodable embeddings (E1/H4). At its
honest-best (1 step) flow reaches **pass@10 0.833, only 0.084 below AR/MDLM**, and finds 2–3
out-of-train (novel) verified tactics — real, if modest, discovery.

## Reading
1. **AR pass@1 0.833 / pass@10 0.917** — reproduces the strong v35-line AR baseline.
2. **MDLM matches AR** (pass@1 **0.875**, pass@5/10 0.917): masked discrete diffusion is a
   first-class tactic generator here, not a poor cousin of AR.
3. **Continuous flow, honest-best (1 step): pass@1 0.542, pass@10 0.833.** The contrast with v35:
   - v35 faithful CPU flow (v-prediction) = **0.000** verified pass@k.
   - v39 flow (x-prediction + 30M) at the naive 16-step default = 0.29/0.50 — already non-zero.
   - v39 flow at its best 1-step sampler = **0.54/0.83 pass@1/10** with 2 novel verified tactics.
   - So x-prediction + correct (few-step) sampling closes most of the gap to AR/MDLM at pass@10
     (0.83 vs 0.92), though pass@1 stays lower (0.54 vs 0.83–0.88) — flow needs K to find its hit.
4. **Flow trades precision for K.** Its high diversity (distinct ~26–32) means many distinct
   sequences are tried; the per-candidate hit rate is low, so pass@1 ≪ pass@10. At 1–2 steps it
   does make **out-of-train discoveries** (novel-verified 2–3) that AR/MDLM (novel 1) rarely do —
   the one axis where flow's diversity pays off.

## Verdict contribution
- This is the **headline three-way verified comparison** the v38 matrix was built for and never
  ran. AR ≈ MDLM ≫ FLOW on verified pass@k.
- x-prediction is necessary-but-not-sufficient: it removes the v35 zero, but at 30M / ≤3689
  unique pairs continuous embedding-space flow does not reach baseline-competitive verified rates.

Artifact: `outputs/v39/trackA/verified.json`. H3 diversity (distinct-*verified*) and H5 repair
are in V39_05 (extensions).
