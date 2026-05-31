# Mini-ELF v8 — donorless target audit (Part 1)

The set of test rows v8's generative proposer has to attack — every row where retrieval has no usable donor in train. Materialised directly from the v7 split manifests in `data/processed/planner_blind_family_holdout/` and `…_operation_holdout/`.

**Honest framing.** The shortest tactic that we *know* verifies is shown for each example, but only as an analysis-side description of the proof shape v8 has to produce. The v8 proposer is **not** allowed to read it. Reporting that tactic as a model output would be the manual oracle the v8 brief explicitly forbids.

## Totals — family_holdout (10 folds, pooled)

- Total target rows: **157**
- Rows with a known verified tactic anywhere in the processed pool: **157**
- Rows with no known verified tactic: **0**

### By group

| group | targets | unique theorems | sibling-in-train | shortest-tactic example |
|---|---:|---:|:--:|---|
| `contrapositive` | 12 | 6 | 12/12 | `exact fun hp => hnq (h hp)` |
| `exists_elim` | 46 | 20 | 46/46 | `exact h.elim fun _ hp => hp` |
| `exists_reconstruct` | 15 | 5 | 0/15 | `exact h` |
| `forall_inst` | 7 | 7 | 0/7 | `exact h 3` |
| `negation_contradiction` | 57 | 18 | 57/57 | `contradiction` |
| `rewrite` | 20 | 5 | 0/20 | `rw [h]` |

### By held family (LOFO)

| held family | targets | unique theorems | required_operation set | sibling families in train |
|---|---:|---:|---|---|
| `exists_elim_conj` | 16 | 8 | destruct_exists | `exists_elim_prop` |
| `exists_elim_prop` | 18 | 6 | destruct_exists | `exists_elim_conj` |
| `exists_reconstruct` | 15 | 5 | unknown | — |
| `forall_inst` | 7 | 7 | instantiate_forall | — |
| `neg_contrapositive` | 12 | 6 | intro_negation | `neg_double_intro`, `neg_imp_exfalso` |
| `neg_double_intro` | 10 | 5 | intro_negation | `neg_contrapositive`, `neg_imp_exfalso` |
| `neg_exfalso` | 32 | 8 | contradiction | `neg_or_cases` |
| `neg_imp_exfalso` | 15 | 5 | intro_negation | `neg_contrapositive`, `neg_double_intro` |
| `neg_or_cases` | 12 | 6 | contradiction | `neg_exfalso` |
| `rewrite_succ` | 20 | 5 | rewrite | — |

## Totals — operation_holdout (7 folds, pooled)

- Total target rows: **157**
- With known verified tactic: **157**
- Without: **0**

### By group

| group | targets | unique theorems | sibling-in-train | shortest-tactic example |
|---|---:|---:|:--:|---|
| `contrapositive` | 12 | 6 | 0/12 | `exact fun hp => hnq (h hp)` |
| `exists_elim` | 46 | 20 | 0/46 | `exact h.elim fun _ hp => hp` |
| `exists_reconstruct` | 15 | 5 | 0/15 | `exact h` |
| `forall_inst` | 7 | 7 | 0/7 | `exact h 3` |
| `negation_contradiction` | 57 | 18 | 0/57 | `contradiction` |
| `rewrite` | 20 | 5 | 0/20 | `rw [h]` |

### By held operation (LOOO)

| held operation | targets | unique theorems | required_operation set | sibling families in train |
|---|---:|---:|---|---|
| `contradiction` | 44 | 14 | contradiction | — |
| `destruct_exists` | 34 | 14 | destruct_exists | — |
| `instantiate_forall` | 7 | 7 | instantiate_forall | — |
| `intro_negation` | 37 | 16 | intro_negation | — |
| `rewrite` | 20 | 5 | rewrite | — |
| `unknown` | 15 | 5 | unknown | — |

## Worked examples (family_holdout)

