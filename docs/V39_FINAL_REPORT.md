# V39 — GPU-scale ELF-flow vs MDLM vs AR for Lean tactics: final report

**Date:** 2026-06-10 (overnight, RTX 4080 16GB) · **Branch:** `v39-scale-matrix`
**One-seed (3407) preliminary evidence; 24-theorem verified tier; theorem-level verification only.**

This run finally executed the v38 matrix — the first **compute-matched** three-way comparison of
continuous embedded **flow** (x-prediction), masked-discrete diffusion (**MDLM**), and
**autoregression** (AR) on formally-verified single-tactic Mathlib generation — and added a scale arm
on 121k LeanDojo pairs plus five hypothesis tests.

---

## 1. Hypothesis verdicts

| ID | Hypothesis | Verdict | Key numbers |
|----|-----------|---------|-------------|
| **H1** | flow escapes token-salad at ≥30M + ≥64K unique pairs + x-pred | **REFUTED** | Track B U=121k (30M, x-pred): flow dev exact-seq **0.000** ≤ 0.02. Flow per-token *highest* (0.363 > AR 0.288) yet exact-seq 0 at every U≥16k; flat across scale while AR/MDLM climb. |
| **H2** | flow/MDLM closes on / beats AR as data shrinks (matched budget) | **REFUTED (flow); MDLM≈AR** | flow 4.5–13× below AR at every U; gap "shrinks" only via AR degradation + flow's epoch-memorization. MDLM within 0.05–0.30 of AR. |
| **H3** | at matched K, flow yields more *distinct verified* tactics than AR | **REFUTED** | distinct-verified/thm: AR **2.92** vs FLOW **0.625** |
| **H4** | flow keeps ≥90% of 32-step pass@1 at ≤8 steps | **SUPPORTED (twist: fewer is better)** | 8-step retention **1.19**; flow exact-seq 1-step 0.278 → 32-step 0.095 |
| **H5** | flow repairs AR's failed candidates (≥5% recovered) | **REFUTED** | flow-repair rescued **0/3** AR-failed theorems (0%) |

---

## 2. Headline verified pass@k (24-theorem Mathlib tier, TrustedMathlibVerifier confirm=True)

| family | params | sampler | **pass@1** | **pass@5** | **pass@10** | novel-verified |
|--------|--------|---------|--------|--------|---------|------|
| **AR**   | 25.8M | full decode | 0.833 | 0.917 | 0.917 | 1 |
| **MDLM** | 25.8M | 16-step | **0.875** | 0.917 | 0.917 | 1 |
| **FLOW** | 26.6M | 16-step (naive default) | 0.292 | 0.500 | 0.500 | 0 |
| **FLOW** | 26.6M | **1-step (honest best)** | **0.542** | **0.833** | **0.833** | **2** |

**The three-number story of continuous flow:** v35 (v-prediction) = **0.000** → v39 x-pred @16-step =
0.50 pass@10 → v39 x-pred @1-step = **0.83 pass@10 + 2 novel discoveries**. x-prediction plus the
*correct* (1-step) sampler closes most of the pass@10 gap to AR/MDLM (0.83 vs 0.92), but flow's
pass@1 (0.54) stays well below AR/MDLM (0.83–0.88): flow needs many samples to land its hit.

## 3. Crossover (Track A, matched 3e7-token budget, dev exact-seq, flow at best 1-step)
| U | epochs | AR | MDLM | FLOW |
|---|--------|----|----|----|
| 461  | 458 | 0.574 | 0.520 | 0.128 |
| 922  | 229 | 0.744 | 0.637 | 0.105 |
| 1844 | 115 | 0.789 | 0.561 | 0.083 |
| 3689 | 61  | 0.873 | 0.570 | 0.064 |

