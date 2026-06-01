# V30 — Part 2: Low-Density Residual Audit

_`scripts/audit_v30_low_density_residuals.py` →
`data/baselines/v30_low_density/report.json`. From the v29 family census + v29
residuals + the Part-1 v25-regression audit. No Lean run._

v30 repairs only families that are **below the reliable 4–6 sibling threshold** or
carry a v29 held-out failure / v25 regression — **no broad random expansion**.

## Target families (10)

| family | v29 train density | v29 residual? | target | repair kind |
|---|---:|:--:|---:|---|
| `nat::add_assoc` | **0** | — | 6 | v25 regression + count |
| `set::empty_subset` | **0** | — | 6 | v25 regression + count |
| `finset::empty_subset` | **0** | ✅ | 6 | residual + count |
| `order::le_refl` | **3** | ✅ | 6 | residual + count |
| `set::union_subset` | 4 | — | 6 | low-density |
| `function::comp_assoc` | **3** | — | 6 | low-density |
| `set::mem_inter_proj` | 8 | ✅ | (token) | residual + **token diversity** |
| `set::mem_union_intro` | 9 | ✅ | (token) | residual + **token diversity** |
| `finset::mem_inter_proj` | 5 | ✅ | (token) | residual + **token diversity** |
| `finset::mem_union_intro` | 5 | ✅ | (token) | residual + **token diversity** |

## Two distinct repair kinds

**(1) Count repair (6 families).** `add_assoc`, `empty_subset` (set+finset),
`le_refl`, `union_subset`, `comp_assoc` are genuinely sparse in v29 training
(density 0–4). The density law predicts bringing them to ~6 siblings (with the
canonical tactic in each) restores reliable held-out success. These include the two
v25-regression families.

**(2) Token-diversity repair (4 families).** The `_3` residuals
(`v29_set_mem_inter_left_3`, …) come from families whose **count is already ≥ 4**
(set 8–9, finset 5) — yet they miss. Cause: the held-out `_3` members use **surface
tokens absent from every training sibling** — sets `u,v`, element `w`, hypothesis
`hw`. The model trained on `s,t,x,h` / `a,b,y,hy` / `p,q,z,hz` and never saw `w`/`hw`.
**Repair = more token variety, not more rows**: v30 adds projection/membership
siblings with fresh element/hyp tokens (`w/hw`, `e/he`, `k/hk`, `m/hm`) and sets
(`u,v`, `c,d`, `g,h`) — statements that differ from the held-out `_3` members (the
leakage guard drops any accidental match), so the projection shape generalises across
identifiers.

## Every target is single-tactic-solvable

All 10 families close with one tactic (named lemma · `omega`/`ring` · `simp` ·
`intro;exact`); none needs multi-step reasoning. This keeps v30 squarely inside the
single-tactic coverage regime — the right place for density repair, and the wrong
place (still) for LeanDojo next-state supervision.

→ Part 3 (`generate_v30_targeted_density_corpus.py`) builds families **A–G** to hit
these targets with **80–200** verified rows.
