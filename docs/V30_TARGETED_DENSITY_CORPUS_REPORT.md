# V30 — Part 3: Targeted Density-Repair Corpus Report

_`scripts/generate_v30_targeted_density_corpus.py` →
`data/{seeds/v30_targeted_density_seeds, manual/v30_targeted_density_candidates,
traces/v30_targeted_density_{verified,failed}}.jsonl` +
`data/processed/v30_mathlib_specialist/targeted_{train_rows,summary}.json`.
`TrustedMathlibVerifier` only._

## Design: surgical, not broad

v30 uses the v29 density law (reliable at ~4–6 siblings) for a **targeted repair** of
the families Part 1/2 flagged — **no broad random expansion**. Each family is brought
to ~4–6 training siblings; the token-diversity families get **fresh element/hyp/set
tokens** (`w/hw`, `e/he`, `k/hk`, sets `u,v`/`c,d`/`g,h`) so the projection shape
generalises to identifiers the model never saw.

## Counts

| metric | value |
|---|---:|
| theorem statements | **69** |
| candidate rows proposed | 176 |
| **verified rows** | **155** |
| Lean-rejected | 8 |
| **coverage gaps** | **0** |
| dropped by guards (v18 / v25–v29 benchmark) | 0 / 13 |
| Lean wall (generation) | ~55 s |

The 8 rejects are all `exact (Set.mem_inter_iff.mp h).1` — that dotted form does not
elaborate as projection in Lean 4 (it parses as an unknown constant
`Set.mem_inter_iff.mp`); the direct `exact h.1` candidate for each of those theorems
**verified**, so **0 coverage gaps**. This is legitimate Lean behaviour, not a bug.

## Theorems added per repaired family

| family | theorems added | prev v29 train density |
|---|---:|---:|
| `mem_inter_proj` (set+finset) | 14 | 5–8 (token gap) |
| `add_assoc` (nat) | 12 | **0** |
| `mem_union_intro` (set+finset) | 11 | 5–9 (token gap) |
| `empty_subset` (set+finset) | 10 | **0** |
| `le_refl` (order) | 8 | 3 |
| `comp_assoc` (function) | 3 | 3 |
| `subset_inter` / `union_subset` (set) | 3 / 3 | 4 / 4 |

The two v25-regression families (`add_assoc`, `empty_subset`) — at v29 density 0 — get
the most repair, directly attacking the beam-absence Part 1 diagnosed.

## Honesty

Real external `import Mathlib`; `TrustedMathlibVerifier` only; no `state_after`;
manual candidates are Lean-verified targets, never predictions; v18 + v25/v26/v27/v28/
**v29** (incl. v29 family-density & low-density holdouts) leakage guards enforced; all
names `v30_*`.