AR scales cleanly with data; MDLM is a genuine AR competitor; continuous flow sits an order of
magnitude below and *declines* with more unique data (it rides epochs/memorization, not diversity —
v37's sample-efficiency limit, restated). The AR−FLOW gap narrows as U falls only because AR
degrades and flow's memorization grows — **flow never becomes competitive.** Plots:
`crossover_trackA_fair.png`, `curves_trackA.png`.

## 4. Sampling-compute frontier (E1/H4)
Flow is a **1-step** model: exact-seq 1-step 0.278 ≫ 32-step 0.095; integrating the probability-flow
ODE drifts away from decodable embeddings. CFG helps monotonically (cfg=2>1). Throughput (E4, batch
256): AR 420 tac/s, flow@8 177, flow@16 88 — flow only wins on speed at 1 step (~1k+/s), which is
also its best quality. `ext_nfe.png`.

## 5. Repair hybrid (E2/H5) and diversity (H3)
AR-draft + flow-repair: 0/3 rescues — seeding the flow near a near-correct draft does not buy
coherence. Flow's high candidate diversity (distinct 26–32 vs AR 4–11) does **not** convert to
verified diversity (distinct-verified 0.6 vs 2.9). Flow's one genuine edge: it surfaces 2–3
**out-of-train** verified tactics (novel) that AR/MDLM rarely do.

## 6. Scale arm (Track B / LeanDojo, 121,345 pairs, 30M, own dev set) — H1 = **REFUTED**
Matched 3e7-token budget across all 12 cells (all `completed=True`, 1860/1860 steps); dev = 1,599
held-out **novel** LeanDojo theorems (theorem-disjoint, real Mathlib — far harder than Track A's
template-similar dev). Family-appropriate dev sampler (flow 1-step, MDLM 16-step, AR full).

| U | epochs | AR ex / pt | MDLM ex / pt | FLOW ex / pt |
|---|--------|-----------|-------------|-------------|
| 4,000   | 44.3 | 0.000 / 0.271 | 0.000 / 0.266 | 0.002 / 0.368 |
| 16,000  | 11.1 | 0.005 / 0.295 | 0.013 / 0.241 | 0.000 / 0.363 |
| 64,000  | 2.8  | 0.011 / 0.294 | 0.013 / 0.267 | 0.000 / 0.363 |
| 121,345 | 1.5  | 0.013 / 0.288 | **0.016** / 0.221 | **0.000** / 0.363 |

**H1 REFUTED.** At the largest U (121k ≥ 64k), 30M, x-prediction: **flow dev exact-seq = 0.000 ≤ 0.02.**
Three robust observations:
1. **Flow's exact-seq is flat at 0 across the entire 30× data range** (and exactly 0.000 at every
   U≥16k), while AR/MDLM *climb* with data (0.000→0.013/0.016) — more data helps the discrete
   generators, not flow. Scale does not rescue flow.
2. **Flow has the *highest* per-token gold recovery (0.363, vs AR 0.288, MDLM 0.221)** yet the lowest
   exact-seq — the coherence gap is total. Flow predicts each token's embedding best (parallel
   prediction, no autoregressive error compounding) but never assembles a jointly-valid tactic. This
   is the cleanest statement of the failure mechanism in the whole v35–v39 line.
3. **The data/epoch tradeoff cannot rescue flow:** it is ~0 at *both* ends — 44 epochs on 4k pairs
   (0.002) and 1.5 epochs on 121k pairs (0.000). Neither memorization nor diversity coverage helps.

Caveat: at matched budget the largest cells see only 1.5 epochs, so AR/MDLM are also undertrained on
this hard novel-Mathlib task (exact-seq 0.013–0.016, barely above the 0.02 line). The exact-seq bar is
stringent for *all* families here; but flow being *pinned at 0* while strictly *worse on the joint
metric despite better per-token* is a clean, scale-robust refutation. Plot: `scale_trackB.png`.

## 7. Limitations
- **One night, one seed (3407).** Preliminary evidence, not a benchmark.
- **24-theorem verified tier** + theorem-level verification only (LeanDojo `run_tac` blocked; no
  `state_after` claims). Track B is judged on dev exact-seq, not Lean (distribution/vocab mismatch).
- **30M params**, ≤121k unique pairs — well below the ELF arXiv scale; "ELF-*style*", not a repro.
- Block/semi-AR (BD3-LM) decoding not implemented (E3 out of scope).
- Flow's headline at 1-step was found by a post-hoc sampler sweep; not separately seed-replicated.

## 8. What would change my mind (one next experiment per hypothesis)
- **H1:** train flow at U≥256k / ≥100M for ≥several epochs; if dev exact-seq climbs past ~0.3 it's a
  data/scale story, not an architecture wall.
- **H2:** a learned (non-tied) decoder head or a discrete-token consistency loss on top of flow — does
  enforcing inter-token agreement at decode time close the coherence gap?
- **H3/H5:** repair with a *coherence-regularized* flow (e.g. CE-anchored at every step, or 1-step
  only) and larger K; 0/3 at K≈6 is a weak negative.
- **H4:** characterize the ODE drift directly (teacher-forced x-pred token accuracy vs free-running at
  each step) to confirm 1-step optimality is the readout geometry, not luck.

## 9. Recommendation
1. **AR remains the tool** for verified single-tactic Mathlib generation (pass@10 0.92).
2. **If pivoting off AR, pivot to MDLM, not continuous flow.** Masked discrete diffusion over the same
   trunk/vocab is AR-competitive (pass@1 0.875) and coherent at every data scale; continuous
   embedding-space flow is not, at this scale.
3. **Continuous flow is a 1-step, diversity/novelty instrument, not a precision one.** If kept, run it
   at 1 step (best + fastest) and use it as a *novel-candidate proposer* feeding an AR/MDLM+Lean
   verifier — not as a standalone generator.
4. **Do not invest further in many-step embedded-flow sampling or AR-draft flow-repair** at CPU/30M
   scale; both are clean negatives. The open door is scale (H1) and a coherence mechanism (H2 §8).
