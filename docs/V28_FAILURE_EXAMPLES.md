# V28 Failure Examples

_Concrete remaining failures of the best general model (`v28_general`) on the fresh
v28 holdout, with the model's top beams vs the Lean-verified expected proof. Source:
`data/baselines/v28_specialist_eval/v28_general__v28_holdout/abstract/predictions.jsonl`.
Expected proofs are Lean-verified reference targets, never fed to the model._

The v27 residuals (`mem_inter_iff`, `union_subset`) are **solved** in v28 — these are
the *new*, deeper residuals (4 of 30). All four are **single-tactic provable** and
share one cause: **a single-sibling or near-miss-binding shape** — exactly the
coverage lever v29 should pull.

## 1. Finset projection — `v28_fs_mem_inter_left_0`

`(α : Type) [DecidableEq α] (s t : Finset α) (x : α) (h : x ∈ s ∩ t) : x ∈ s`

* **expected:** `exact (Finset.mem_inter.mp h).1` / `exact Finset.mem_of_mem_inter_left h`
* **model top beams:** `simp [h]`, `exact Finset.symm h`, `exact (Finset.inl h`,
  `exact Finset.mem_of_mem_inter_right h`
* **why it fails:** the model knows the `Finset.mem_of_mem_inter_*` family but picks
  **`_right` instead of `_left`**, or hallucinates `Finset.symm`/`Finset.inl`. The
  left/right projection direction is under-determined with too few Finset siblings.
* **bucket:** proof_shape (API/arity) → fix with more Finset projection siblings.

## 2. Function composition assoc under renamed binders — `v28_fun_comp_assoc3`

`(α β γ δ) (p : α → β) (q : β → γ) (r : γ → δ) : (r ∘ q) ∘ p = r ∘ (q ∘ p)`

* **expected:** `rfl` / `funext x; rfl`
* **model top beams:** `intro x _; rfl`, `intro x; rfl`, `intro x _; simp`
* **why it fails:** the goal is an equality of functions — `intro` (`introN`) fails;
  it needs `funext` or bare `rfl`. The model learned `intro x` from Set membership
  goals and over-applies it. The `(p,q,r)` renaming is novel (the `(f,g,h)` sibling
  was the only one it had).
* **bucket:** syntax/parse (wrong opener) → fix with more renamed `comp_assoc`/`rfl`
  siblings.

## 3. PartialOrder antisymmetry — `v28_ord_antisymm`

`(α : Type) [PartialOrder α] (a b : α) (h1 : a ≤ b) (h2 : b ≤ a) : a = b`

* **expected:** `exact le_antisymm h1 h2`
* **model top beams:** `simp`, `exact Nat.min_le_left a b`, `exact Nat.le_of_eq a b`,
  `exact Nat.le_max_right a b`
* **why it fails:** with only **one** `antisymm` sibling in the corpus, the decoder
  falls back to the dominant Nat order vocabulary (`Nat.min_le_left`, …) → application
  type mismatch. It has never seen enough `le_antisymm` to bind it.
* **bucket:** proof_shape (API/arity) → fix with more `le_antisymm` siblings.

## 4. Set union commutativity subset (renamed) — `v28_set_union_comm_subset_1`

`(α : Type) (a b : Set α) : a ∪ b ⊆ b ∪ a`

* **expected:** `intro x hx; exact hx.elim Or.inr Or.inl`
* **model top beams:** `intro x hx; exact Or.inr hx`, `intro x hx; exact Or.inl hx`,
  `intro x hx; exact hx.elim Or.` (truncated)
* **why it fails:** the model gets the `intro x hx` opener right and reaches for
  `Or.inr/Or.inl` and `hx.elim`, but mis-assembles the `elim` term (it emits a
  membership proof for one side instead of the case split). Right neighbourhood,
  wrong binding — more `union_comm`/`elim` siblings would disambiguate.
* **bucket:** insufficient_shape_diversity → fix with more `hx.elim` siblings.

## Pattern

Every residual is the same signature seen in the Part-1 audit: **the model lands in
the right neighbourhood but mis-binds the exact identifier/projection/opener** when a
shape has few siblings. None require multi-step planning; none are impossible. This
is a **data/coverage** limit, not architecture or proof-state supervision — v29's
lever is more verified single-tactic siblings for these single-sibling shapes
(Finset projection direction, `le_antisymm`, renamed `comp_assoc`, `union` `elim`).
