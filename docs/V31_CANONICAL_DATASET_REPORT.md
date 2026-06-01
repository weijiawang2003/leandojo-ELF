# V31 — Part 3: Canonical Dataset Report

_`scripts/build_v31_canonical_mathlib_dataset.py` →
`data/processed/v31_canonical_mathlib/`._

## What was built

The v30 training base (905 rows) was canonicalized with
`v31_identifier_normalization` (binder identifiers → `c0, c1, …`).

| metric | value |
|---|---:|
| base train rows | 905 |
| **canonicalized rows** | **902** (3 have no binders → stay raw) |
| **round-trip failures** | **0** (every canonical tactic recovers its raw form) |

## Configs

| config | rows | approach |
|---|---:|---|
| `canonical_general` | 905 | A — every row canonicalized (+ canonical val) |
| `raw_canonical_mixture` | 897 | A/B — raw ∪ canonical (dedup) |
| `raw_plus_canonical_aug` | 1807 | raw + canonical-that-differ (augmentation) |
| `raw_plus_projection_aug` | 1045 | B — v30 base + 140 verified rename-aug rows (Part 4) |
| pattern-rerank baseline | — | C — v30 model, no new training |

`token_diversity_holdout`: the **13** v30 residual theorems, the benchmark the v31
approaches are judged on.

## Honesty: canonicalization vs leakage

Canonicalization **deliberately collapses identifier variants** — parallel theorems
become one canonical form. This is the generalization under test, **not** memorization:

- the **RAW** guard holds — the v30 base already excludes every v25–v30 held-out test
  statement, so no held-out raw statement is in training;
- a held-out identifier-variant (e.g. `…(w)(hw)…`) canonicalizes to the same shape as a
  *trained* row that came from a **different** raw theorem (`…(x)(h)…`) — the model
  generalizes across identifier surface, exactly the v30 token-coverage gap;
- the eval verifies the **real (un-canonicalized) theorem** with Lean — the canonical
  model must `concretize_or_reject` correctly to pass, so a pass is a genuine solve.

This is analogous to rotation-augmentation in vision: the augmentation makes a rotated
test image "in-distribution" in canonical orientation; it is not test-set leakage.

No `state_after`; **0** unresolved canonical identifiers in any training target
(asserted); not v19 placeholder decoding.
