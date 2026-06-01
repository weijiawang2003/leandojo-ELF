# V31 — Part 1: Token-Coverage Residual Audit

_`scripts/audit_v31_token_coverage_residuals.py` →
`data/baselines/v31_token_coverage/report.json`. From the v30 residuals + v30 training
patterns + verified corpora. No Lean run._

## Headline: **all 13 residuals are surface-token coverage, not shape/API gaps**

| classification | count |
|---|---:|
| `projection_token_OOD` | **10** |
| `identifier_surface_OOD` | **3** |
| `lemma_namespace_OOD` | 0 |
| `api_arity` | 0 |
| `true_missing_shape` | 0 |
| **surface-token-fixable** | **13 / 13** |

For **every** residual, the proof's identifier-free **pattern is already present in the
family's training rows** — only the specific identifier surface differs. This directly
answers **RQ3: the remaining ~15% projection-direction failure is raw identifier
memorization (surface-token OOD), not a true API or proof-shape gap.**

## The missing identifiers

| theorem | family | needs | missing from train |
|---|---|---|---|
| `v29_set_mem_inter_left_3` / `_right_3` | set::mem_inter_proj | `exact hw.1` / `.2` | **`hw`** |
| `v29_set_mem_union_of_left_3` / `_right_3` | set::mem_union_intro | `exact Or.inl hw` | **`hw`** |
| `v29_fs_mem_union_right_3` | finset::mem_union_intro | `Finset.mem_union.mpr (Or.inr hw)` | **`hw`, `u`** |
| `v30_set_mem_inter_left_mgh` / `_right_mgh` | set::mem_inter_proj | `exact hm.1` / `.2` | **`hm`** |
| `v30_fs_mem_inter_right_mgh` | finset::mem_inter_proj | `(Finset.mem_inter.mp hm).2` | **`hm`** |
| `v30_set_mem_union_right_mgh` | set::mem_union_intro | `exact Or.inr g` | **`g`** |
| `v29_ord_min_le_left_2` | order::min_max | `min_le_left p q` | **`p`, `q`** |
| `v30_set_union_subset_rsw` / `v28_ord_le_max_right_1` / `v30_set_empty_inter_subset` | (mixed) | named lemma | (identifier-surface) |

The held-out `_3` and `_mgh` members use element/hypothesis tokens (`hw`, `hm`, `g`)
that no training sibling of their family carries. The model has learned `exact ID.1`
for `ID ∈ {h, hx, hy, hz, hk, he}` but never `hw`/`hm`, so it cannot bind the
projection to the unseen identifier.

## Implication for v31

Two routes can fix surface-token OOD, both compatible with the refined density law:

- **(A) input-side canonicalization** — map every local identifier to a stable
  canonical name (`hw`→`c4`), so the model sees **one** form regardless of surface and
  is identifier-invariant. Principled but must avoid v19's placeholder failure (Part 2).
- **(B) verified rename augmentation** — add verified projection siblings that *use*
  the missing identifiers (`hw`, `hm`, `g`, …), bringing them in-distribution (Part 4).
  This is the direct data fix and is guaranteed safe (verified rows).

Because the audit shows the gap is **purely surface tokens** (0 true-missing-shape),
both should work; v31 implements and compares them, with (A) guarded so it can only add
coverage on top of the raw v30 pool. No `state_after`; expected proofs are references,
never predictions.