Two distinct theorems per group, showing exactly what v8 has to handle.

### contrapositive

**`neg_contrapositive_ab`** (family=`neg_contrapositive`, op=`intro_negation`, held-as=`neg_contrapositive`)

Theorem statement:
```lean
(a b : Prop) (h : a → b) (hnq : ¬b) : ¬a
```

`state_before`:
```
a b : Prop
h : a → b
hnq : ¬b
⊢ ¬a
```

- available donor families: `and_comm`, `and_elim_left`, `and_elim_right`, `and_intro`, `eq_chain3`, `eq_refl`, `eq_symm`, `eq_symm_trans`, `eq_trans`, `exists_elim_conj`, `exists_elim_prop`, `exists_reconstruct`, `exists_witness`, `false_elim`, `forall_inst`, `iff_apply`, `iff_chain`, `iff_flip`, `iff_intro`, `iff_mp`, `iff_mpr`, `imp_chain3`, `imp_chain_mixed`, `imp_compose`, `imp_identity`, `imp_uncurry`, `modus_ponens`, `nat_rfl`, `neg_double_intro`, `neg_exfalso`, `neg_imp_exfalso`, `neg_or_cases`, `nested_and_elim_l`, `nested_and_elim_r`, `nested_and_intro`, `or_comm`, `or_elim`, `or_intro_left`, `or_intro_right`, `or_self_elim`, `rewrite_succ`, `true_intro`
- same-operation siblings in train: `neg_double_intro`, `neg_imp_exfalso`
- why retrieval fails: `no_same_family_donor;same_operation_sibling_in_train`
- shortest tactic that we KNOW verifies (*analysis only, never used as model output*): `exact fun hp => hnq (h hp)`

**`neg_contrapositive_ac`** (family=`neg_contrapositive`, op=`intro_negation`, held-as=`neg_contrapositive`)

Theorem statement:
```lean
(a c : Prop) (h : a → c) (hnq : ¬c) : ¬a
```

`state_before`:
```
a c : Prop
h : a → c
hnq : ¬c
⊢ ¬a
```

- available donor families: `and_comm`, `and_elim_left`, `and_elim_right`, `and_intro`, `eq_chain3`, `eq_refl`, `eq_symm`, `eq_symm_trans`, `eq_trans`, `exists_elim_conj`, `exists_elim_prop`, `exists_reconstruct`, `exists_witness`, `false_elim`, `forall_inst`, `iff_apply`, `iff_chain`, `iff_flip`, `iff_intro`, `iff_mp`, `iff_mpr`, `imp_chain3`, `imp_chain_mixed`, `imp_compose`, `imp_identity`, `imp_uncurry`, `modus_ponens`, `nat_rfl`, `neg_double_intro`, `neg_exfalso`, `neg_imp_exfalso`, `neg_or_cases`, `nested_and_elim_l`, `nested_and_elim_r`, `nested_and_intro`, `or_comm`, `or_elim`, `or_intro_left`, `or_intro_right`, `or_self_elim`, `rewrite_succ`, `true_intro`
- same-operation siblings in train: `neg_double_intro`, `neg_imp_exfalso`
- why retrieval fails: `no_same_family_donor;same_operation_sibling_in_train`
- shortest tactic that we KNOW verifies (*analysis only, never used as model output*): `exact fun hp => hnq (h hp)`

### exists_elim

**`exists_elim_conj_l_ab`** (family=`exists_elim_conj`, op=`destruct_exists`, held-as=`exists_elim_conj`)

Theorem statement:
```lean
(a b : Prop) (h : ∃ _ : Nat, a ∧ b) : a
```

`state_before`:
```
a b : Prop
h : ∃ _ : Nat, a ∧ b
⊢ a
```

