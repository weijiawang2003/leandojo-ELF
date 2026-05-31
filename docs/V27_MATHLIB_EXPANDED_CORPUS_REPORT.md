# Mini-ELF v27 — Expanded Mathlib Corpus Report (Part 4)

Source: `scripts/generate_v27_mathlib_expanded_corpus.py`. Verifier:
`TrustedMathlibVerifier` (sentinel + confirm + rescue, `import Mathlib`).
Integrity re-check: `scripts/verify_v27_mathlib_expanded_corpus.py`.

## Counts

- Theorems planned: **87** (categories A–F, Set-heavy).
- Candidates proposed: **268**; **181 verified** new training rows; 5 Lean-rejected.
- Theorems contributing ≥1 new training row: **60**.
- Leakage drops (verified but excluded from train): v18-name 0, v18-triple 8,
  **held-out (v25/v26) statement/triple 74** — correctly kept out so the
  benchmarks stay clean. 27 theorems verified entirely into held-out shapes
  (stripped to zero new rows — **not** coverage gaps).
- True coverage gaps (Lean rejected ALL candidates): **0**.

## New verified training rows by category

| Category | rows | theorems | new theorem-families |
|----------|------|----------|----------------------|
| set | 53 | 23 | mem_iff, mem_union, mem_inter_proj, union_subset, subset_inter, subset_trans, diff_subset, union_comm, inter_self, mem_singleton, subset_univ |
| order | 40 | 13 | le_refl, le_succ, le_succ_of_le, le_add, le_of_eq, succ_le_succ, zero_le, lt_succ, succ_pos, min_max |
| logic | 31 | 12 | and_self, or_self, or_symm, contrapose, demorgan, imp_trans, curry, em, false_elim, not_not |
| bool_option | 16 | 10 | and_self, or_false, not_not, option_map_id, option_getD, option_isSome |
| list | 15 | 12 | append_assoc, length_cons, length_nil, map_nil, mem_append, mem_cons, nil_append |
| nat | 14 | 12 | add_assoc, add_sub, mul_comm, mul_zero, two_mul |
| function | 12 | 5 | comp_id, comp_assoc, const_apply, id_apply |

The corpus **directly targets the Part-3 residuals**: Set membership-iff
(`mem_inter_iff`, `mem_union`), inter/union commutativity & associativity as
subsets, `subset_trans`, `subset_inter`, `diff_subset`, membership projection
(`x ∈ s ∩ t → x ∈ s`) — and adds a dedicated **order** block (v26 had order only
folded under `nat`).

## Lean-rejected candidates (kept for taxonomy)

All 5 rejects are the **API/arity mistakes** the Part-3 audit predicted:
`exact List.length_append xs ys`, `exact List.map_map g f xs`,
`exact List.mem_cons_self x xs` → *"Function expected"* (these Mathlib lemmas take
implicit args; passing them explicitly is wrong), `exact Nat.add_sub_cancel` →
*type mismatch* (wrong arity), and a bare `simp` → *"made no progress"*. The
corpus also includes the **correct** arity-free forms (`exact List.length_cons`,
`simp`, `rfl`) which verified — so the model is shown the right API, not the wrong one.

## Integrity (`data/baselines/v27_corpus_integrity/report.json`)

Re-verified all 181 verified rows + 5 failed rows with the trusted verifier and a
24-row gold one-per-file spot-check:
- 181 / 181 verified rows still pass; **0 regressions**;
- 0 failed rows became valid;
- **0 gold mismatches**.

## Honesty

Real `import Mathlib` typecheck (no mock); `uses_state_after = false`;
`uses_manual_oracle = false`; manual targets are Lean-verified corpus targets,
never fed to a model as predictions; Mathlib is real and external. All v27 theorem
names are `v27_*`, distinct from v25/v26.
