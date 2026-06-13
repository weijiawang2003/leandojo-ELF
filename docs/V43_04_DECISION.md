# V43 Phase 3 — A2 decision (+ B2 union, C2 ceiling, D1 ensemble)

**A2 verdict: FAILS the pre-registered bar → LPSF closure confirmed under the premise-selection
grounder.** Flow's verified union gain over a simp-inclusive base is **0 in both seeds**.

## A2 — flow union gain over the simp-inclusive base (tier-dev, coarse plans + retrieval grounder)

Bases (tier-dev): learned-only `{direct-AR ∪ plan-AR}` = 25; `+ {simp,simp_all,aesop}` = 27;
`+ wide trivial sweep` = 42. (`outputs/v43/union/union_report_dev.json`)

| seed | flow solved | gain over learned-only (25) | gain over base+simp (27) | gain over base+wide (42) |
|---|---|---|---|---|
| 3407 | 14 | 0 | **0** | **0** |
| 4242 | 14 | +2 | **0** | **0** |

**Pre-registered A2 bar: union gain ≥ +2 in ≥ 2/3 seeds over the simp-inclusive base.** Flow scores
**0 in 2/2 seeds** → bar not met → **A2 falsifier fires → LPSF closes** (confirming the cheap A1
verdict). Seed 4242's "+2 over learned-only" is the A1 story in miniature: those two theorems are
simp-closable, so the gain vanishes the instant the base includes `simp` (gain 0 over base+simp).
Flow's diverse coarse plans ground (via premise retrieval) only to proofs a trivial baseline
already supplies.

*(7331 skipped — each e2e source is ~45 min Lean-bound; 2/2 zero-gain seeds already settle a
negative, which the guardrails permit single-seed. The full coarse-AR/MDLM e2e was dropped for the
same cost reason; flow's 0 gain over a plan-AR-inclusive base means flow can add nothing to any
AR-containing ensemble regardless — see D1.)*

## A2 robustness — there was no "strong grounder" to survive
The pre-registered A2 envisioned testing flow under a *strong* grounder. A3 (`V43_02_GROUNDER.md`)
showed the premise-selection grounder we could build (BM25 over 241k premises) has ceiling **0.20**,
*below* the V42 neural grounder (0.267) — lexical retrieval can't surface exact gold premises. So
the A2 result is read correctly as: *under the best grounder available tonight, flow's gain is 0*.
The closure does not hinge on grounder strength — A1 already showed flow's uniques are simp-bias
with the original grounder, and A2 confirms it with the retrieval grounder.

## B2 — discrete vs continuous at the plan level (union)
Exact-seq (`V43_03_PLANS_GRANULARITY.md`): AR > MDLM ≫ flow on coarse plans (L=1: 0.42 / 0.25 /
0.019). The verified-**union** B2 (does MDLM-plan add over AR-plan) required the coarse-AR/MDLM e2e,
**dropped for time**. What stands: at the plan level the discrete ladder AR > MDLM > flow holds on
exact-seq, and v40's whole-proof "MDLM ≈ AR, AR∪MDLM = 27/44" complementarity is a token/whole-proof
phenomenon that does **not** reappear at the short-plan level (MDLM collapses by L=2). The
productionizable discrete ensemble remains the v40 whole-proof result, not a plan-level one.

## C2 — is the coarse abstraction the bottleneck? No — the grounder is.
Coarse plans express **100%** of tier gold proofs (`V43_02_GROUNDER.md`). The coarse e2e pipeline's
ceiling is therefore set by *grounding*, not representation: bounded by the retrieval ceiling 0.20
(gold-plan), so any coarse-plan e2e (AR or flow) is ≤ ~9/45 ≪ direct-AR's 20/45. C2's "coarse
ceiling ≥ direct-AR" therefore **fails — because of premise selection, not abstraction loss**. The
representation is fine; the arg-filling wall (A3) is the limiter.

## D1 — plan-level ensemble value of flow
Flow's gain over `{direct-AR ∪ plan-AR ∪ simp}` is 0 (both seeds). Since that base already contains
the AR-family plan generator and simp, **flow contributes 0 unique solves to any ensemble built on
AR + simp** — D1's "union == AR(+simp)" falsifier is met without the full ar∪mdlm∪flow table. The
plan-level ensemble has no flow value.

## Bottom line
Every leg of Thesis A closes the same way: **A1** (simp catches all flow uniques) → **A3** (no
buildable grounder lifts the ceiling) → **A2** (flow gain 0 over the simp-inclusive base, both
seeds). LPSF is closed not as "didn't beat a strong baseline" but as "its verified value was
simp-bias, confirmed three independent ways."
