# Mini-ELF v27 — Expanded Mathlib Category Gap Audit (Part 3)

Source: `scripts/audit_v27_mathlib_category_gaps.py` →
`data/baselines/v27_category_gaps/report.json`. Derived from the v26 verified
corpus (237 rows), the v26 Lean-rejected corpus, and the v26/widened specialist
eval predictions on the two held-out benchmarks (all real Lean verdicts).

## Where v26 stands (specialist best-config pass@10)

| Model @ bench | overall | **Set** |
|---------------|---------|---------|
| v26_base @ v25-heldout | 0.929 | 1.00 (n=2) |
| v26_base @ v26-holdout | 0.909 | **0.50** (n=4) |
| v26_widened @ v25-heldout | 0.929 | 1.00 (n=2) |
| v26_widened @ v26-holdout | 0.909 | **0.75** (n=4) |

Every non-Set category is at pass@10 = 1.00 on the held-out benchmarks. **Set is
the one category still below ceiling**, and the +Set widening (base→widened) lifted
Set 0.50→0.75 on v26-holdout — strong evidence Set is **data-bound**, not
architecture-bound.

## Per-category findings

### Set — PRIMARY GAP (covered: 17 theorems / 54 rows)
- Covered proof shapes: `exact`(32) / `intro`(13) / `simp`(5); lemma vocabulary
  already includes `Set.inter_subset_left/right`, `Set.subset_union_left/right`,
  `Set.Subset.refl`, `Set.subset_univ`, `Set.mem_inter_iff`, `Set.mem_union_left`,
  `Set.mem_singleton(_iff)`, `Or.inl/inr`.
- **Residual theorems the base specialist misses** (both `type_mismatch`):
  - `set_inter_comm_subset` : `s ∩ t ⊆ t ∩ s` (needs `intro x h; exact ⟨h.2, h.1⟩`)
  - `set_mem_inter_left` : `x ∈ s ∩ t → x ∈ s` (needs `exact h.1` / membership destructuring)
  - widened recovers `inter_comm_subset` (Set 0.75) but membership-destructuring
    shapes are still thin.
- Missing shapes to add: **membership ↔** (`mem_inter_iff`, `mem_union`,
  `mem_singleton_iff`) used both directions; **inter/union commutativity &
  associativity as subsets**; **diff/compl subset**; **`x ∈ s → x ∈ s ∪ t`** and
  the symmetric `mem_union_right`; **`subset_trans`**; **`u ⊆ s → u ⊆ t → u ⊆ s ∩ t`**.
- Proposed expansion: the full Part-4 Set block (≈12 statements × multiple verified
  tactic forms: `intro x hx; exact …`, `exact ⟨…⟩`, `Or.inl/inr`, `simp only
  [Set.mem_*]`).

### order / ≤ (lives under category `nat`, `expected_skill="order"`)
- Covered: `le_refl`, `le_succ`, `zero_le`, `le_add_right/left`, `le_trans`,
  `lt_succ_self`, `le_of_eq`, `min_le_left`, `le_max_left`, `succ_pos` (via `omega`
  / `exact Nat.*` / `simp`).
- No held-out order residual was observed, but the held-out order sample is tiny.
  Proposed expansion: `n ≤ m → n ≤ m+1`, `succ_le_succ`, `le_of_lt`, transitivity
  chains, `min/max` both sides, so order pass@10 is **documented on a larger
  sample** (Part 4 builds a dedicated order block + an order category-holdout).

### nat arithmetic / simp (covered: 20 theorems / 66 rows)
- Residual: `nat_add_assoc` : `a + b + c = a + (b + c)` (`type_mismatch` — the model
  proposed a wrongly-shaped `exact`). Associativity is under-represented.
- Lean-rejected (API/arity): `exact Nat.add_sub_cancel` (wrong implicit/explicit
  arity → type mismatch). Correct form is `omega` / `simp` / `Nat.add_sub_cancel`
  with the right arguments.
- Proposed expansion: associativity **both directions**, `two_mul`, `succ_eq`,
  `add_sub_cancel` in the arity-free / `omega` form, commutativity variants.

### list (covered: 12 theorems / 25 rows)
- No held-out residual, but **6 Lean-rejected candidates — all API/arity mistakes**:
  `exact List.length_cons x xs`, `…length_append xs ys`, `…length_reverse xs`,
  `…mem_cons_self x xs`, `exact (List.map_map g f xs)` → all *"Function expected"*
  (these Mathlib lemmas take **implicit** args; passing them explicitly is wrong),
  and `left; rfl` → *"No goals"*. These were correctly dropped (kept as failed).
- Proposed expansion: prefer **`simp` / `rfl`** and the **arity-free lemma form**
  (`exact List.length_cons`, `exact List.map_map`) so the model sees the *correct*
  API, plus `append_assoc`, `reverse_reverse`, `map_map`, `mem_append`.

### logic (covered: 15 theorems / 49 rows) — no residual, no rejects
- Strong coverage (`exact`, `tauto`, `Or/And.symm`, `Iff.rfl`). Proposed expansion
  adds diversity only: contrapositive, De Morgan, curry, `em`, `not_not`.

### bool_option (covered: 10 theorems / 29 rows) — no residual, no rejects
- `cases b <;> simp/rfl`, `Bool.*`, dichotomy, `Option.map id`. Expansion is
  diversity: `or/and/not` identities, `option getD/map`, `b = true ∨ b = false`.

### function (covered: 5 theorems / 14 rows)
- Residual: `fun_comp_assoc2` : `(h ∘ g) ∘ f = h ∘ (g ∘ f)` (eval class `other`;
  needs `rfl` / `funext x; rfl`). One reject: a bare `simp` *"made no progress"*.
- Proposed expansion: `comp id` both sides via `funext`, `comp_assoc`, `const`
  apply, `id` apply — all via `rfl`/`funext`/`simp` confirmed by Lean.

## Which categories are data-bound after v26?

- **Set: data-bound** — widening lifted held-out Set 0.50→0.75 with no other
  regression; the residuals are specific membership/commutativity shapes absent
  from training. v27 targets this hardest.
- **order: under-measured** — coverage exists but the held-out order sample is too
  small to state a confident number; v27 enlarges it and adds an order holdout.
- **nat: one associativity shape** missing; cheap to close.
- **list / function: API-form** issues (arity-free lemmas, `funext`) — fixable by
  feeding the correct shapes.
- **logic / bool_option: at ceiling** — expand only for diversity, not coverage.

## v27 corpus expansion plan (feeds Part 4)

Priority order by expected marginal value: **Set ≫ order > nat ≈ list/function >
logic/bool_option**. Targets: 150–300 *verified* candidate rows over 60–120
statements, Set-heavy, every candidate Lean-checked by the **trusted** verifier,
failed candidates retained for taxonomy. No state_after, no manual oracle as
predictions.
