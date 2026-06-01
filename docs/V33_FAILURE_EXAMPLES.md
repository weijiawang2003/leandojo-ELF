# V33 — Failure Examples

_From the v33 specialist + routed evals. No Lean run._

## Remaining failures — essentially none

On the v33 **specialist** eval benches (`v25`, `v28`, `v29`, `token_diversity`,
`identifier_stress`, `fresh_robustness`), `v33_general_residual` has **0 residuals**
(every theorem solved at pass@10; stress 46/46, fresh 42/42, token-diversity 13/13).

In the broader **routed** tier-C set (244 theorems, which also pulls in the older v32
`fresh_mathlib` micro-holdout), **~2 theorems miss** (per-category: list 0.941,
set 0.987). They are fresh single-tactic *shapes* from the v32 fresh set
(e.g. a `List`/`Set` one-liner whose specific shape has no trained sibling) — a residual
**density** gap, **not** token-coverage, **not** multi-step, **not** API.

## Classification

| class | count (routed 244) |
|---|---:|
| theorem-shape density (fresh) | ~2 |
| token-coverage | 0 |
| vocabulary / API | 0 |
| **multi-step / proof-state** | **0** |
| architecture | 0 |

## LeanDojo relevance — no

**0 multi-step / proof-state failures** anywhere in v33. The ~2 routed misses are
single-tactic fresh shapes that a couple of verified density siblings would close. The
single-tactic Mathlib tier is saturated; LeanDojo next-state supervision is **not**
justified by any current failure and stays deferred until a genuinely multi-step
benchmark exists. Trusted verifier only; no `state_after`; no manual oracle; v24 untouched.