- available donor families: `and_comm`, `and_elim_left`, `and_elim_right`, `and_intro`, `eq_chain3`, `eq_refl`, `eq_symm`, `eq_symm_trans`, `eq_trans`, `exists_elim_prop`, `exists_reconstruct`, `exists_witness`, `false_elim`, `forall_inst`, `iff_apply`, `iff_chain`, `iff_flip`, `iff_intro`, `iff_mp`, `iff_mpr`, `imp_chain3`, `imp_chain_mixed`, `imp_compose`, `imp_identity`, `imp_uncurry`, `modus_ponens`, `nat_rfl`, `neg_contrapositive`, `neg_double_intro`, `neg_exfalso`, `neg_imp_exfalso`, `neg_or_cases`, `nested_and_elim_l`, `nested_and_elim_r`, `nested_and_intro`, `or_comm`, `or_elim`, `or_intro_left`, `or_intro_right`, `or_self_elim`, `rewrite_succ`, `true_intro`
- same-operation siblings in train: `exists_elim_prop`
- why retrieval fails: `no_same_family_donor;same_operation_sibling_in_train`
- shortest tactic that we KNOW verifies (*analysis only, never used as model output*): `obtain ⟨n, hpq⟩ := h
  exact hpq.1`

**`exists_elim_conj_l_pq`** (family=`exists_elim_conj`, op=`destruct_exists`, held-as=`exists_elim_conj`)

Theorem statement:
```lean
(p q : Prop) (h : ∃ _ : Nat, p ∧ q) : p
```

`state_before`:
```
p q : Prop
h : ∃ _ : Nat, p ∧ q
⊢ p
```

- available donor families: `and_comm`, `and_elim_left`, `and_elim_right`, `and_intro`, `eq_chain3`, `eq_refl`, `eq_symm`, `eq_symm_trans`, `eq_trans`, `exists_elim_prop`, `exists_reconstruct`, `exists_witness`, `false_elim`, `forall_inst`, `iff_apply`, `iff_chain`, `iff_flip`, `iff_intro`, `iff_mp`, `iff_mpr`, `imp_chain3`, `imp_chain_mixed`, `imp_compose`, `imp_identity`, `imp_uncurry`, `modus_ponens`, `nat_rfl`, `neg_contrapositive`, `neg_double_intro`, `neg_exfalso`, `neg_imp_exfalso`, `neg_or_cases`, `nested_and_elim_l`, `nested_and_elim_r`, `nested_and_intro`, `or_comm`, `or_elim`, `or_intro_left`, `or_intro_right`, `or_self_elim`, `rewrite_succ`, `true_intro`
- same-operation siblings in train: `exists_elim_prop`
- why retrieval fails: `no_same_family_donor;same_operation_sibling_in_train`
- shortest tactic that we KNOW verifies (*analysis only, never used as model output*): `obtain ⟨n, hpq⟩ := h
  exact hpq.1`

### exists_reconstruct

**`exists_reconstruct_100`** (family=`exists_reconstruct`, op=`unknown`, held-as=`exists_reconstruct`)

Theorem statement:
```lean
(h : ∃ n : Nat, n = 100) : ∃ m : Nat, m = 100
```

`state_before`:
```
h : ∃ n : Nat, n = 100
⊢ ∃ m : Nat, m = 100
```

- available donor families: `and_comm`, `and_elim_left`, `and_elim_right`, `and_intro`, `eq_chain3`, `eq_refl`, `eq_symm`, `eq_symm_trans`, `eq_trans`, `exists_elim_conj`, `exists_elim_prop`, `exists_witness`, `false_elim`, `forall_inst`, `iff_apply`, `iff_chain`, `iff_flip`, `iff_intro`, `iff_mp`, `iff_mpr`, `imp_chain3`, `imp_chain_mixed`, `imp_compose`, `imp_identity`, `imp_uncurry`, `modus_ponens`, `nat_rfl`, `neg_contrapositive`, `neg_double_intro`, `neg_exfalso`, `neg_imp_exfalso`, `neg_or_cases`, `nested_and_elim_l`, `nested_and_elim_r`, `nested_and_intro`, `or_comm`, `or_elim`, `or_intro_left`, `or_intro_right`, `or_self_elim`, `rewrite_succ`, `true_intro`
- same-operation siblings in train: — (none)
- why retrieval fails: `no_same_family_donor`
- shortest tactic that we KNOW verifies (*analysis only, never used as model output*): `exact h`

