# V29 — Part 3: Sibling-Density Corpus Report

_`scripts/generate_v29_mathlib_density_corpus.py` →
`data/{seeds/v29_mathlib_density_seeds,manual/v29_mathlib_density_candidates,
traces/v29_mathlib_density_{verified,failed}}.jsonl` +
`data/processed/v29_mathlib_specialist/density_{train_rows,summary}.json`.
Every candidate verified by `TrustedMathlibVerifier` (sentinel+confirm+rescue, sound
& complete) against real external `import Mathlib`._

## Design: density, not breadth

v28's lesson was that within-family sibling density drives held-out success. v29
therefore scales **density directly**: each weak/residual family (Part 2) is crossed
over a **var-set menu** (`s,t,u` / `a,b,c` / `p,q,r` / `u,v,w` / `m,n,k` …, element
`x/y/z/w`, hypothesis `h/hy/hz/hw`) and a **proof-head menu** (named lemma ·
`intro;exact` · `simp` · `rintro` · `funext`), so the small seq2seq sees one *shape*
under many surface tokens and stops mis-binding the identifier/projection.

This is honest alpha-renamed augmentation: each sibling is a **distinct true theorem,
independently Lean-verified**. Manual candidates are corpus targets verified by Lean,
never fed to a model as predictions.

## Counts

| metric | value |
|---|---:|
| theorem statements | **229** |
| candidate rows proposed | 589 |
| **verified rows** | **492** |
| Lean-rejected | **0** |
| **true coverage gaps** (theorem with 0 verifying candidates) | **0** |
| dropped by guards (v18 triple / v25–v28 benchmark) | 2 / 95 |
| theorems stripped to 0 by guards (NOT gaps) | 36 |
| Lean wall (generation) | 80.3 s over 18 invocations |

Verified rows by category: **set 143, finset 114, order 72, function 61, nat 44,
logic 40, list 18.** Proof-head mix: `exact` 258, `intro` 62, `simp` 49, `rfl` 29,
`funext` 15, `ext` 13, `omega` 12, `tauto` 12 — head diversity is itself part of the
density (the model must learn the family closes by several routes).

The 95 benchmark-guard drops are siblings whose `(statement, state)` coincides with a
v25/v26/v27/v28 held-out test (e.g. the `(s,t,u)`/`(f,g,h)`/`(a,b)` var-sets that v28
already used as benchmarks). Dropping them keeps every established benchmark clean;
they are **not** coverage gaps — the family is still densely covered by its other,
novel siblings.

## Families densified (verified rows)

| family | category(ies) | siblings | verified rows |
|---|---|---:|---:|
| `mem_union_intro` | set+finset | 16 | 42 |
| `mem_iff` | set+finset | 16 | 41 |
| `subset_union` | set+finset | 16 | 35 |
| `mem_inter_proj` | set+finset | 16 | 33 |
| `comp_id` | function | 8 | 32 |
| `inter_subset` | set+finset | 16 | 32 |
| `le_of_eq` | order | 10 | 30 |
| `comp_assoc` | function | 9 | 21 |
| `union_comm` / `inter_comm` | set+finset | 7 / 7 | 15 / 12 |
| `subset_inter` / `union_subset` | set+finset | 7 / 7 | 14 / 12 |
| `antisymm` | order | 9 | (le_antisymm) |

The exact v28 residual families — `mem_inter_proj` (projection direction),
`comp_assoc` (renamed), `antisymm` (polymorphic `le_antisymm`), `union_subset` — are
now each carried by 7–16 verified siblings with both directions and multiple proof
heads, directly attacking the sparse-sibling underfit Part 2 diagnosed.

## Honesty

Real `import Mathlib` typecheck (no mock); `TrustedMathlibVerifier` only
(`confirm=False` raises); no `state_after` read or produced; manual targets never used
as predictions; Mathlib real and external (`~/code/mini_elf_mathlib_probe`, pinned
v4.30.0); v18 + v25/v26/v27/v28 leakage guards enforced; all names `v29_*`.
