# Mini-ELF v19 — Bool Category Gap Note

**Short version.** Bool stays at 0.000 pass@5 / pass@10 in v19 (just
as in v18). This is **not** an identifier-name problem; it is a
**data-shape gap** — the synthetic corpus has zero `cases b` examples
on Boolean values. v19's identifier-abstraction layer does not touch
this gap.

## The three v18 Bool theorems and their need

| theorem | required tactic | shape category |
|---|---|---|
| `v18_bool_true_or_false` | `cases b with \| true => exact Or.inl rfl \| false => exact Or.inr rfl` | structural induction on Bool |
| `v18_bool_and_left` | `rw [Bool.and_true] at h; exact h` (or `simp at h; exact h`) | requires Bool.and_true lemma name |
| `v18_bool_not_not` | `cases b <;> rfl` | structural induction on Bool |

The first and third theorems both need **`cases b`** where `b :
Bool`. v17/v16 corpora have `cases h with | intro n hn => …` (Or /
exists patterns) but never `cases b` on a Boolean. The model has no
training signal that a Boolean variable can be case-analysed.

The second theorem needs a Lean stdlib lemma name (`Bool.and_true`).
Without Mathlib (and without `simp` extensions) this requires the
exact lemma name; the model never saw it.

## Why identifier abstraction can't help

v19 abstraction replaces *local* identifier names with placeholders.
The keyword `cases` is in the closed Lean tactic vocab and is
preserved across abstraction; the syntactic shape `cases b with |
true => …` is preserved as `cases <VAR_BOOL_0> with | true => …`.
But the model has no training pair whose target tactic looks like
that — so it never emits the shape, abstract or not.

## v20 fix is corpus-side

Same pattern as v16 (contrapositive) and v17 (arrow_false_elim):
generate a small corpus of `cases b` examples on Boolean values
with verified-by-lean proofs.

Suggested v20 Bool augmentation:

```
-- ~10–15 theorems
example (b : Bool) : b = true ∨ b = false := by
  cases b with | true => exact Or.inl rfl | false => exact Or.inr rfl

example (b : Bool) : !!b = b := by cases b <;> rfl

example (b : Bool) : (if b then 1 else 0) ≥ 0 := by
  cases b <;> simp

-- variants with different variable names: c, x, p, true_flag, …
```

Plus a handful of `Bool.and_*` / `Bool.or_*` rewrite-lemma rows so
the model sees these stdlib names.

This is **deferred to v20** explicitly per the v19 brief's Part 7:
"Do not try to solve Bool through identifier abstraction unless
naturally improved." v19 abstraction does not naturally improve
Bool (it stays at 0.000); v20 corpus augmentation is the right path.

## Honesty contract

* v19's bool numbers are reported honestly at 0.000 in
  `V19_IDENTIFIER_ABSTRACTION_REPORT.md`.
* The Bool failures are classified as
  ``corpus_shape_bound_no_top10`` in the v19 audit — same class
  the v18 audit assigned. v19 does not move that needle.