**`exists_reconstruct_11`** (family=`exists_reconstruct`, op=`unknown`, held-as=`exists_reconstruct`)

Theorem statement:
```lean
(h : ∃ n : Nat, n = 11) : ∃ m : Nat, m = 11
```

`state_before`:
```
h : ∃ n : Nat, n = 11
⊢ ∃ m : Nat, m = 11
```

- available donor families: `and_comm`, `and_elim_left`, `and_elim_right`, `and_intro`, `eq_chain3`, `eq_refl`, `eq_symm`, `eq_symm_trans`, `eq_trans`, `exists_elim_conj`, `exists_elim_prop`, `exists_witness`, `false_elim`, `forall_inst`, `iff_apply`, `iff_chain`, `iff_flip`, `iff_intro`, `iff_mp`, `iff_mpr`, `imp_chain3`, `imp_chain_mixed`, `imp_compose`, `imp_identity`, `imp_uncurry`, `modus_ponens`, `nat_rfl`, `neg_contrapositive`, `neg_double_intro`, `neg_exfalso`, `neg_imp_exfalso`, `neg_or_cases`, `nested_and_elim_l`, `nested_and_elim_r`, `nested_and_intro`, `or_comm`, `or_elim`, `or_intro_left`, `or_intro_right`, `or_self_elim`, `rewrite_succ`, `true_intro`
- same-operation siblings in train: — (none)
- why retrieval fails: `no_same_family_donor`
- shortest tactic that we KNOW verifies (*analysis only, never used as model output*): `exact h`

### forall_inst

**`forall_inst_13_6`** (family=`forall_inst`, op=`instantiate_forall`, held-as=`forall_inst`)

Theorem statement:
```lean
(h : ∀ x : Nat, x = 6) : 13 = 6
```

`state_before`:
```
h : ∀ x : Nat, x = 6
⊢ 13 = 6
```

- available donor families: `and_comm`, `and_elim_left`, `and_elim_right`, `and_intro`, `eq_chain3`, `eq_refl`, `eq_symm`, `eq_symm_trans`, `eq_trans`, `exists_elim_conj`, `exists_elim_prop`, `exists_reconstruct`, `exists_witness`, `false_elim`, `iff_apply`, `iff_chain`, `iff_flip`, `iff_intro`, `iff_mp`, `iff_mpr`, `imp_chain3`, `imp_chain_mixed`, `imp_compose`, `imp_identity`, `imp_uncurry`, `modus_ponens`, `nat_rfl`, `neg_contrapositive`, `neg_double_intro`, `neg_exfalso`, `neg_imp_exfalso`, `neg_or_cases`, `nested_and_elim_l`, `nested_and_elim_r`, `nested_and_intro`, `or_comm`, `or_elim`, `or_intro_left`, `or_intro_right`, `or_self_elim`, `rewrite_succ`, `true_intro`
- same-operation siblings in train: — (none)
- why retrieval fails: `no_same_family_donor`
- shortest tactic that we KNOW verifies (*analysis only, never used as model output*): `exact h 13`

**`forall_inst_3_0`** (family=`forall_inst`, op=`instantiate_forall`, held-as=`forall_inst`)

Theorem statement:
```lean
(h : ∀ x : Nat, x = 0) : 3 = 0
```

`state_before`:
```
h : ∀ x : Nat, x = 0
⊢ 3 = 0
```

