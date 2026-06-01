# V31 — Part 8: Density vs Token-Coverage Analysis

_`scripts/analyze_v31_density_vs_token_coverage.py` →
`data/baselines/v31_density_vs_token_coverage/report.json`. No Lean run._

## Headline: canonicalization dissolves the token-coverage ceiling

**token-diversity holdout (the 13 v30 residuals), pass@10:**

| model | token-diversity | standard-holdout floor (min v25–v29) |
|---|---:|---:|
| v30_general_targeted (baseline) | **0.00** | 0.967 |
| v31_raw_plus_projection_aug (B) | 0.77 | **1.000** |
| **v31_canonical_general (A)** | **0.92** | **1.000** |
| v31_raw_canonical_mixture | 0.92 | 0.955 |

Both approaches lift the residuals from 0; **canonicalization (A) is best (0 → 0.92)**
and, uniquely, also keeps every standard held-out at **1.000** (it even lifts v28
0.967 → 1.000 and the v30 targeted-family holdout 0.60 → 1.000).

## RQ1 — does canonicalization fix the `_3` residuals without v19's failure? **Yes.**

On the token-diversity holdout the canonical model generated 130 candidates with
**0 unresolved-rejected** (`pool_stats`), and the raw v30 fallback added 123 more. The
v19 `unresolved_placeholder` failure mode **did not occur** — canonical names are valid
identifiers, the parse is clean, and any unmapped slot would have been dropped before
the verifier (10 such drops did occur harmlessly in the *mixture* model, which still
hit 0.92).

## RQ2 — does it reduce token-coverage dependence? **Yes.**

The canonical model is identifier-invariant: `h`, `hw`, `hm`, `g` all map to the same
canonical slot, so a held-out member's unseen identifier no longer matters. v30's
13 residuals → **1** under canonicalization.

## RQ3 — memorization or real gap? **Memorization (now removed).**

The audit (Part 1) found 13/13 residuals were surface-token OOD. Canonicalization,
which removes raw identifier dependence, fixes 12/13 — confirming the failure was raw
identifier **memorization**, not an API/proof-shape gap.

## RQ4 — improve fresh held-out without broad expansion? **Yes.**

`canonical_general` adds **zero new theorems** — it is the v30 base *re-encoded* — yet
lifts token-diversity 0 → 0.92, targeted-family 0.60 → 1.00, and v28 0.97 → 1.00.
`raw_plus_projection_aug` (B) added only 140 verified rows and reached 0.77.

## The density law gains a second axis

> **Two-axis coverage law.** Held-out single-tactic success requires **(1) family
> density** (≥ 4–6 siblings — v29) **AND (2) surface-token coverage** of the held-out
> member's identifiers/projection forms (v30/v31). v29 supplied axis 1; v30 showed
> axis 2 is the residual ceiling; v31 supplies axis 2 two ways:
> - **canonicalization** makes the model identifier-invariant (axis 2 satisfied for
>   *all* identifiers at once) — most effective, zero new data;
> - **verified rename augmentation** brings the specific missing identifiers
>   in-distribution — simpler, raw model, slightly lower.

## Verified vs canonical — which is better?

Canonicalization (A, 0.92) > rename augmentation (B, 0.77) on token-diversity, and A
keeps the standard floor at 1.000 with **no new data**. B is the safer, more
conventional fix (pure verified data, raw model). **Adopt A** (with the raw v30
fallback union that makes it strictly ≥ v30); keep B as the low-risk alternative.
