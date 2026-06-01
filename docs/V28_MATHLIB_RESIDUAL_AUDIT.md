# V28 Part 1 — Mathlib Residual Audit

_Source: `scripts/audit_v28_mathlib_residuals.py` over the v27 specialist-eval
best-config predictions (no Lean re-run). Output:
`data/baselines/v28_residual_audit/{report.json,residuals.jsonl}`._

## What "residual" means here

A theorem is a **v27 residual** if, under the *best-pass@5 config* of a v27
specialist model, **no** candidate in the model's top-10 beam (+ literal-adapt
compositions) Lean-verifies. The proof exists and verifies — the model simply
never **generates** it. Expected proofs below are Lean-verified reference targets
pulled from the v25/v26/v27 verified corpora; they are **never** fed to a model.

## The 9 distinct residuals

| bench | theorem | cat | statement | expected proof | bucket |
|-------|---------|-----|-----------|----------------|--------|
| v25 | `v25_nat_add_assoc` | nat | `a+b+c = a+(b+c)` | `exact Nat.add_assoc a b c` / `omega` | missing_lemma_vocabulary |
| v26 | `v26_nat_le_trans2` | nat | `a≤b → b≤c → a≤c` | `exact Nat.le_trans h1 h2` / `omega` | wrong_api_arity |
| v26 | `v26_fun_comp_assoc2` | function | `(h∘g)∘f = h∘(g∘f)` | `rfl` / `funext x; rfl` | wrong_api_arity |
| v26 | `v25_set_inter_subset_left` | set | `s∩t ⊆ s` | `exact Set.inter_subset_left` / `intro x h; exact h.1` | insufficient_shape_diversity |
| v26 | `v26_set_inter_comm_subset` | set | `s∩t ⊆ t∩s` | `intro x h; exact ⟨h.2, h.1⟩` | wrong_api_arity |
| v26 | `v26_set_mem_inter_left` | set | `x∈s∩t → x∈s` | `exact h.1` | wrong_api_arity |
| v27 | `v27_nat_add_assoc_rev` | nat | `a+(b+c) = a+b+c` | `omega` / `exact (Nat.add_assoc a b c).symm` | wrong_api_arity |
| v27 | `v27_set_mem_inter_iff` | set | `x∈s∩t ↔ x∈s ∧ x∈t` | `exact Set.mem_inter_iff x s t` / `rfl` | missing_lemma_vocabulary |
| v27 | `v27_set_union_subset` | set | `s⊆u → t⊆u → s∪t ⊆ u` | `exact Set.union_subset h1 h2` | wrong_api_arity |

**Bucket counts:** `wrong_api_arity 6, missing_lemma_vocabulary 2,
insufficient_shape_diversity 1`. **Hardest** (residual in *every* v27 config):
`v26_fun_comp_assoc2`, `v27_set_union_subset`.

## The actual failure mode (what the beams show)

The model is **not** missing the vocabulary wholesale — it has the right *tokens*
but **mis-binds** them. Three recurring signatures:

1. **Hallucinated near-miss identifier.** For `a+b+c=a+(b+c)` the top beam is
   `exact Nat.append_assoc a` (a `List` lemma name welded onto `Nat`); for
   `(h∘g)∘f=…` it emits `exact Set.comp_id f` (right lemma stem, wrong namespace).
   → `unknown_identifier`. The corpus never taught the *exact* correct name for
   this held-out shape, so the decoder interpolates a plausible-but-wrong one.

2. **Wrong-but-plausible shape (the swap bug).** For `s∩t ⊆ s` the top beams are
   `intro x h; exact ⟨h.2, h.1⟩` and `exact fun x h => h.1.1` — these are the
   proofs of *neighbouring* goals (`s∩t ⊆ t∩s`, or a doubly-nested intersection),
   not this one. The model has seen the `⟨h.2,h.1⟩` shape and the `h.1` shape but
   cannot reliably pick which goal each belongs to. → `type_mismatch` / `shape_miss`.

3. **Truncated / garbled hypothesis-chaining.** For `s⊆u → t⊆u → s∪t ⊆ u` the
   beams degenerate to `intro x hx; exact h2 (h1 (h1` — the right idea (apply the
   hypotheses) but the term is malformed and runs off the beam length. The clean
   proof `exact Set.union_subset h1 h2` is never produced because the
   `union_subset` lemma had **one** sibling in the corpus and it was held out.

## Diagnosis: sparse-sibling underfit, not a hard wall

Every residual is a **single-tactic-provable** goal (the expected proofs are one
tactic). None require multi-step planning; none are impossible. The common cause
is **family sparsity**: each residual family (`mem_inter_iff`, `union_subset`,
`subset_inter`, `inter_subset`, general `le_trans`, `comp_assoc`) had only 1–3
training siblings, and when one is held out the small seq2seq cannot pin the exact
identifier/shape from the survivors. The decoder lands in the right neighbourhood
but mis-binds the name or the projection.

This is a **data-volume / shape-density** limit, **not** an architecture or
proof-state-supervision limit (LeanDojo next-state would not help a model that
already proposes the right *neighbourhood*; it needs denser exemplars of the exact
shape). It is exactly the regime where adding more verified siblings should help.

## v28 corpus targets implied by the audit

Per family, add many concrete sibling shapes so a held-out member has near-identical
neighbours (each verified by the trusted verifier):

* **Set membership-iff** (`mem_inter_iff`, `mem_union_iff`, `mem_diff_iff`, …):
  `exact Set.mem_*`, `Iff.rfl`, `rfl`, `constructor <;> intro h <;> …`,
  `simp [Set.mem_*]`.
* **Set subset of inter/union** (`inter_subset_left/right`, `subset_union_*`,
  `union_subset`, `subset_inter`): both the named-lemma form and the
  `intro x hx; exact …` / `hx.elim` manual form, across many `s,t,u` arrangements.
* **Set projection** (`x∈s∩t → x∈s/t`): `exact h.1/.2/.left/.right` — many copies so
  the projection direction is unambiguous.
* **General order/lattice** (`le_refl`, `le_trans`, `le_of_eq`, `min_le_left`,
  `le_max_right`, antisymm-free): typeclass-polymorphic (`[Preorder]`/`[LinearOrder]`)
  so the skill is not Nat-locked.
* **Function** (`comp_assoc`, `comp_id`, `id_comp`, `const`): `rfl` / `funext x; rfl`.
* **Nat assoc/comm both directions**: `omega` / `ring` / named `.symm` forms.
* **Finset** (new category): `mem_union`/`mem_inter`/`subset_union` with
  `[DecidableEq α]`, `.mpr (Or.inl …)` / `(… ).1` forms.

The Part 2 generator (`generate_v28_mathlib_expanded_corpus.py`) implements exactly
these families with multiple verified candidate styles each.

## Honesty

Expected proofs are Lean-verified reference targets, never predictions. No
`state_after`. No manual oracle. Audit reads only existing eval artifacts.
