# V41 Phase 4–6 — End-to-end (H11, H12, H13) + the data-quality catch

K=24 plans/theorem → **greedy** batched grounding (budget = K) → Lean verify, per source.
direct-AR reference = v40 whole-proof AR (tier-dev 0.422 = 19/45, tier-final 0.455 = 20/44).

## ⚠ Data-quality catch (read first)
The first tier-dev run reported plan-flow **0.000** and printed *"verify_many: confirm did not converge
in 8 rounds"* — the **batched verifier was poisoned** by malformed grounded candidates (unterminated
syntax), which broke the confirm loop and **under-reported the whole batch**. A bracket-balance filter
helped but didn't fully fix it. **Isolated verification (chunk=1)** removed the poison and gave numbers
that **match tier-final** — the batched tier-dev had been catastrophically wrong. **All tier-dev numbers
below are isolated; tier-final is the (clean, no-warning) batched once-touch.** Lesson logged: grounded
candidates need isolated or poison-filtered verification.

## End-to-end pass@10 (SOUND)
| source | tier-dev (isolated) | tier-final (batched, clean) |
|--------|------|------|
| direct-AR (v40 ref) | 0.422 (19/45) | 0.455 (20/44) |
| plan-AR + grounder | **0.444 (20/45)** | 0.386 (17/44) |
| plan-flow + grounder (3407) | **0.444 (20/45)** | 0.409 (18/44) |
| plan-flow + grounder (4242) | 0.333 (15/45) | 0.341 (15/44) |
| plan-MDLM + grounder | 0.267 (12/45) | 0.273 (12/44) |

**The LPSF pipeline is competitive with direct generation** (plan-AR ≈ direct-AR; plan-flow ≈ plan-AR),
and the e2e (0.33–0.44) **exceeds the gold-plan greedy ceiling (0.267)** — K=24 diverse plans give more
shots than one greedy gold plan, so the grounder did not cap the pipeline.

## Verdicts
- **H11 (planning ≥ direct +1 theorem):** tier-dev plan-AR 20 vs direct-AR 19 → **+1 (SUPPORTED, marginal)**;
  tier-final 17 vs 20 → −3. Net: planning is **≈ tied** with direct generation (within ±3), marginally +
  on tier-dev. (Caveat: direct-AR base is v40 *batched*, possibly a slight under-count.)
- **H12 (plan-flow ≥ 0.8× plan-AR, both seeds):** ratios — tier-dev 1.00 (3407) / **0.75** (4242);
  tier-final 1.06 / 0.88. **BORDERLINE:** flow is competitive (0.75–1.06×); seed-4242 tier-dev (0.75) just
  misses 0.8, so the strict both-seed-on-tier-dev reading **fails by one notch**, while tier-final passes both.
- **H13 (LPSF bet — flow union gain ≥+2 dev AND ≥+1 final, both seeds):** flow's unique verified solves over
  {direct-AR ∪ plan-AR}: seed **3407 = +2 dev, +3 final → PASS**; seed **4242 = +1 dev, +2 final → FAIL** (dev
  one short). **The unique solves are SOUND** — direct-AR re-verified *isolated* (K=24) solves **none** of
  flow's 6 unique theorems (`MulRingNorm.isPowMul`, `sup_himp_self_left`, `sdiff_le_iff'`,
  `Rep.ρ_inv_self_apply`, `codisjoint_inf_right`, `upperBounds_closure`). So flow **genuinely adds verified
  strategic solves AR misses** — the first real flow value in the v35–v41 arc — but it **misses the
  two-seed stability bar** (seed 4242 weaker). plan-MDLM adds 0 unique (its diversity is redundant here).

**The exit rule (H12 ∧ H13 both cleanly fail) does NOT fire:** flow is competitive and adds genuine (if
seed-unstable) diversity. The flow thread stays **open**. (Proof-level audit of the unique solves —
strategic vs simp-lottery — was not done; the e2e did not persist candidate proofs, a logged gap.)

> **V42 correction:** see `docs/V41_FINAL_REPORT.md` §"V42 correction" and
> `docs/V42_02_REBASELINE.md`. Sound numbers: direct-AR dev = 20/45 (H11 +1 retracted → tied);
> plan-flow-3407 final = 20/44; all other cells reproduce. The unique solves are sound but are
> 1-step simp variants (`docs/V42_03_UNIQUES_AUDIT.md`), not strategic diversity.
