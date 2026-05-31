# V25 failure & transfer examples (Part 7)

Concrete beams from the verified runs (`data/baselines/v25_zero_shot_tierc/` and
`data/baselines/v25_aug_tierc_test/`). `OK` = Lean-accepted against real Mathlib;
`xx` = rejected. Ordering is the `raw` beam (literal `\n` shown as ` ; `).

## 1. Successful zero-shot transfer (Mathlib-tagged) — `xs ++ [] = xs`

```
v25_list_append_nil  [mathlib]  pass@1 ✅
  0 OK  simp
  1 xx  exact List.append_nil zs
  2 xx  exact List.append_nil l
  …    (all `exact List.append_nil <name>` fail: see #3)
```
The v24 generator transfers `simp` straight into Mathlib and solves it at rank 0
— with **no** Mathlib data in training.

## 2. Success only after augmentation — `n * 1 = n`

Zero-shot (v24) **fails** — no verifying candidate in the top-10:
```
v25_nat_mul_one  [mathlib]  pass@1 ✗ (no_verify)
  0 xx  exact rfl        1 xx  exact Eq.refl     2 xx  exact ⟨1,
  3 xx  exact Nat.add_comm   4 xx  exact hAll i  …
```
After the tiny tier-C augmentation (v25), it is solved at rank 0:
```
v25_nat_mul_one  [mathlib]  pass@1 ✅
  0 OK  simp
```
The 68-row corpus taught the generator to reach for `simp` on `* 1` shapes.
(Also newly solved by augmentation: `(b && true) = b` via `simpa using heq` at
rank 8, and `xs.map id = xs`.)

## 3. Mathlib tactic / identifier vocabulary failure — lemma arity

The generator often emits the *right lemma name* but with the wrong argument
arity, because Mathlib v4.30.0 states these lemmas with **implicit** list args:
```
exact List.append_nil zs   →  xx  (Function expected: append_nil takes implicit l)
exact List.length_reverse xs  →  xx  (corpus reference also failed here)
exact List.mem_cons_self x xs  →  xx
```
These are the dominant zero-shot failure class overall (**164 `unknown_identifier`
+ 70 `type_mismatch`** across the 36 theorems). The model's identifier vocabulary
is core-Lean, so it hallucinates names (`hAll`, `himp`, `Or.refl`, `Eq.add_comm`)
or mis-applies real Mathlib lemmas.

## 4. Syntax failure (and the absence of import failures)

There were **zero import/environment failures** — `import Mathlib` resolves
cleanly for every candidate, so the environment was *not* a wall. The
syntax-level failures are malformed tactics the decoder truncates, e.g.:
```
exact ⟨1,                          →  xx  (parse error: unterminated ⟨…⟩)
rw [Bool.and_true] [Bool.and_true] at   →  xx  (parse error)
rcases h with ⟨hp, hq ;  exact ⟨hq, hp⟩  →  xx  (unbalanced ⟨)
```
(57 `parse_error` candidates total — a decoder artifact, not an env issue.)

## 5. Theorem-shape miss — `s ⊆ s` (Set)

```
v25_set_subset_refl  [mathlib]  pass@1 ✗ (no_verify)
  0 xx  apply g ;  exact f      1 xx  exact g.refl a   2 xx  exact g.2 a
  3 xx  exact g.1 a             4 xx  exact Eq.refl a   …
```
The generator has **no Set / `⊆` concept**: it treats the goal like a function
application or a conjunction projection. **All 5 Set theorems are unreachable
zero-shot (pass@10 = 0.000)** — the clearest theorem-shape gap.

## 6. Broad-core skill that DOES transfer — `p ∧ q → q ∧ p`

```
v25_logic_and_symm  [core]  pass@1 ✅
  0 OK  cases h with | intro hp hq => exact ⟨hq, hp⟩
  1 OK  rcases h with ⟨hp, hq⟩ ; exact ⟨hq, hp⟩
  2 OK  exact ⟨h.2, h.1⟩
```
Conjunction projection / swap — a core skill from v18 — transfers perfectly to
the Mathlib environment (3 verifying candidates in the top 3). This is why
**core-tagged tier-C theorems reach pass@5 = 0.812**.

## 7. Broad-core habit that does NOT transfer — `rfl` reflex on `n * 1 = n`

The same `exact rfl` habit that solves `n + 0 = n` (which reduces definitionally)
**fails** on `n * 1 = n` and `0 + n = n` (which do not reduce for a variable `n`).
Zero-shot, the generator over-applies `rfl`/`Eq.refl` and then falls back to
hallucinated identifiers, never reaching `simp` / `Nat.mul_one` / `ring` — see
#2's zero-shot beam. The skill "use `rfl` for equalities" is right in core Lean
but mis-fires on Mathlib's non-definitional equalities until the corpus teaches
the `simp`/lemma alternative.

## Takeaway

Transfer is gated by **generator coverage**, split cleanly into (a) *identifier/
lemma vocabulary* (#3) and (b) *theorem-shape coverage* (#5, #7). The environment
(#4) is not a wall. A tiny verified corpus fixes specific gaps (#2) — but, per
[`V25_BROADCORE_REGRESSION_REPORT.md`](V25_BROADCORE_REGRESSION_REPORT.md), naive
co-training regresses broad-core, so the fix must be delivered without
cannibalising v24.
