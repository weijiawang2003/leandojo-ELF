# V39 Phase 4 — Verified evaluation (the headline table)

`TrustedMathlibVerifier(confirm=True)`, cached, on the frozen 24-theorem Mathlib tier.
Headline = the three U=3689 / 1e8-token snapshots. K=24 sampled → top-10 ranked/deduped →
verified. Verifier wall: 61 s (55 s Lean), well inside the 75-min budget.

## Headline verified pass@k (24-theorem tier)
| family | params | **pass@1** | **pass@5** | **pass@10** | verified exact-seq | per-token | novel-verified | #cands verified |
|--------|--------|--------|--------|---------|-----------|-----------|------|------|
| **AR**   | 25.8M | 0.833 | 0.917 | 0.917 | 0.800 | 0.609 | 1 | 90 |
| **MDLM** | 25.8M | **0.875** | 0.917 | 0.917 | 0.786 | 0.590 | 1 | 75 |
| **FLOW** | 26.6M | 0.292 | 0.500 | 0.500 | 0.137 | 0.599 | 0 | 235 |

## Reading
1. **AR pass@1 0.833 / pass@10 0.917** — reproduces the strong v35-line AR baseline.
2. **MDLM matches AR** (pass@1 **0.875**, pass@5/10 0.917): masked discrete diffusion is a
   first-class tactic generator here, not a poor cousin of AR.
3. **Continuous flow: pass@1 0.292, pass@10 0.500.** The headline contrast with v35:
   - v35 faithful CPU flow (v-prediction) = **0.000** verified pass@k.
   - v39 flow (x-prediction + 30M + more training) = **0.50 pass@10** — x-pred genuinely
     un-sticks the 0.000; flow now lands real, Lean-verified tactics on half the theorems at K=10.
   - But it is still ~0.4 below AR/MDLM in pass@1 and caps at 0.50 vs 0.92 pass@10.
4. **Flow needs more candidates to find a hit:** it verified 235 candidates (vs AR 90, MDLM 75)
   — its high diversity (distinct ~26–32) means many distinct sequences are tried, but the
   verified-hit rate per candidate is low. **novel-verified = 0** for flow: every flow tactic
   that verifies is already in the training corpus (no out-of-train discovery), vs 1 each for AR/MDLM.

## Verdict contribution
- This is the **headline three-way verified comparison** the v38 matrix was built for and never
  ran. AR ≈ MDLM ≫ FLOW on verified pass@k.
- x-prediction is necessary-but-not-sufficient: it removes the v35 zero, but at 30M / ≤3689
  unique pairs continuous embedding-space flow does not reach baseline-competitive verified rates.

Artifact: `outputs/v39/trackA/verified.json`. H3 diversity (distinct-*verified*) and H5 repair
are in V39_05 (extensions).
