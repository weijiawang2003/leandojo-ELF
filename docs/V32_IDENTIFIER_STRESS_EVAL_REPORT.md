# V32 — Part 4: Identifier-Stress Eval Report

_`scripts/evaluate_v32_identifier_stress.py` →
`data/baselines/v32_identifier_stress_eval/`. 4 models × 2 benches; **2093 unique
pairs** verified (TrustedMathlibVerifier, 156 s). Canonical models use the v31
canonical-aware pool (canonicalize → decode → concretize-or-reject → union raw v30
fallback)._

## Result — canonicalization GENERALIZES; augmentation does not

**pass@10:**

| model | identifier-stress (46, adversarial) | fresh-Mathlib (25, new shapes) |
|---|---:|---:|
| v30_general_targeted (raw) | **0.261** | 0.760 |
| v31_raw_plus_projection_aug (raw, B) | 0.283 | 0.680 |
| **v31_canonical_general (canonical, A)** | **0.891** | 0.760 |
| **v32_canonical_repaired (canonical)** | **0.891** | **0.800** |

## What this answers (RQ3 / Part-4 question)

> *"Did v31 really solve token coverage, or only the specific v30 residuals?"*

**Canonicalization solved it in general.** On 46 theorems whose identifiers
(`h_mem`, `proof₁`, `hα`, `φ ψ χ`, `A B obj`) the corpus **never** contained, the raw
model gets **0.261** and the **rename-augmentation gets only 0.283** (it merely
memorized the specific identifiers it was fed), while **canonicalization reaches
0.891** — a 3.4× lift, because it makes the model genuinely **identifier-invariant**.
This is the sharpest evidence that Approach A is a real generalization, not a patch.

## The v19 guard under adversarial input

On these adversarial identifiers the canonical model generated 445 candidates with
**38 unresolved-rejected (8.5 %)** — higher than on the standard eval (the Greek /
subscript identifiers occasionally desync the canonical decode) — but **every one was
dropped before the verifier**, and the raw v30 fallback supplied 417 candidates. So
even with 8.5 % unresolved, canonical still hits 0.891 and **no
`unresolved_placeholder` failure reaches a metric** (v32's repair trims it to 25/456).

## Fresh-shape holdout (25 new single-tactic shapes)

All models cluster ~0.76–0.80 (v32 best at 0.80). This bench varies the **shape**, not
the identifier — so canonicalization gives no edge here, and the ~0.20 gap is the
**density / shape-coverage axis** (axis 1), the known remaining frontier, not token
coverage (axis 2, now solved).

Real `import Mathlib`; TrustedMathlibVerifier only; not v19 placeholders; no
`state_after`; v24 untouched.
