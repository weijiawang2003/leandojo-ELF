# V29 — Part 1: Sibling-Density Audit

_`scripts/audit_v29_family_density.py` → `data/baselines/v29_family_density/{report.json,families.jsonl}`.
Reads the v26/v27/v28 Mathlib verified corpora + the v28 specialist eval. **No Lean run.**_

## Question

v28 showed that improvement on fresh held-outs is driven by **within-family sibling
density**, not generic category transfer. v29 asks it quantitatively: **does the
number of training siblings a family has predict held-out success?**

## Method

- **Family** = the corpus `theorem_family` where present (v27/v28); for the older
  v25/v26 rows that predate the field, a stem derived from the theorem name
  (version prefix + trailing index stripped), namespaced by category. 181 families.
- **Effective training density** of a held-out evaluation = the number of distinct
  sibling theorems of that family **actually present in the training set of the
  model that evaluated it** (excludes the held-out theorem). This is the honest
  signal: theorem-holdout cells keep the family, while whole-category transfer cells
  (`category_holdout_*`) remove the entire category, dropping in-category density to
  0. We bin **507 (theorem, model) evaluation points** by this number.

## The density law (headline)

| effective siblings in train | held-out evaluations | pass@10 |
|---:|---:|---:|
| **0** | 395 | **0.684** |
| **1–3** | 76 | **0.829** |
| **4–6** | 36 | **0.944** |
| 7–10 | 0 | — |

Monotone. Binary gate: **density ≥ 1 → pass@10 0.866 (n=112)** vs **density 0 →
0.684 (n=395)**. Pointwise Pearson(eff-density, pass@10) = **+0.17** (modest only
because pass@10 is a 0/1 outcome that saturates by ~4 siblings — the binned curve
and the gate are the faithful view). **Answer to RQ1: yes — within-family sibling
density predicts held-out success, and the marginal value of siblings saturates
around 4–6.**

## Density by category (avg family density ↔ held-out pass@10)

| category | families | avg family density | held-out n | held-out pass@10 |
|---|---:|---:|---:|---:|
| order | 15 | **3.13** | 29 | 0.828 |
| finset | 9 | 2.67 | 18 | 0.444 |
| set | 56 | 1.84 | 43 | 0.488 |
| function | 9 | 1.78 | 2 | 0.50 |
| logic | 25 | 1.32 | 5 | 1.00 |
| nat | 29 | 1.31 | 8 | 1.00 |
| list | 22 | 1.14 | 5 | 1.00 |

The two weak categories (finset 0.444, set 0.488) are weak **because their held-out
pool is dominated by whole-category-transfer evaluations** (effective density 0 in
those cells), not because the categories are intrinsically hard — order, with the
highest in-corpus family density, has the best held-out rate among the structured
categories. This is the density law restated per category.

## Densest families (already reliable — the model of what "enough siblings" looks like)

| family | category | siblings | proof heads | α-skeletons | held-out pass@10 |
|---|---|---:|---:|---:|---:|
| `min_max` | order | 10 | 3 | 4 | 1.00 |
| `nat_le` | order | 10 | 3 | 4 | 0.875 |
| `lattice_inf_sup` | order | 8 | 1 | 2 | 0.833 |
| `subset_union` | set | 8 | 2 | 1 | 0.40 |
| `mem_iff` | set | 7 | 4 | 2 | 0.60 |

(`subset_union`/`mem_iff` look dense but most of their held-out members come from
the Set whole-category transfer cell — density 0 in that condition — which is why
they still miss. Same family, two regimes.)

## Sparse / failing families → the v29 densify list

163 families have ≤ 3 siblings. The ones with **held-out failures** are the v29
targets (they coincide exactly with the families the brief names):

| family | category | siblings | held-out pass@10 | gap class |
|---|---|---:|---:|---|
| `mem_inter_proj` | finset | 4 | **0.00** | projection direction |
| `mem_inter_proj` | set | 6 | 0.25 | projection direction |
| `subset_inter` | set | 4 | **0.00** | union/inter subset |
| `inter_subset` | finset | 4 | 0.33 | union/inter subset |
| `inter_subset` | set | 6 | 0.25 | union/inter subset |
| `subset_union` | finset | 4 | 0.33 | union/inter subset |
| `union_subset` | set | 3 | 0.33 | union/inter subset |
| `mem_iff` | finset | 4 | 0.33 | membership iff |
| `inter_comm` | set | 2 | **0.00** | commutativity |
| `union_comm` | finset | 1 | **0.00** | commutativity |
| `comp_assoc` | function | 1 | **0.00** | renamed comp_assoc |
| `antisymm` | order | 1 | **0.00** | le_antisymm |
| `le_total` | order | 2 | **0.00** | order total |

## Categories where density helps most

Set and Finset projection/membership/subset families dominate the failure list and
sit at 1–4 siblings — exactly the families v28 left thin. Order is already dense
(avg 3.13) and mostly reliable; function/list/nat are reliable at low density
because their shapes are nearly canonical (`rfl`/`simp`/`omega` close them
regardless of identifiers). So the highest-leverage densification is **Set/Finset
union·inter·projection·membership** and the **single-sibling order/function**
residuals (`antisymm`, `le_total`, `comp_assoc`).

## v29 densify plan (drives Part 3)

Bring every failing family to ≥ 6–8 verified siblings with varied identifiers
(`s,t,u` / `a,b,c` / `p,q,r` and element/hypothesis renames) **and** varied proof
heads (named lemma · `intro;exact` · `simp` · `rintro`), since the density law's
gain comes from siblings the model can bind a stable shape from. No category
balancing (harmful in v27/v28). Honesty: families measured from Lean-verified rows
only; expected proofs are references, never predictions; no `state_after`.
