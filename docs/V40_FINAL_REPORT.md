# V40 — ELF beyond token salad: objects, decoders, geometry on real Mathlib

**Date:** 2026-06-10 (overnight) · **Branch:** `v40-elf-objects` (off `v39-scale-matrix`) · RTX 4080 16GB.
**Preliminary: one seed (3407), 30M params, n=44–45 real-Mathlib verified tiers.**

V40 attacked the three levers v39 left unexploited — the generation **object** (whole proof vs single
tactic), the decode-time **coherence** mechanism (block/semi-AR, snap-repair), and the embedding
**geometry** — plus a plan-level probe, on a **real-Mathlib** tier (vs v39's synthetic tier). Every arm
changed something v39 proved decisive; none re-ran v39's loser.

## 1. Hypothesis verdicts (pre-registered criteria)

| ID | Hypothesis | Criterion | Verdict | Numbers |
|----|-----------|-----------|---------|---------|
| **H6** | whole-proof object shrinks flow's relative gap | flow/AR dev-exact ratio ≥ 0.146 (2× v39's 0.073) | **REFUTED** | ratio **0.023** (flow 0.0008 / AR 0.0346); flow **0 verified** on real Mathlib (AR 0.422) |
| **H7** | block/semi-AR decode > plain 1-step | dev-exact ≥ 1.5× FLOW@1 at NFE≤8 | **SUPPORTED** | block_nb8 **0.0033 = 4.0×** 0.0008 — but absolute ≈10× below AR; per-token unchanged |
| **H8** | snap-repair > 1-step | dev-exact > 1.10× FLOW@1 (any R) | **REFUTED** | all R/t cells **0.0000** |
| **H9** | frozen/max-sep geometry lifts flow | unit-norm/scratch dev-exact ratio ≥ 1.5 | **REFUTED** | ratio **1.0** (unit-norm 0.0008 = scratch 0.0008); per-token 0.329 ≈ 0.323 |
| **H10** | MDLM ≈ AR on real-Mathlib whole-proofs | MDLM within 1 theorem of AR (tier-final) | **SUPPORTED** | tier-final: AR 20/44 vs MDLM **19/44** (−1, within criterion); MDLM pass@1 0.318 > AR 0.295 |

**Global exit rule:** triggered iff **H6–H9 all fail**. Final tally: **H6 REFUTED, H7 SUPPORTED, H8
REFUTED, H9 REFUTED** — 3 of 4 fail, but **H7 met its pre-registered criterion** (block decode 4× off
the floor) ⇒ **exit rule NOT triggered.** Per the pre-registration ("criteria decide, not narrative"),
the verbatim "flow is exhausted across objects/decoders/geometries" sentence is **withheld** — one lever
(semi-AR block conditioning) demonstrably moves coherence. **Substantive caveat that must travel with
this:** every arm leaves flow non-competitive (0 verified on real Mathlib; H7's win is 0.003 vs AR's
0.035), so the practical conclusion is one notch short of the exit sentence: continuous flow is a
*non-competitive* generator whose *only* working lever is block/semi-AR decoding. H9 refuted rules out
geometry as the explanation; the gap is intrinsic to single-shot embedding decoding.

## 2. The object result (H6) — flow collapses harder on whole proofs
Whole-proof dev exact-seq: AR 0.0346, MDLM 0.0252, **FLOW 0.0008**. Verified pass@10 on 45 real-Mathlib
theorems: AR **0.422**, MDLM 0.356, **FLOW 0.000** (both 1- and 16-step). Flow produces **zero
jointly-valid whole proofs**; AR/MDLM each verify 4 genuine multi-tactic proofs. Flow's per-token (0.323)
≈ AR's (0.320) with maximal distinct (32) — the coherence gap is *worse* at the object level: the longer
the structured object, the more an absent inter-token-coherence mechanism costs. This **refutes** the ELF
"natural fit = whole structured object" intuition at 30M scale.

## 3. The coherence result (H7/H8) — only block conditioning moves the needle
Block/semi-AR decode (condition each block on the snapped prefix) lifts joint coherence 4× (exact-seq
0.0008→0.0033) **with per-token unchanged** — isolating inter-token coupling as the addressable gap
(BD3-LM thesis, in miniature). But the absolute level stays ~10× below AR. Snap-repair (re-noise a
snapped prediction, re-predict) collapses to 0.0 — iterative embedding-space refinement discards
structure. The one constructive lever for continuous flow is semi-AR decoding; everything else fails.

