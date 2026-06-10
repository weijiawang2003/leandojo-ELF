# Continuous Embedded Flow vs Discrete Diffusion vs Autoregression for Lean Tactic Generation: A Compute-Matched Study

*Working draft. Preliminary evidence: one machine-night, ≤2 training seeds, a 24-theorem verified
tier, models at 30M parameters. "ELF-style," not a reproduction of the ELF paper's scale.*

## Abstract

We ask whether a continuous **embedded flow** — generating a tactic as a sequence of token
*embeddings* via a probability-flow ODE, then reading out to tokens — can match autoregression (AR)
for formally-verified single-tactic Lean/Mathlib generation. On a single GPU we run the first
**compute-matched** three-way comparison of continuous flow (x-prediction), **masked discrete
diffusion** (MDLM), and AR on a shared param-matched Transformer trunk with a tied
nearest-embedding readout, at identical token budgets, across a 30×-data crossover and a 121k-pair
LeanDojo scale arm; headline models are evaluated with a trusted Lean verifier (`confirm=True`).
**Findings.** (1) x-prediction lifts flow off the prior v35 floor of 0.000 verified pass@k; with a
**1-step** sampler flow reaches pass@10 0.833 [Wilson 0.64–0.93] vs AR/MDLM 0.917 [0.74–0.98] —
a gap not resolvable at n=24. (2) But flow's value is illusory under scrutiny: it solves a **strict
subset** of AR's theorems with **zero unique solves**, covers **neither** of AR's two misses (even at
2× budget), and its "novel" verifications are whitespace variants of training tactics. (3) The failure
is **coherence**, specific to *continuous embedding space*: flow has the **highest per-token** gold
recovery yet ~0 exact-sequence recovery, and **masked discrete diffusion over the same trunk is
AR-competitive** (pass@1 0.875). (4) More data does not rescue flow (exact-seq flat at 0 from 4k→121k
pairs while AR/MDLM climb). We recommend AR as the tool and MDLM — not continuous flow — as the
alternative worth scaling.

## 1. Problem and prior work (v35–v37)

Embedded/latent flow models generate in a continuous space and decode to tokens, promising few-step
sampling and parallel (non-autoregressive) generation. Our earlier CPU-scale attempts established a
negative baseline: a faithful per-token flow with v-prediction got **0.000** verified pass@k vs a
matched token-AR's 0.875 (v35); a coherence sampler and a scale·objective ladder did not close the
gap (v36); and an overfit-control study reframed the failure as a **sample-efficiency limit** — the
flow memorizes a handful of exactly-correct, Lean-verified tactics but collapses as the support grows
(v37). Two hypotheses remained open: that the failure was *v-prediction* (the ELF paper argues
x-prediction is required with a shared readout), and that it was *scale/data*. This work tests both.

## 2. Method

**Shared trunk.** All three families use one prefix-LM Transformer (`V38Trunk`): sequence
`[clean condition tokens][target slots]`, a shared token embedding `E`, and a tied nearest-embedding
readout `(z·E − ½‖E‖²)/τ` (argmax = nearest embedding). They are param-matched by construction
(25.8M AR/MDLM, 26.6M flow at the 30M preset). Only the target-slot filling, attention mask, and head
differ: **AR** — causal mask, next-token CE; **MDLM** — bidirectional, absorbing-`[MASK]` diffusion,
masked-token CE with the MDLM 1/t weight; **FLOW** — bidirectional, noised target embeddings `z_t`,
**x-prediction** of the clean target embedding (not velocity), self-conditioning, logit-normal time,
training-time CFG.

**Matched budget.** Every training cell shares batch size and sequence length, so a fixed *token
budget* fixes the optimizer-step count; only the number of epochs over the unique data varies. Cosine
LR, 2% warmup, bf16, seed 3407 (FLOW headline replicated at 4242).

**Data.** *Track A* — a frozen verified single-tactic Mathlib corpus (3,689 train rows, vocab 377) with
a 24-theorem verified test tier (shared with v35–v37). *Track B* — LeanDojo Benchmark 4 (random split),
121,345 cleaned (state→tactic) pairs, train-only vocab 55,303 (OOV 0.2%), conditioning on
`full_name + state_before`; judged on a held-out novel-theorem dev set (distribution/vocab mismatch
makes 24-tier Lean verification inapplicable).

**Verification.** `TrustedMathlibVerifier(confirm=True)`, cached; K=24 sampled → frequency-ranked
top-10 → verified pass@{1,5,10}. Per-theorem detail (which candidate verified) is persisted for
ensemble analysis.

## 3. Results

**3.1 Matched matrix + crossover (Track A, dev exact-seq).** AR scales cleanly with data (0.574→0.873);
MDLM stays a close competitor (0.52–0.64); continuous flow (best 1-step sampler) sits an order of
magnitude lower (0.128→0.064) and *declines* with more unique data — it rides epochs/memorization, not
diversity. The AR−FLOW gap narrows as data shrinks only because AR degrades, not because flow improves;
flow never becomes competitive.

