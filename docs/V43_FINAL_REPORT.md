# V43 — LPSF scale-up under real controls: the flow thread closes (strong negative)

**Date:** 2026-06-12/13 (overnight) · **Branch:** `v43-lpsf-scale` · RTX 4080 · seeds {3407,4242,7331}.
All verification: `verify_many_bisect` (V42 sound path, == isolation), `verify_mode` stamped; all
generation on `.venv-gpu` (deterministic). Decisive verdicts isolation-ground-truthed.

## Headline
**The continuous-flow thread closes as a strong negative, three independent ways.** V42 predicted
flow's "diversity" value would dissolve once a simp baseline and a real grounder were present. V43
built both and confirms it:

1. **A1 (the cheapest falsifier, no training):** a trivial `simp`/`aesop` sweep catches **all 6**
   V42 flow-unique theorems (bare `simp` alone catches 5/6; `exact?` the 6th), all isolation-
   confirmed. Flow's H13 "strategic diversity" was **diversity-toward-simplicity**.
2. **A3 (the grounder):** a BM25 premise-selection grounder over 241k Mathlib premises has gold-plan
   ceiling **0.20** — *below* V42's neural grounder (0.267) and far under 0.35. No buildable grounder
   lifts the wall; lexical retrieval can't surface exact gold premises (the wall is dense/semantic
   premise selection). **There is no "strong grounder" for flow to benefit from.**
3. **A2 (the decision):** with the premise-selection grounder + coarse plans, flow's verified union
   gain over `{direct-AR ∪ plan-AR ∪ simp}` is **0 in both seeds** (bar was ≥+2 in ≥2/3) → close.

## Pre-registered verdict table
| ID | Hypothesis | Verdict | Evidence |
|----|-----------|---------|----------|
| **A1** | simp sweep captures flow uniques | **FALSIFIER MET → close** | 6/6 flow uniques simp/aesop-caught (5/6 bare `simp`); wide sweep solves 42/45 dev, 40/44 final |
| **A2** | flow gain survives strong grounder + simp | **FAILS bar → close** | flow gain 0/0 over base+simp, both seeds (3407, 4242) |
| **A3** | retrieval lifts ceiling toward 0.35 | **FALSIFIER MET** | retrieval ceiling 0.20 < neural 0.267 < 0.35; causality holds (corrupted 0.022) |
| **B1** | coherence gap is joint modeling, not capacity | **SUPPORTED (textbook)** | flow per-token ≈ AR (0.80 vs 0.83) but exact-seq 20–25× worse (0.019 vs 0.42) |
| **B2** | MDLM ≈ AR at plan level + adds union | **REFUTED @L≥2** | AR > MDLM ≫ flow exact-seq (0.42/0.25/0.019 @L1); MDLM collapses by L2; v40 MDLM≈AR doesn't transfer to short plans |
| **C1** | a granularity sweet spot (competitive + groundable) | **REFUTED** | flow/AR ratio @L2: head-only 0.60 (not groundable), coarse 0.038, typed 0.034 (groundable but flow dead) — no operating point |
| **C2** | coarse plans expressive enough | **expressibility yes (100%), e2e ceiling no** | 100% gold proofs coarse-factorizable; coarse e2e ceiling grounder-bound ≪ direct-AR |
| **D1** | plan-level ensemble beats AR | **FALSIFIER MET** | flow adds 0 over {AR ∪ plan-AR ∪ simp} |
| **D2** | decode frontier breaks 0.35 | **MET (flat)** | = A3, retrieval ceiling 0.20 |
| **D3/D4** | multi-step plans / x-vs-v | **dropped (time)** | disclosed; B1 already shows flow exact-seq 0 @L≥3 |

## Mechanism (what we now understand, grounded in theory)
- **B1 is the clean instance of the joint-vs-marginal failure** (Gu 2018 NAT; Diffusion-LM rounding,
  Li 2022): continuous flow predicts each plan token nearly as well as AR but assembles the correct
  *joint* sequence ~25× less often. **C1 sharpens V42-H16**: the head-only competitiveness V42
  attributed to "abstraction" is actually a **sequence-length** effect — a length-1 head plan is ~1
  token (joint = marginal, trivial); the moment any per-step argument structure is added (even a
  single generic `ARG`), flow collapses, because that is exactly when the plan is *groundable*.
  Flow's only competitive regime is the non-groundable one. There is no usable operating point.
- **B2** places discrete MDLM strictly between AR and flow on plan exact-seq — discrete iterative
  commitment recovers much of the joint structure flow misses, but at this short, highly-structured
  granularity AR's exact factorization dominates and MDLM lags. The discrete-ensemble win
  (AR∪MDLM 27/44) is a whole-proof phenomenon, not a plan-level one.
- **The tiers are mostly simp-closable** (A1: 42/45 dev, 40/44 final by a 15-tactic trivial sweep),
  and the trained generators *miss* most of those — the whole v40–v42 "competitive pass@k" framing
  was contests over a handful of non-trivial theorems, inside a simp-closable majority.

## Project-level conclusion
Across **objects** (token → whole-proof → plan), **decoders** (1/16-step, block, snap-repair),
**geometries** (scratch, unit-norm), **granularities** (head-only → coarse → typed), **substrates**
(flow vs MDLM vs AR), and now a **premise-selection grounder + simp control**, continuous embedded
flow earns **no verified value a trivial baseline lacks** on Lean tactic/plan generation. The flow
arc (v35→v43) is complete as a **mechanism-grounded negative**: the failure is the joint-vs-marginal
limit of single-shot continuous decoding (B1), invariant to abstraction level (C1). The standing
positive is **discrete**: MDLM is AR-competitive at the whole-proof level and AR∪MDLM is a
complementary, productionizable ensemble (v40 H10, 27/44, V42-sound).

## V44 recommendation (from the tally)
**Close the flow thread; do not scale LPSF.** The diversity bet failed its own pre-registered test
under sound measurement. Productive directions that follow from the evidence:
1. **Discrete ensemble for real** — scale AR + MDLM (the only substrates that model the joint), add
   a *dense/semantic* premise-selection retriever (the A3 wall: trained retriever / LLM reranker,
   LeanSearch-v2 style) — that is where verified gains live, not in the generator's diversity.
2. **Drop the simp-closable tier** — build an evaluation tier filtered to *non-trivially* provable
   theorems (a `simp/aesop/omega` sweep must fail) so that "verified value" measures something the
   trivial baseline doesn't already provide. Every prior tier overstated model contribution.
3. **No more continuous embedded flow** for verified Lean generation, at any granularity.

## Honest scope / drops
- Full coarse-AR/MDLM e2e and the AR∪MDLM∪flow union table: **dropped for time** (each e2e source
  ~45 min Lean-bound); flow's 0 gain over a plan-AR-inclusive base already proves 0 ensemble value.
- A2 seed 7331 e2e and tier-final e2e: **not run**; A1 (which *did* run on tier-final: 6/6 flow
  uniques caught, 40/44 simp-closable) supplies the tier-final closure; 2/2 zero-gain dev seeds
  settle the negative (guardrails permit single-seed negatives).
- D3/D4: dropped (designated-droppable).
- Artifacts: `outputs/v43/{simp,grounder,plans,union}/*` with `verify_mode`+SHA; docs V43_00–V43_05.
