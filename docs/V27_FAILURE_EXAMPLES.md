# Mini-ELF v27 — Failure / Improvement Examples (Part 8)

Concrete, Lean-verified examples. All verdicts from the trusted verifier; no
state_after; manual targets never fed to a model.

## 1. Set improvement (v26 → v27)

**`v26_set_inter_comm_subset`** : `(α : Type) (s t : Set α) : s ∩ t ⊆ t ∩ s`
- v26_widened: **no candidate verified** (Set residual on v26 holdout).
- v27_set_heavy: **pass@1** via `intro x h; exact ⟨h.2, h.1⟩` (also
  `exact fun x h => ⟨h.2, h.1⟩`).
- Why: the v27 corpus added inter/union-commutativity-as-subset and
  membership-projection shapes; upsampling Set rows taught the
  `⟨h.2, h.1⟩` swap. This closes the last v26-holdout Set residual → Set 0.75 → **1.00**.

## 2. order improvement / documentation

**`v27_ord_le_of_eq`** : `(n m : Nat) (h : n = m) : n ≤ m` and the order block at
large — solved at pass@10 = **1.00** with training and **0.90 in pure transfer**
(model trained with the whole order category held out) via `omega` / `simp` /
`Nat.le_of_eq`. v27 promotes order to a first-class documented category (v26 only
had order folded under `nat`); e.g. `v27_ord_le_add_left` and `v27_ord_le_max_right`
verify via `simp` even with zero order training.

## 3. Nat / list / simp improvement (v26 → v27)

**`v27_nat_add_assoc_rev`** : `(a b c : Nat) : a + (b + c) = a + b + c`
- v26_base: **no candidate verified** (associativity under-represented).
- v27_set_heavy: **pass** via `omega`.
- Why: v27 added associativity **both directions** (`add_assoc`, `add_assoc_rev`),
  so the model learned the reversed orientation. (Companion: the v26 `nat_add_assoc`
  residual is likewise covered by the v27 associativity rows.)

## 4. Remaining hard Set failure (fresh v27 holdout)

**`v27_set_mem_inter_iff`** : `(α : Type) (s t : Set α) (x : α) : x ∈ s ∩ t ↔ x ∈ s ∧ x ∈ t`
- v27_set_heavy: **no candidate verified** in top-10 on the fresh holdout.
- The proof is one tactic (`exact Iff.rfl` / `rfl` / `simp [Set.mem_inter_iff]`),
  but the model's beam does not place a verifying membership-iff form in the top-10
  for this *novel* iff shape. Companion hard shape: `v27_set_union_subset`
  (`s ⊆ u → t ⊆ u → s ∪ t ⊆ u`, needs union elimination). These are
  **shape/vocabulary** gaps (Part 8 Q-failures), the v28 target — not a planning wall.

## 5. Broad-core preserved (routed, v24 untouched)

**`v18_bool_not_not`** (and the whole `bool` category, n=3) : routed broad-core
**pass@10 = 1.00**, identical to v24/v26. Because the router sends every
non-Mathlib theorem to the byte-for-byte-unchanged v24 model, broad-core is
preserved exactly (overall 0.938/0.958; only the long-standing conjunction 0.833 /
disjunction 0.800 residuals remain, unchanged from v24).

## 6. Corrected-verifier false-positive avoided

For `(b : Bool) : (b || b) = b` (`v26_bool_or_self2`) the weak co-trained model
(v25_aug) emits garbage beam candidates: `exact b b`, `exact ⟨b, rfl⟩`,
`exact Eq.symm b`, `exact Nat.zero_add b`. A **naive** batched verifier (no
sentinel / no confirm) falsely marks them **verified** (an earlier malformed
candidate desynced the parser and they were skipped). The **trusted** verifier and
the **gold** one-per-file reference both reject all of them (gold agreed with
trusted on **8/8** disputed candidates, with naive on **0/8**). This is why the
corrected verifier is essential: it would have inflated v25_aug's v26-holdout
pass@10 from 0.636 to 0.727 (Part 2).
