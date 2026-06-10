# V39 Phase 3 — Data-constrained crossover (Track A) and H2 verdict

**Question (H2):** in the data-constrained regime — small unique data U, many epochs at a
*matched token budget* — does flow/MDLM close on or beat AR? Grid = 3 families × U ∈
{461, 922, 1844, 3689}, all 12 cells at an identical 3e7-token budget (so U=461 trains
~7.5× more epochs than U=3689: 458 vs 61). Metric = dev exact-seq.

## Gap table (dev exact-seq)
| U | epochs | AR | MDLM | FLOW | AR−FLOW | AR−MDLM |
|---|--------|----|----|----|----|----|
| 3689 | 61  | 0.873 | 0.570 | 0.041 | 0.832 | 0.303 |
| 1844 | 115 | 0.789 | 0.561 | 0.020 | 0.770 | 0.229 |
| 922  | 229 | 0.744 | 0.637 | 0.055 | 0.689 | 0.107 |
| 461  | 458 | 0.574 | 0.520 | 0.006 | 0.568 | 0.055 |

## Reading — H2 = **REFUTED** (with an important caveat)

The AR−FLOW gap *does* shrink monotonically as U falls / epochs rise (0.832 → 0.568), which
is the brief's literal falsification criterion → not falsified *by that test*. **But the
mechanism is AR degradation under data scarcity, not flow improvement:**
- AR drops from 0.873 → 0.574 as U shrinks (it has less unique data to generalize from).
- FLOW stays in the salad band (0.006–0.055) at *every* U — it never becomes competitive.
- At the most data-constrained point (U=461, 458 epochs), flow is still **0.006 vs AR 0.574**.

So the spirit of H2 — "flow becomes competitive when data is scarce and epochs are many" — is
**refuted**: flow does not close the gap; the gap only narrows because the *baseline* falls
toward it. We mark H2 **REFUTED** and flag that the monotone-gap test is satisfied for the
wrong reason (a baseline artifact). Reporting only "gap shrinks → H2 holds" would be misleading.

**MDLM** tells the decisive secondary story: AR−MDLM gap is small (0.055–0.303) and MDLM stays
in the 0.52–0.64 band across all U — a *coherent* generator throughout. The collapse is therefore
**specific to continuous embedding-space flow**, not to iterative/diffusion-style generation:
masked *discrete* diffusion over the same trunk + vocab works. If one were to "pivot off AR," the
evidence points to **MDLM**, not continuous flow.

## What flow actually does (the coherence gap)
Per-token gold recovery stays 0.42–0.46 while exact-seq ≈ 0 — flow predicts each token's
embedding ~45% correctly but cannot assemble a jointly-valid sequence (bidirectional x-pred has
no mechanism to enforce inter-token agreement at decode time; v36's "no inter-token coupling").
Its high distinct (≈31) confirms it samples many *different* incoherent sequences rather than
collapsing to one — diversity without validity.

Plot: `outputs/v39/trackA/crossover_trackA.png` (left: vs epochs/unique-token; right: vs U).
H1 (does *more data*, not more epochs, rescue flow?) is tested on Track B (U up to 121k) — see V39_FINAL.
