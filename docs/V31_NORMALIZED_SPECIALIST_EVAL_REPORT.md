# V31 — Part 6: Normalized Specialist Evaluation Report

_`scripts/evaluate_v31_normalized_specialists.py` →
`data/baselines/v31_normalized_eval/`. 4 models × 7 benches; **3374 unique pairs**
verified in one shared TrustedMathlibVerifier pass (55 invocations, 242 s). The
canonical/mixture pools are **canonicalize → decode → concretize-or-reject → union with
the raw v30 pool** (raw fallback), so they can only add coverage._

## Primary table — pass@10 (best rerank config per cell)

| config | v25 | v26 | v27 | v28 | v29 | tgt-family | **token-div** | residuals | unresolved | broad-core |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| v30_general_targeted | 1.00 | 1.00 | 1.00 | 0.97 | 1.00 | 0.60 | **0.00** | 13 | — | preserved |
| v31_raw_plus_projection_aug (B) | 1.00 | 1.00 | 1.00 | **1.00** | 1.00 | 0.70 | **0.77** | ~4 | — | preserved |
| **v31_canonical_general (A)** | 1.00 | 1.00 | 1.00 | **1.00** | 1.00 | **1.00** | **0.92** | **1** | **0** | preserved |
| v31_raw_canonical_mixture | 1.00 | 0.95 | 1.00 | 0.97 | 1.00 | 0.90 | 0.92 | ~2 | 10 (dropped) | preserved |

## Against the v31 targets

| target | result |
|---|---|
| preserve v25 = 1.000 | ✅ 1.000 |
| preserve v26 / v27 / v29 = 1.000 | ✅ 1.000 (mixture dips v26 to 0.955) |
| preserve v28 ≥ 0.967 | ✅ **1.000** (canonical & B lift it) |
| improve `_3` / token-diversity residuals | ✅ **0.00 → 0.92** (A), 0.77 (B) |
| reduce residual count below 13 | ✅ **13 → 1** (A) |
| avoid `unresolved_placeholder` failures | ✅ **0 unresolved** (canonical_general) |
| 0 trusted-verifier gold mismatches | ✅ maintained |

## The v19 failure mode did NOT recur

On the token-diversity holdout `v31_canonical_general` generated 130 canonical
candidates with **0 unresolved-rejected**, and the raw v30 fallback added 123 more.
Because canonical names are valid Lean identifiers, the parse is clean and there are no
unmapped slots; any that did occur (10 in the *mixture* model) were **dropped before
the verifier**. This is the precise opposite of v19, where placeholders flooded the
verifier with `unresolved_placeholder` and pass@k collapsed.

## Why Approach C (pattern-rerank) is not enough

Approach C reorders the existing pool but **cannot add an absent candidate**; the
residuals are beam-*absence*, so reranking alone cannot fix them (it can only help
pass@1/MRR within ≤10). Only A (changes which candidates are generated, via canonical
decoding) or B (adds training data) can lift pass@10 — confirmed by the table.

## Recommended config

**`v31_canonical_general`** — token-diversity 0.92, every standard held-out 1.000
(v28 lifted to 1.000), targeted-family 1.000, **1 residual**, **0 unresolved**, and it
adds **zero new theorems** (the v30 base re-encoded). `raw_plus_projection_aug` (B) is
the simpler raw-model alternative (0.77, +140 verified rows).

Real `import Mathlib`; TrustedMathlibVerifier only; no `state_after`; no manual oracle;
not v19 placeholders; v24 untouched.
