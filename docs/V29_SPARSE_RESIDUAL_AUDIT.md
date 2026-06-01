# V29 — Part 2: Sparse-Family / Residual Audit

_`scripts/audit_v29_sparse_residuals.py` →
`data/baselines/v29_sparse_residual/{report.json,residuals.jsonl}`.
Joins the Part-1 density census with the v28 specialist-eval predictions + verified
corpora. **No Lean run.** Expected proofs are Lean-verified references, never predictions._

## What counts as a residual

"The model" = the **current v28 system** (`v28_general` / `set_order_heavy` /
`finset_specialist` on the theorem-holdout benches; the transfer models on their
category-holdout benches). A theorem is a residual iff **no applicable v28 model**
gets a verifying candidate into the top-10. **40 residuals**, split by regime:

| regime | n | meaning |
|---|---:|---|
| `theorem_holdout` | **5** | family intact in training, still missed — the genuine residuals |
| `whole_category_transfer` | **35** | entire category removed from training (effective density 0) — the density-0 control |

The 35 transfer-regime residuals are not bugs; they are the density-0 anchor of the
Part-1 law (a model that never trained on Set lemmas cannot emit `Set.union_subset`).
v29's RQ3 (can transfer improve with more sibling families?) targets them; the **5
genuine residuals** are the priority densification targets.

## The 5 genuine theorem-holdout residuals (sparse-sibling underfit, in the act)

Every one lands in the right neighbourhood and **mis-binds** — the v28-memory
diagnosis, confirmed:

| theorem | family | dens | gap class | expected | model's top beams (wrong) |
|---|---|---:|---|---|---|
| `v28_fs_mem_inter_left_0` | finset::mem_inter_proj | 4 | **wrong_projection_direction** | `exact (Finset.mem_inter.mp h).1` | `exact h.2`, `exact (Or.inl h` — emits the **opposite** projector |
| `v28_fun_comp_assoc3` (`p,q,r`) | function::comp_assoc | 1 | renamed_identifier | `rfl` | `exact fun _ => h2`, `intro x _; exact hx` — hallucinates order hyps |
| `v26_fun_comp_assoc2` (`f,g,h`) | function::comp_assoc | 1 | namespace/API | `rfl` / `funext x; rfl` | `exact Set.id_comp h`, `Set.comp_id h` — wrong **namespace** |
| `v28_ord_antisymm` | order::antisymm | 1 | namespace/API | `exact le_antisymm h1 h2` | `exact Nat.trans h2`, `Nat.le_of_eq a b` — **Nat-locked**, not polymorphic |
| `v28_set_union_comm_subset_1` | set::union_comm | 4 | namespace/API | `intro x hx; exact hx.elim Or.inr Or.inl` | `Set.subset_union_right`, `Or.inr hx` — misses the **swap** |

Read off the cause in each case:

- **Projection direction** (`mem_inter_left` → emits `.2`): with only 2 same-direction
  siblings in train the model cannot tell `.1` from `.2`. Densify both directions, all
  var-sets.
- **`comp_assoc` (1 sibling each name set)**: the model has never seen `(r∘q)∘p` close
  by `rfl`; it borrows hyps/namespaces from other families. Densify `f,g,h` / `p,q,r` /
  `φ,ψ,χ` with `rfl`/`funext x; rfl`/`ext x; rfl`.
- **Polymorphic `antisymm` (1 sibling)**: the model defaults to `Nat.*` because order
  was historically Nat-heavy. Densify `[PartialOrder]` antisymm across `(a,b)`/`(x,y)`.
- **`union_comm` swap**: emits the non-swapped subset lemma. Densify the commutativity
  swap shape with `hx.elim Or.inr Or.inl` and `ext`/`simp` variants.

## Gap-class distribution

All 40: `namespace_api_gap` 21, `wrong_projection_direction` 18, `sibling_density` 1.
Theorem-holdout only (the 5): `namespace_api_gap` 4, `wrong_projection_direction` 1.

**Crucially, none of the 5 genuine residuals is a `multi_step_gap`.** Every one is
single-tactic-provable and fails purely on identifier/shape binding — i.e.
**data-coverage-bound, not planning-bound.** This is the green light for v29's
density-scaling thesis and the red light (still) for LeanDojo next-state supervision.

## 27 weak families (held-out pass@10 < 1 somewhere) → v29 densify list

Driven into Part 3 with concrete `(var-set × proof-head)` menus, target ≥ 8 siblings:

- **Set**: `mem_inter_proj`, `inter_subset`, `subset_union`, `union_subset`,
  `subset_inter`, `mem_union_intro`, `mem_iff`, `inter_comm`, `union_comm`.
- **Finset**: `mem_inter_proj`, `inter_subset`, `subset_union`, `mem_iff`,
  `mem_union_intro`, `union_comm`, `inter_comm`.
- **order**: `antisymm`, `le_trans` (polymorphic), `le_total`, `le_of_eq`.
- **function**: `comp_assoc`, `comp_id`.
- **nat / list / logic**: name-variant vocabulary (`add_assoc` rev, `contrapose`,
  `and_symm`) — low priority (already ~1.0 held-out).

Honesty: residual records read from existing eval artifacts; expected proofs are
Lean-verified references used only to label the gap, never fed to a model; no
`state_after`.
