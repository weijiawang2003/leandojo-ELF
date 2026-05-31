# v24 generator-bound rows (Part 1)

The 8 v18 broad-core theorems with **no verified candidate in the v22 plus_exists top-10** (from the v23 generator-bound audit). v23 proved these are unreachable by reranking; v24 adds targeted, lean-verified core-Lean shape corpora for each. Every `verified_shape` below was probed and accepted by lean-cli during this audit.

**Families to add:** conj_reassoc, exists_eq_rev, list_append_nil, nat_succ_inj, nat_zero_add, neg_of_or, or_elim, or_intro

## `v18_and_assoc_one` — conjunction

- statement: `(p q r : Prop) (h : p ∧ q ∧ r) : (p ∧ q) ∧ r`
- classification: **conjunction shape gap (nested re-association)**
- verified core-Lean shape: `exact ⟨⟨h.1, h.2.1⟩, h.2.2⟩`
- proposed corpus family: **conj_reassoc**
- raw top-3 (all fail): ['exact ⟨h.2, h.1⟩', 'rcases h with ⟨hp, hq⟩\n  exact ⟨hq', 'cases h with\n  | intro hp hq =>']
- similar verified tactic in training: no (generator never emitted this shape)

## `v18_or_inr` — disjunction

- statement: `(p q : Prop) (hq : q) : p ∨ q`
- classification: **disjunction shape gap + wrong-hyp (emits Or.inr hp not hq)**
- verified core-Lean shape: `exact Or.inr hq`
- proposed corpus family: **or_intro**
- raw top-3 (all fail): ['left\n  exact hp\n  exact hq', 'exact Or.inr hp\n  exact hq', 'right\n  exact hp\n  exact hq']
- similar verified tactic in training: no (generator never emitted this shape)

## `v18_or_elim_to_common` — disjunction

- statement: `(p q r : Prop) (h : p ∨ q) (hpr : p → r) (hqr : q → r) : r`
- classification: **disjunction shape gap (or-elimination)**
- verified core-Lean shape: `exact Or.elim h hpr hqr`
- proposed corpus family: **or_elim**
- raw top-3 (all fail): ['cases h with | inl ht => exact hpq hx', 'cases h with\n  | inl hp => exact hpq hx', 'cases h with\n  | inl ht => exact hpq hx']
- similar verified tactic in training: no (generator never emitted this shape)

## `v18_neg_or_left` — negation

- statement: `(p q : Prop) (h : ¬(p ∨ q)) : ¬p`
- classification: **negation shape gap (push ¬ through Or.inl)**
- verified core-Lean shape: `intro hp
  exact h (Or.inl hp)`
- proposed corpus family: **neg_of_or**
- raw top-3 (all fail): ['exact fun hp => h (h hp)', 'exact fun hp => absurd hp hnp\n  | inr', 'exact fun hp => absurd hp hnp => h']
- similar verified tactic in training: no (generator never emitted this shape)

## `v18_exists_intro_eq` — exists

- statement: `(n : Nat) : ∃ m, n = m`
- classification: **exists shape gap (reversed reflexive witness ∃ m, n = m)**
- verified core-Lean shape: `exact ⟨n, rfl⟩`
- proposed corpus family: **exists_eq_rev**
- raw top-3 (all fail): ['exact ⟨m, rfl⟩', 'refine ⟨m, ?_⟩\n  rfl', 'rcases h with ⟨n, hn⟩']
- similar verified tactic in training: no (generator never emitted this shape)

## `v18_nat_zero_add` — nat_succ

- statement: `(n : Nat) : 0 + n = n`
- classification: **nat_succ shape gap (0 + n = n is NOT rfl; needs lemma/omega)**
- verified core-Lean shape: `exact Nat.zero_add n  /  omega`
- proposed corpus family: **nat_zero_add**
- raw top-3 (all fail): ['exact rfl', 'exact Eq.refl _', 'exact ⟨m, rfl⟩']
- similar verified tactic in training: no (generator never emitted this shape)

## `v18_nat_succ_inj` — nat_succ

- statement: `(n m : Nat) (h : n.succ = m.succ) : n = m`
- classification: **nat_succ shape gap (succ injectivity)**
- verified core-Lean shape: `exact Nat.succ.inj h  /  injection h  /  omega`
- proposed corpus family: **nat_succ_inj**
- raw top-3 (all fail): ['rw [h]', 'subst h\n  rfl', 'exact congrArg Nat.succ']
- similar verified tactic in training: no (generator never emitted this shape)

## `v18_list_append_nil` — list

- statement: `(α : Type) (xs : List α) : xs ++ [] = xs`
- classification: **list shape gap (xs ++ [] = xs is NOT rfl; needs lemma/simp)**
- verified core-Lean shape: `exact List.append_nil xs  /  simp`
- proposed corpus family: **list_append_nil**
- raw top-3 (all fail): ['rfl', 'exact rfl', 'exact Eq.refl']
- similar verified tactic in training: no (generator never emitted this shape)

