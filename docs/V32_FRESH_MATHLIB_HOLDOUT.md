# V32 — Part 5: Fresh Mathlib Micro-Holdout

_`scripts/generate_v32_fresh_mathlib_holdout.py` →
`data/seeds/v32_fresh_mathlib_holdout_seeds.jsonl` +
`data/manual/v32_fresh_mathlib_holdout_candidates.jsonl`. EVAL ONLY — never trained._

## Counts

| metric | value |
|---|---:|
| theorems proposed | 35 |
| **solvable, novel (kept)** | **25** |
| verified gold candidates | 50 |
| dropped: leaked (coincided with training) | 9 |
| dropped: gold proof failed | 2 |

By category: set 8, order 6, nat 4, finset 3, list 2, function 1, logic 1.

These are **fresh single-tactic shapes** (e.g. `s ∩ t = t ∩ s`, `a < b → a ≤ b`,
`min a b = min b a`, `1 * n = n`, `[].map f = []`, `p ↔ p`) distinct from the trained
families, statement-level leakage-guarded against every prior corpus. The gold proof
confirms provability; it is never fed to a model.

## Result (Part 4 eval)

All specialists score **0.76–0.80 pass@10** on this set (v32 best at 0.80). Because the
holdout varies the **shape** rather than the identifier, identifier-canonicalization
gives no advantage here — the ~0.20 gap is **shape/density coverage** (axis 1), the
remaining frontier after token coverage (axis 2) is solved. No `state_after`; no manual
oracle as predictions.
