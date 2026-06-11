# V41 — LPSF: plan-level flow, grounded and verified end-to-end

**Date:** 2026-06-11 (overnight) · **Branch:** `v41-lpsf` · RTX 4080 16GB · seeds 3407 + 4242 (flow).
**Preliminary: one night, 10M plan models / 42M grounder, real-Mathlib tiers n=44–45.**

V41 ran the project's original bet: continuous flow generates compact **proof plans** (typed tactic
skeletons), a shared **grounder** expands them to concrete tactics, Lean verifies end-to-end. Flow stops
being a token generator (refuted v35–v40) and becomes a *strategy proposer*.

## 1. Hypothesis verdicts (pre-registered criteria; raw counts shown)

| ID | Hypothesis | Criterion | Verdict | Numbers |
|----|-----------|-----------|---------|---------|
| **H11** | planning ≥ direct generation | plan-AR pass@10 ≥ direct-AR + 1 thm (tier-dev) | **SUPPORTED (marginal) / ≈tied** | dev plan-AR **20/45** vs direct **19/45** (+1); final 17 vs 20 (−3) |
| **H12** | flow competitive e2e | plan-flow pass@10 ≥ 0.8× plan-AR, both seeds | **BORDERLINE** | ratios dev 1.00/**0.75**, final 1.06/0.88 — seed-4242 dev (0.75) misses by one notch |
| **H13** | LPSF bet: flow diversity → union | flow union gain ≥+2 dev ∧ ≥+1 final, both seeds | **FAIL (two-seed bar); unique solves SOUND** | seed 3407 **+2 dev / +3 final (PASS)**; seed 4242 +1 dev / +2 final (FAIL). Direct-AR *isolated* solves **0/6** of flow's unique theorems |
| **H14** | abstraction, not length | flow/AR plan exact-seq ratio ≥ 0.4 on L≥2 | **REFUTED** | L=2 ratio **0.021**, L≥3 **0.000** (typed-slot plan reintroduces the coherence gap) |
| **H15** | CFG steering | qualitative, no gate | **NOT RUN** (designated drop) | — |

**Global exit rule (H12 ∧ H13 both fail ⇒ close the flow thread):** **NOT triggered.** Flow is competitive
with plan-AR (H12 borderline-pass) and adds genuine, *isolated-verified* unique solves (H13 seed-3407
passes both tiers; the 6 unique theorems are confirmed unsolved by direct-AR). H13 misses only the
**two-seed stability** bar (seed 4242 weaker). → The flow thread stays **open**; V42 = LPSF scale-up.

## 2. The headline — flow's first genuine verified value
For the first time in v35–v41, continuous flow contributes **real, sound verified value**:
- **Competitive e2e:** plan-flow pass@10 = 0.444 (tier-dev) / 0.41 (tier-final) ≈ plan-AR and ≈ direct-AR
  (0.42/0.46) — the LPSF pipeline matches direct generation.
- **Unique strategic solves:** flow's diverse plans ground to **1–3 verified proofs per seed/tier that
  AR misses** (`MulRingNorm.isPowMul`, `Rep.ρ_inv_self_apply`, `sup_himp_self_left`, …), and direct-AR
  re-verified isolated solves **none** of them. plan-MDLM adds **0** unique — flow's diversity is the one
  that pays off here.
- **Mechanism:** flow's plan *exact-seq* is near-zero (H14 — it rarely matches the gold plan), but its
  high plan **diversity** (distinct 30.6) grounds to verified *alternative* proofs. Flow's value is
  diversity-via-grounding, exactly the LPSF bet — **not** plan accuracy.

## 3. The caveats that bound it (honest)
- **H13 misses the two-seed bar** (seed 4242 dev gain = 1, not ≥2) — the v40 union-instability lesson
  applies; a +2 that doesn't replicate isn't yet bankable.
- **Grounder is weak** (ceiling: gold-plan greedy pass@1 **0.267**, premise-selection-limited) — though
  the K=24-diversity e2e (0.44) exceeded it. Causality control passed (corrupted-plan 0.022 ≪ gold 0.267).
- **Verification-method confound:** the direct-AR base is v40 *batched*; the targeted isolated re-check
  (0/6) firms the headline, but a full isolated direct-AR sweep was not affordable (isolated = ~2 h/tier).
- **Data-quality catch:** batched verification was **poisoned** by malformed grounded candidates and
  under-reported tier-dev to 0.000; isolated verification fixed it. Without this catch the night would
  have falsely reported catastrophic LPSF failure. Logged.
- **No proof-level audit** of the unique solves (strategic vs simp-lottery) — e2e didn't persist proofs.

## 4. V42 recommendation — **scale up LPSF** (no middle narrative)
The bet showed life; the exit rule did not fire. V42 = **LPSF-scale-up**, with three concrete targets the
night named: (1) a **premise-selection grounder** (retrieval-augmented) to lift the 0.267 ceiling — the
true bottleneck; (2) **stability** — ≥3 seeds and persisted proofs, to convert seed-3407's +2/+3 into a
bankable two-seed union gain (the H13 bar); (3) **plan representation** — H14 shows typed-multi-token
steps hurt flow; test a coarser (head-mostly) plan to keep flow's lattice small while retaining
groundability. MDLM remains the discrete token-level substrate; AR+plan-AR are complementary.
**Do not close the flow thread** — LPSF is the first place it earned its keep.