## 4. Geometry (H9)
_[Phase 4 — unit-norm frozen embeddings vs scratch, matched budget; filling.]_

## 5. Plan-level probe (LPSF-lite) — the gap closes at the plan abstraction
flow/AR exact-seq ratio by object granularity: **plan 0.643** ≫ single-tactic 0.073 ≫ whole-proof 0.023.
At the plan level (head sequence, mean 1.74 heads) flow reaches **64% of AR's plan exact-seq** (0.085 vs
0.132; per-token 0.537 > 0.505). The coherence gap is a monotone function of *object granularity*, not a
fixed property of flow — the single positive signal for *where* continuous flow belongs (the plan/
abstraction level, i.e. LPSF). See V40_05.

## 6. Real-Mathlib verified headline (tier-final)
**Finalists named before verifying** (tier-final touched exactly once): **AR** and **MDLM** whole-proof
(best per discrete family), **FLOW@1** whole-proof (best flow sampler), **FLOW block_nb8** (best Phase-3
coherence mechanism). No H9 geometry finalist (refuted). Verified ONCE on tier-final (44 real-Mathlib
theorems, K=24, top-10), priority AR > MDLM > FLOW.

| model | pass@1 | pass@5 | **pass@10** (Wilson 95%) | solved | multi-tactic |
|-------|--------|--------|---------|--------|------|
| **AR** | 0.295 | 0.409 | **0.455** [0.32, 0.60] | 20/44 | 4 |
| **MDLM** | **0.318** | 0.364 | 0.432 [0.30, 0.58] | 19/44 | 3 |
| **FLOW@1** | 0.000 | 0.000 | 0.023 [0.00, 0.12] | 1/44 | 0 |

**H10 SUPPORTED:** MDLM (19) is within 1 theorem of AR (20) and *beats* AR at pass@1 — AR-competitive on
real-Mathlib whole proofs. CIs overlap heavily (AR≈MDLM within noise at n=44). **Coverage (v39B lesson —
coverage > aggregates):** AR-only **8**, MDLM-only **7**, both 12 → **AR∪MDLM = 27/44 (0.614)** ≫ either
alone. The two discrete generators are **complementary**, not subset — a real ensemble. **FLOW**: 1/44,
and its single solve is also found by MDLM ⇒ **zero ensemble value** (as in v39B). FLOW block_nb8 was not
tier-verified (decode path not wired to the Lean harness; its dev-exact 0.0033 ≈ 0 makes ~0 verified the
near-certain outcome). Detail: `outputs/v40/wholeproof/detail_finaltier/`.

## 7. Limitations
One seed (3407); 30M params; real-Mathlib tiers n=44–45 (wide CIs); **gold-compile-rate 13.7%** (version
skew v4.19 bench vs v4.30 scratch) ⇒ verified tiers skew single-tactic (72%); whole-proof statements
reconstructed from the first proof state (`state_to_example`), not source-extracted; dev = 614 (val-split
limit), full-set evaluated; block-decode verified on dev-exact only (decode path not wired to the Lean
tier). Honest negatives stand on the pre-registered criteria.

## 8. Recommendation for V41 — **build LPSF (plan-level flow)**
Justified only by tonight's numbers:
- **Archive token/whole-proof continuous flow as a competitive generator:** 0 verified on real Mathlib;
  the object change (H6), max-separation geometry (H9), and iterative snap-repair (H8) all failed; the
  gap is intrinsic to single-shot embedding decoding, not data/object/geometry.
- **The plan probe (§5) is the warranted next build:** flow reaches **64% of AR's exact-seq at the plan
  level** vs ~2–7% at the token level. Continuous flow's home is the **plan/abstraction** object. V41 =
  **LPSF-full**: a plan-flow emitting a tactic-head skeleton, each head expanded by an AR/MDLM tactic head
  + Lean verifier. This is the one direction with a positive coherence signal.
- **MDLM is a first-class discrete substrate, and AR+MDLM are complementary:** on tier-final MDLM is
  within 1 of AR (and beats it at pass@1), and **AR∪MDLM solves 27/44 vs 20 alone** (each covers ~7–8 the
  other misses). A discrete **AR+MDLM ensemble** is a cheap, real win worth productionizing now.
- If a *flow* token-level effort is ever revived, only **semi-AR block decoding** (H7) showed any lift,
  and only 4× off a near-zero floor — not worth it over LPSF.
