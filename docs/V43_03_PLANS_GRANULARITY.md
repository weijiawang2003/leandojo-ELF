# V43 — C1 (granularity frontier) + B1/B2 (continuous vs discrete at the plan level)

Seed 3407, matched 10M models, K=4 exact-seq + per-token, stratified by plan length L, dev splits.
Three granularities span the abstraction axis (`outputs/v43/plans/granularity_s3407.json`):
head-only (V40, 1 token/step) → coarse (head + generic `ARG`/`NONE`, arity kept) → full-typed
(head + `LEMMA`/`HYP`/`TERM`).

## C1 — flow/AR exact-seq RATIO by granularity (the sweet-spot test)

| granularity | L=1 | L=2 | L=3+ | groundable? |
|---|---|---|---|---|
| head-only | 0.80 | **0.60** | 0.00 | ❌ (no args for the grounder) |
| coarse (arity, generic ARG) | 0.05 | **0.038** | 0.00 | ✅ |
| full-typed | 0.08 | **0.034** | 0.00 | ✅ |

**C1 falsifier MET → REFUTED.** The pre-registered out is "No granularity gives flow ratio ≥0.4 at
L≥2 *with* non-trivial grounding coverage." Exactly that holds: head-only is the only place flow is
competitive (ratio 0.60 @L2) but it carries **no argument information to ground**; the moment any
argument structure is added — even a single generic `ARG` symbol (coarse) — flow collapses to 0.04,
*indistinguishable from full-typed* (0.034). **There is no head-mostly operating point that is both
flow-competitive and groundable.** The hoped-for sweet spot does not exist.

**This sharpens V42-H16.** V42 concluded the typed-plan collapse was *tokenization* (the
LEMMA/HYP/TERM vocabulary) and that "plan abstraction is real." V43 shows coarse (which drops that
vocabulary, using one generic `ARG`) collapses flow **just as hard** as full-typed. So the killer is
**not** the typed argument vocabulary — it is the **extra tokens per step** (sequence length).
Head-only worked because a length-1 plan is ~1 token, where "joint = marginal" trivially.

## B1 — joint-vs-marginal: per-token vs exact-seq (the mechanism)

flow vs AR, coarse granularity (the cleanest case):

| | per-token (L=1/2/3+) | exact-seq (L=1/2/3+) |
|---|---|---|
| coarse AR | 0.83 / 0.66 / 0.50 | 0.42 / 0.13 / 0.01 |
| coarse flow | 0.80 / 0.65 / 0.54 | **0.019 / 0.005 / 0.00** |

**B1 SUPPORTED — textbook.** Flow's **per-token accuracy ≈ AR** (0.80 vs 0.83 at L=1; flow even
*exceeds* AR's per-token at L=3+, 0.54 vs 0.50), yet its **exact-sequence rate is ~20–25× worse**
(0.019 vs 0.42 at L=1). Flow predicts each position nearly as well as AR but assembles the correct
*joint* sequence far less often — the non-autoregressive conditional-independence / marginal-not-
joint failure (Gu 2018; Diffusion-LM rounding, Li 2022) realized cleanly on Lean plans. The
strict prediction "flow per-token ≥ AR at every L" is marginally not met at L=1/2 (flow a few points
below) but holds at L=3+; the qualitative thesis — *flow's gap is joint modeling, not token
capacity* — is confirmed decisively. The head-only→coarse exact-seq cliff (0.48→0.019 at L=1, same
theorems) is the same effect: adding tokens per step lengthens the sequence flow must get jointly
right.

## B2 — MDLM at the plan level: intermediate, not AR-competitive

exact-seq, seed 3407:

| | L=1 | L=2 | L=3+ |
|---|---|---|---|
| AR (coarse) | 0.42 | 0.13 | 0.01 |
| MDLM (coarse) | 0.25 | 0.00 | 0.00 |
| flow (coarse) | 0.019 | 0.005 | 0.00 |
| AR (typed) | 0.40 | 0.15 | 0.02 |
| MDLM (typed) | 0.25 | 0.02 | 0.00 |
| flow (typed) | 0.03 | 0.005 | 0.00 |

**B2 REFUTED at L≥2, but the ordering is informative.** Discrete MDLM is **strictly intermediate**:
AR > MDLM ≫ flow on plan exact-seq. At L=1 MDLM (0.25) is ~13× flow (0.019) — iterative discrete
commitment recovers a lot of the joint structure flow misses — but it is well short of AR (0.42)
and collapses by L=2. So v40's whole-proof "MDLM ≈ AR" (H10) does **not** transfer to short typed
plans: where the target is a few highly-structured tokens, AR's exact left-to-right factorization
dominates, MDLM's parallel-refinement approximation lags, and continuous flow fails. The B2 union
value is read from A2 (e2e); on exact-seq alone, discrete diffusion buys a lot over flow but not
parity with AR at this granularity.

## Takeaways for the LPSF post-mortem
1. The continuous-flow coherence gap is **joint modeling over sequence length** (B1), and it bites
   the instant a plan carries any per-step argument structure (C1) — which is exactly when a plan is
   groundable. Continuous flow's only competitive regime (head-only) is the non-groundable one.
2. The discrete ladder AR > MDLM > flow holds at the plan level (B2), mirroring the token level —
   discrete iterative commitment > continuous single-shot, AR factorization best.
3. Combined with A1 (the verified uniques were simp-bias), there is **no granularity, substrate, or
   grounder regime** in which plan-level continuous flow earns verified value a baseline lacks.