**3.2 Verified pass@k (24-theorem tier; Wilson 95% CIs).**

| family | sampler | pass@1 | pass@5 | pass@10 |
|--------|---------|--------|--------|---------|
| AR | full | 0.833 [0.64,0.93] | 0.917 [0.74,0.98] | 0.917 [0.74,0.98] |
| MDLM | 16-step | 0.875 [0.69,0.96] | 0.917 [0.74,0.98] | 0.917 [0.74,0.98] |
| FLOW | 16-step | 0.292 [0.15,0.49] | 0.500 [0.31,0.69] | 0.500 [0.31,0.69] |
| FLOW | **1-step** | 0.542 [0.35,0.72] | 0.833 [0.64,0.93] | 0.833 [0.64,0.93] |

The rescue from v35's 0.000 has **two** causes — x-prediction (→0.500 @16-step) and the 1-step sampler
(→0.833) — not "x-pred at scale" alone. CIs are wide; flow-vs-AR pass@10 is within noise at n=24.

**3.3 Step frontier.** Flow is a **1-step** model: exact-seq *decreases* monotonically with ODE steps
(1-step 0.278 → 32-step 0.095); Euler-integrating the flow drifts away from decodable lattice points.
1-step is both most accurate and cheapest (and only there does flow approach AR throughput).

**3.4 Seed replication (FLOW headline, 3407 vs 4242).** Retraining FLOW only (seed changed, all else
fixed) reproduces the headline: FLOW@1 **pass@10 = 0.833 in both seeds** (mean pass@1 0.521, range
0.50–0.54), and **1-step > 16-step pass@10 in both** (0.833 vs 0.500 and 0.583) — the "fewer-steps-is-
better" finding holds 2/2 seeds. Per the pre-registered rule (seed-2 pass@10 ≥ 0.75) the headline
stands, reported as the seed mean (≈0.83), not the max.

**3.5 Scale arm (Track B, H1).** Across U ∈ {4k,16k,64k,121k} at matched budget, AR/MDLM dev exact-seq
climbs (0.000→0.013/0.016) while **flow is pinned at 0.000 for every U≥16k** despite the **highest
per-token** recovery (0.363 > AR 0.288 > MDLM 0.221). Scale does not rescue flow.

**3.6 Ensemble / coverage (the decisive test).** AR solves 22/24; its two misses
(`v26w_inter_subset_left_union`, `v28_ord_min_le_right_0`) are covered by **no** flow setting, **no**
MDLM, and **not** AR at 2× budget (K=48). Every union (AR∪FLOW@1, AR∪MDLM, all-four) equals AR alone
(0.917). No model has a unique solve. A verbatim audit of "novel-verified" tactics finds the two
genuinely-novel strings are produced by AR/MDLM too, while flow's own novel strings (`simp [ ]`,
`intro h; exact   h`) are whitespace/empty-list variants of training tactics. **Flow has no ensemble
value here.**

## 4. Mechanism

Across both tracks the signature is identical and clean: **flow predicts each token's embedding better
than AR predicts each next token** (parallel prediction has no autoregressive error compounding) **yet
almost never assembles a jointly-valid tactic** (exact-seq ~0). The tied bidirectional x-prediction
head has no decode-time mechanism to enforce inter-token agreement; high sampling diversity (distinct
26–32 vs AR 4–11) is therefore *incoherent* diversity. MDLM, which commits tokens iteratively under a
discrete posterior over the same trunk, does not exhibit the gap — implicating **continuous embedding
space**, not non-autoregression per se.

## 5. Limitations
One night; seeds 3407 (+ a FLOW replication at 4242); n=24 verified tier ⇒ wide CIs (aggregate
flow-vs-AR gaps within noise); 30M params, ≤121k pairs (far below ELF scale); theorem-level
verification only (no `run_tac`/`state_after`); Track B dev metrics on 640 samples (160 of 1,599 dev
theorems × K=4); block/semi-AR decoding not implemented. A reproducibility relaunch (Track B batch-96,
`c9ddfaa`) lost no cells.

## 6. Conclusion
At this scale, **continuous embedded flow is not the tool** for verified Lean tactic generation:
x-prediction and 1-step sampling make it non-trivial, but it stays behind AR, fails to scale, and adds
no verified coverage AR lacks. **MDLM** — masked discrete diffusion over the identical trunk and vocab
— *is* AR-competitive and is the alternative worth scaling. The open scientific questions are whether
≥100M params / ≥256k pairs change the scale verdict (H1) and whether a decode-time inter-token
coherence mechanism (a learned head, or a discrete-consistency loss) can close the gap.

## Reproducibility
Branch `v39-scale-matrix`. Code: `scripts/v39_{train,grid,build_leandojo,analyze,verify,ext_*}.py`,
`scripts/v39b_ensemble.py`. Per-cell `config.json` (seed, git SHA, data fingerprint, measured tok/s);
metrics JSONL; per-theorem verification detail under `outputs/v39/trackA/detail/`. Phase reports
`docs/V39_00`–`V39_06`, `docs/V39_FINAL_REPORT.md`.