- available donor families: `and_comm`, `and_elim_left`, `and_elim_right`, `and_intro`, `eq_chain3`, `eq_refl`, `eq_symm`, `eq_symm_trans`, `eq_trans`, `exists_elim_conj`, `exists_elim_prop`, `exists_reconstruct`, `exists_witness`, `false_elim`, `iff_apply`, `iff_chain`, `iff_flip`, `iff_intro`, `iff_mp`, `iff_mpr`, `imp_chain3`, `imp_chain_mixed`, `imp_compose`, `imp_identity`, `imp_uncurry`, `modus_ponens`, `nat_rfl`, `neg_contrapositive`, `neg_double_intro`, `neg_exfalso`, `neg_imp_exfalso`, `neg_or_cases`, `nested_and_elim_l`, `nested_and_elim_r`, `nested_and_intro`, `or_comm`, `or_elim`, `or_intro_left`, `or_intro_right`, `or_self_elim`, `rewrite_succ`, `true_intro`
- same-operation siblings in train: — (none)
- why retrieval fails: `no_same_family_donor`
- shortest tactic that we KNOW verifies (*analysis only, never used as model output*): `exact h 3`

### negation_contradiction

**`neg_double_intro_a`** (family=`neg_double_intro`, op=`intro_negation`, held-as=`neg_double_intro`)

Theorem statement:
```lean
(a : Prop) (hp : a) : ¬¬a
```

`state_before`:
```
a : Prop
hp : a
⊢ ¬¬a
```

- available donor families: `and_comm`, `and_elim_left`, `and_elim_right`, `and_intro`, `eq_chain3`, `eq_refl`, `eq_symm`, `eq_symm_trans`, `eq_trans`, `exists_elim_conj`, `exists_elim_prop`, `exists_reconstruct`, `exists_witness`, `false_elim`, `forall_inst`, `iff_apply`, `iff_chain`, `iff_flip`, `iff_intro`, `iff_mp`, `iff_mpr`, `imp_chain3`, `imp_chain_mixed`, `imp_compose`, `imp_identity`, `imp_uncurry`, `modus_ponens`, `nat_rfl`, `neg_contrapositive`, `neg_exfalso`, `neg_imp_exfalso`, `neg_or_cases`, `nested_and_elim_l`, `nested_and_elim_r`, `nested_and_intro`, `or_comm`, `or_elim`, `or_intro_left`, `or_intro_right`, `or_self_elim`, `rewrite_succ`, `true_intro`
- same-operation siblings in train: `neg_contrapositive`, `neg_imp_exfalso`
- why retrieval fails: `no_same_family_donor;same_operation_sibling_in_train`
- shortest tactic that we KNOW verifies (*analysis only, never used as model output*): `exact fun hnp => hnp hp`

**`neg_double_intro_p`** (family=`neg_double_intro`, op=`intro_negation`, held-as=`neg_double_intro`)

Theorem statement:
```lean
(p : Prop) (hp : p) : ¬¬p
```

`state_before`:
```
p : Prop
hp : p
⊢ ¬¬p
```

- available donor families: `and_comm`, `and_elim_left`, `and_elim_right`, `and_intro`, `eq_chain3`, `eq_refl`, `eq_symm`, `eq_symm_trans`, `eq_trans`, `exists_elim_conj`, `exists_elim_prop`, `exists_reconstruct`, `exists_witness`, `false_elim`, `forall_inst`, `iff_apply`, `iff_chain`, `iff_flip`, `iff_intro`, `iff_mp`, `iff_mpr`, `imp_chain3`, `imp_chain_mixed`, `imp_compose`, `imp_identity`, `imp_uncurry`, `modus_ponens`, `nat_rfl`, `neg_contrapositive`, `neg_exfalso`, `neg_imp_exfalso`, `neg_or_cases`, `nested_and_elim_l`, `nested_and_elim_r`, `nested_and_intro`, `or_comm`, `or_elim`, `or_intro_left`, `or_intro_right`, `or_self_elim`, `rewrite_succ`, `true_intro`
- same-operation siblings in train: `neg_contrapositive`, `neg_imp_exfalso`
- why retrieval fails: `no_same_family_donor;same_operation_sibling_in_train`
- shortest tactic that we KNOW verifies (*analysis only, never used as model output*): `exact fun hnp => hnp hp`

