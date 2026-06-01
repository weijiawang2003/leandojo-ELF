# V30 — Part 10/11: Remaining Failures + v24 Cleanup Decision

_`scripts/analyze_v30_remaining_failures.py` →
`data/baselines/v30_remaining_failures/report.json`. No Lean run._

## Remaining failures of `v30_general_targeted`

Over the fresh + density holdouts (v28 + v29 + v30 + targeted-family): **13 residuals**.

| failure class | count |
|---|---:|
| api_syntax | 8 |
| lemma_vocabulary | 5 |
| multi_step_planning | **0** |
| architecture | 0 |
| proof_state_supervision | 0 |

By bench: `v29_family_density` 6 (the `_3` token residuals), `v30_targeted_family` 4,
`v30_holdout` 2, `v28_holdout` 1.

The count is **higher than v29's 8 not because v30 is worse** — on the shared
v25–v29 benchmarks v30 is strictly ≥ v29 (v25 recovered to 1.000, nothing regressed).
The extra residuals come from the **new, harder holdouts** v30 added (the fresh v30
holdout and the targeted-family holdout), plus the persistent `_3` token residuals.

## Classification — still data/coverage-bound

All 13 are **single-tactic** goals whose correct proof verifies; **0 multi-step, 0
architecture, 0 proof-state**. The dominant classes are:

- **token-coverage** (`_3` projection members): the held-out element/hyp tokens
  (`w`,`hw`) appear in no training sibling — pure augmentation can't cover them;
- **API/namespace** (`empty_subset` in Finset at density 0, a couple of `le_refl`
  variants): would be fixed by the same count-repair, just not yet applied to those.

## Is LeanDojo next-state relevant now? **Still no.**

`leandojo_next_state_relevant: false`. Zero multi-step / proof-state residuals. The
wall is single-tactic surface-token coverage — the wrong place for next-state
supervision. Hold LeanDojo until the projection token-coverage ceiling is either
widened or accepted as a small-model limit.

## Optional v24 broad-core cleanup — **audited, not retrained**

The protected v24 model is **never retrained** (constraint). Audit found **3 old core
residuals** (`and_assoc_one` / `or_inr` / `or_elim_to_common`-style), orthogonal to the
Mathlib tier. **Recommendation:** repair them the *same way* v30 just repaired the
Mathlib tier — a small **core-density sibling corpus** + a **core specialist** routed
to, never edits to the protected v24 model. Out of v30 scope (the routed system
already preserves broad-core bit-for-bit by sending all core theorems to v24).
