# V43 — LPSF scale-up under real controls (pre-registered plan)

**Branch:** `v43-lpsf-scale` off `v42-verifier-audit` · **Device:** RTX 4080, generate on `.venv-gpu` only · 2026-06-12

## Spine
V42 predicted: *if flow's union gain shrinks/inverts as the grounder strengthens, the "diversity"
value was an artifact of grounder weakness* (`docs/V42_04_LPSF_NEXT.md`). V43 builds the strong
grounder + the simp control and finds out. The cheapest falsifier (A1 simp-baseline) runs first and
can close the bet before any GPU time.

## Pre-registered hypotheses (criteria = the night's contract)
**Thesis A — real grounder × simp baseline (the decision)**
- **A1** (no training, first): `{bare-simp, simp_all, aesop}` sweep. Falsifier: simp-sweep ≥ flow∪AR
  uniques on dev ⇒ LPSF's H13 value = simp-bias, close LPSF as a mechanism result.
- **A2**: with premise-selection grounder, flow union gain over `{direct-AR ∪ plan-AR ∪ simp}`
  persists ≥ +2 in ≥2/3 seeds ⇒ diversity mechanism real → scale; else close.
- **A3**: retrieval grounder lifts gold-plan ceiling toward/through 0.35 (was 0.267 greedy / 0.311 beam-2).

**Thesis B — continuous vs discrete at the plan level**
- **B1**: flow per-token ≥ AR at every L; exact-seq ratio ≥0.5 @L≤2 → 0 by L=3+ (joint-modeling gap).
- **B2**: MDLM-over-plans ≈ AR exact-seq and adds complementary union solves.

**Thesis C — plan-abstraction granularity**
- **C1**: flow/AR exact-seq ratio monotone-decreasing in tokens/step; a head-mostly point is
  competitive (ratio ≥0.4 @L2) AND groundable.
- **C2**: coarse plans express enough verified tactics that the coarse-plan ceiling ≥ direct-AR.

**Thesis D — breadth (droppable)**: D1 plan-ensemble; D2 decode frontier (beam-4/retrieval >0.35?);
D3 multi-step `have…sorry`; D4 x-pred vs v-pred at plan level.

## Non-negotiable controls
simp/aesop + direct-AR columns in EVERY union table; generate on `.venv-gpu`; verify via
`verify_many_bisect` only with `verify_mode`+SHA stamped; ≥3 seeds {3407,4242,7331}, bar = union
gain ≥+2 in ≥2/3 seeds; touch tier-final once; persist candidates+plans+vmaps always.

## Close-out tree (pre-registered)
- A1 simp ≥ flow∪AR uniques → LPSF closes (mechanism result); MDLM = productionizable discrete
  substrate (v40 H10 AR∪MDLM 27/44 stands).
- A1 residual but A2 doesn't survive strong grounder → LPSF closes (sharper mechanism).
- A2 survives → diversity real → scale LPSF; B/C say which representation + substrate.
- B/C/D deliver the granularity frontier + plan-level continuous-vs-discrete result regardless of A.

## Theory anchors
ELF (arXiv:2605.10938, x-prediction); NAT/joint-vs-marginal (Gu 2018, Diffusion-LM Li 2022) vs
discrete absorbing-state ELBO (D3PM/MDLM/SEDD); LD4LG coarse-latent; 3D-Prover diversity→pass@k
(arXiv:2410.11133); premise selection beyond ReProver (LeanSearch v2, graph-augmented +25%,
REAL-Prover). No diffusion proof/plan generator exists in the literature — LPSF is a genuine niche.

## Sequencing
P0 A1 (no GPU) → P1 grounder + A3 + C2 (light) → P2 train coarse flow/AR/MDLM ≥3 seeds + C1 + B1
(GPU) → P3 A2 decision + B2 (GPU) → P4 D1-D4 (droppable) → P5 report + paper §4e.