### rewrite

**`rewrite_succ_ab`** (family=`rewrite_succ`, op=`rewrite`, held-as=`rewrite_succ`)

Theorem statement:
```lean
(a b : Nat) (h : a = b) : a.succ = b.succ
```

`state_before`:
```
a b : Nat
h : a = b
⊢ a.succ = b.succ
```

- available donor families: `and_comm`, `and_elim_left`, `and_elim_right`, `and_intro`, `eq_chain3`, `eq_refl`, `eq_symm`, `eq_symm_trans`, `eq_trans`, `exists_elim_conj`, `exists_elim_prop`, `exists_reconstruct`, `exists_witness`, `false_elim`, `forall_inst`, `iff_apply`, `iff_chain`, `iff_flip`, `iff_intro`, `iff_mp`, `iff_mpr`, `imp_chain3`, `imp_chain_mixed`, `imp_compose`, `imp_identity`, `imp_uncurry`, `modus_ponens`, `nat_rfl`, `neg_contrapositive`, `neg_double_intro`, `neg_exfalso`, `neg_imp_exfalso`, `neg_or_cases`, `nested_and_elim_l`, `nested_and_elim_r`, `nested_and_intro`, `or_comm`, `or_elim`, `or_intro_left`, `or_intro_right`, `or_self_elim`, `true_intro`
- same-operation siblings in train: — (none)
- why retrieval fails: `no_same_family_donor`
- shortest tactic that we KNOW verifies (*analysis only, never used as model output*): `rw [h]`

**`rewrite_succ_ij`** (family=`rewrite_succ`, op=`rewrite`, held-as=`rewrite_succ`)

Theorem statement:
```lean
(i j : Nat) (h : i = j) : i.succ = j.succ
```

`state_before`:
```
i j : Nat
h : i = j
⊢ i.succ = j.succ
```

- available donor families: `and_comm`, `and_elim_left`, `and_elim_right`, `and_intro`, `eq_chain3`, `eq_refl`, `eq_symm`, `eq_symm_trans`, `eq_trans`, `exists_elim_conj`, `exists_elim_prop`, `exists_reconstruct`, `exists_witness`, `false_elim`, `forall_inst`, `iff_apply`, `iff_chain`, `iff_flip`, `iff_intro`, `iff_mp`, `iff_mpr`, `imp_chain3`, `imp_chain_mixed`, `imp_compose`, `imp_identity`, `imp_uncurry`, `modus_ponens`, `nat_rfl`, `neg_contrapositive`, `neg_double_intro`, `neg_exfalso`, `neg_imp_exfalso`, `neg_or_cases`, `nested_and_elim_l`, `nested_and_elim_r`, `nested_and_intro`, `or_comm`, `or_elim`, `or_intro_left`, `or_intro_right`, `or_self_elim`, `true_intro`
- same-operation siblings in train: — (none)
- why retrieval fails: `no_same_family_donor`
- shortest tactic that we KNOW verifies (*analysis only, never used as model output*): `rw [h]`


## Reading the table

- *`available donor families`* are the families that *do* appear in train. v7 retrieval can fetch tactics from any of them; the question is whether any of those tactics will close the held-out family's goal. v7 said: not in this corpus — `cross_family_verified = 0`.
- *`same-operation siblings in train`* names families that share the same `required_operation` as the held family (e.g. `neg_or_cases` is a sibling of `neg_exfalso` under `contradiction`); v7 showed these siblings rank high for retrieval but their tactic *bodies* still fail (wrong destructor, wrong projection, etc.).
- *`why retrieval fails`* is the structural reason, not a post-hoc failure label.

