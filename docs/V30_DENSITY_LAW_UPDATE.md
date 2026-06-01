# V30 — Part 9: Density Law Update

_`scripts/analyze_v30_density_law_update.py` →
`data/baselines/v30_density_law_update/report.json`. No Lean run._

v30 tested the v29 density law **out of sample**: does targeted repair of low-density
families actually fix their held-out failures?

## Before → after (best v29 vs v30_general_targeted, pass@10)

| bench | v29 best | v30 | Δ |
|---|---:|---:|---:|
| **v25_heldout** | 0.857 | **1.000** | **+0.143** |
| v26_holdout | 1.000 | 1.000 | 0 |
| v27_holdout | 1.000 | 1.000 | 0 |
| v28_holdout | 0.967 | 0.967 | 0 |
| v29_holdout | 1.000 | 1.000 | 0 |
| v29_family_density (`_3`) | 0.853 | 0.824 | −0.029 |
| v29_low_density | 1.000 | 1.000 | 0 |
| v30_holdout (fresh) | 0.333 | **0.867** | **+0.533** |
| v30_targeted_family | 0.10 | **0.60** | **+0.50** |

## RQ1 — recover v25 without hurting v28/v29? **Yes.**

v25 **0.857 → 1.000** (both `nat_add_assoc` and `set_empty_subset` recovered) with
**zero regression** on v26/v27/v28/v29. The recovered model even matches the heavy
config (v28 0.967). Targeted count-repair works and is free.

## RQ2 — does reaching density 4–6 improve held-out success? **Yes, for count-repair.**

The count-repair families (`add_assoc` 0→5, `empty_subset` 0→6, `le_refl` 3→7) all
recovered; the v30 fresh holdout (whose families v30 trained to ≥4) jumped 0.33 → 0.87.

## RQ3 — is the density law actionable for targeted construction? **Yes.**

v30 added only **155** verified rows (vs v29's 492) targeting **10** named families and
recovered the regression + lifted the fresh families — a surgical, law-guided repair,
not broad expansion.

## RQ4 — are remaining failures still single-tactic? **Yes.**

v30 residual classes: `unknown_identifier` 6, `type_mismatch` 3, `other`/`parse` 4 —
**0 multi-step**. Still vocabulary/API-bound.

## The one honest non-result: token-diversity repair

The `_3` residuals (`v29_family_density`) did **not** improve (0.85 → 0.82, flat). The
`failures-vs-threshold` table even looks inverted (below-4-sibling families 1.0 vs
≥4-sibling 0.5) — the **same confound** v29 flagged: the ≥4 bucket here is the *hard*
projection/membership families whose held-out `_3` members use element/hyp tokens
(`w`,`hw`) that **no training sibling carries**, while the below-4 bucket is
`empty_subset` (universal-tactic `simp`). So:

> **Refined density law:** held-out success rises with training siblings **when the
> held-out member's surface tokens are within the training distribution**. Pure count/
> token augmentation cannot cover an identifier a char/token seq2seq has never seen —
> that is the residual limit, and it is a *coverage* limit, not an architecture one.

## Verdict — no architecture / proof-state bottleneck

Count-repair fully validated the law out of sample (v25 recovered). The remaining
misses are single-tactic token-coverage cases, not multi-step or proof-state failures.
**LeanDojo next-state supervision is still premature.** v31 should either (a) widen the
token alphabet of the projection families further, or (b) accept that the last ~15% of
projection-direction binding is a small-model ceiling and bank the v25 recovery.
