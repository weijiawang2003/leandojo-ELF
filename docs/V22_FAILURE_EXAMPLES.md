# v20 failure examples
v20 broad-plus policy: 48 theorems, 8 unverified at top-10.

## Failure-class tally
- `type_mismatch`: 3
- `tactic_failed`: 3
- `other`: 1
- `wrong_var_name`: 1

## Per-theorem detail

### `v18_and_assoc_one` — conjunction — `type_mismatch`
- statement: `(p q r : Prop) (h : p ∧ q ∧ r) : (p ∧ q) ∧ r`
- expected head: `exact`
- alt-config first-verified rank: {'raw': None}
- top-3 candidates:
  - `'exact ⟨h.2, h.1⟩'`
  - `'exact ⟨h.1, h.1⟩'`
  - `'exact ⟨h.2, h.2, h.1⟩'`
- top-3 errors:
  - `/tmp/mini_elf_lean_de4f3k2h.lean:2:9: error: Application type mismatch: The argument`
  - `/tmp/claude-1000/mini_elf_lean_3p7c75bf.lean:2:9: error: Application type mismatch: The argument`
  - `/tmp/mini_elf_lean_q2_25wju.lean:2:9: error: Application type mismatch: The argument`

### `v18_or_inr` — disjunction — `other`
- statement: `(p q : Prop) (hq : q) : p ∨ q`
- expected head: `exact`
- alt-config first-verified rank: {'raw': None}
- top-3 candidates:
  - `'exact Or.inl hq hq'`
  - `'exact Or.inr hp\n  exact hq'`
  - `'exact Or.intro hp hq'`
- top-3 errors:
  - `/tmp/claude-1000/mini_elf_lean_tms9wy21.lean:2:8: error: Function expected at`
  - `/tmp/claude-1000/mini_elf_lean_v5j4d9_c.lean:2:15: error(lean.unknownIdentifier): Unknown identifier 'hp'`
  - `/tmp/mini_elf_lean_d0dfvtwx.lean:2:8: error(lean.unknownIdentifier): Unknown constant 'Or.intro'`

### `v18_or_elim_to_common` — disjunction — `wrong_var_name`
- statement: `(p q r : Prop) (h : p ∨ q) (hpr : p → r) (hqr : q → r) : r`
- expected head: `exact`
- alt-config first-verified rank: {'raw': None}
- top-3 candidates:
  - `'cases h with | inl ht => exact hpq hx'`
  - `'cases h with\n  | inl hp => exact hpq hx'`
  - `'cases h with\n  | inl ht => exact hpq hx'`
- top-3 errors:
  - `/tmp/claude-1000/mini_elf_lean_5q4k2t6p.lean:2:33: error(lean.unknownIdentifier): Unknown identifier 'hpq'`
  - `/tmp/claude-1000/mini_elf_lean_ngo2sa99.lean:3:20: error(lean.unknownIdentifier): Unknown identifier 'hpq'`
  - `/tmp/claude-1000/mini_elf_lean_c7utw338.lean:3:20: error(lean.unknownIdentifier): Unknown identifier 'hpq'`

### `v18_neg_or_left` — negation — `tactic_failed`
- statement: `(p q : Prop) (h : ¬(p ∨ q)) : ¬p`
- expected head: `intro`
- alt-config first-verified rank: {'raw': None}
- top-3 candidates:
  - `'cases h with\n  | inl hp => exact absurd'`
  - `'exact fun hp => h (h hp)'`
  - `'exact fun hp => (h hp)'`
- top-3 errors:
  - `/tmp/mini_elf_lean_shvkc_hh.lean:2:2: error: Tactic 'cases' failed: major premise type is not an inductive type`
  - `/tmp/claude-1000/mini_elf_lean_1ewperfe.lean:2:23: error: Application type mismatch: The argument`
  - `/tmp/mini_elf_lean_gsvgrioy.lean:2:21: error: Application type mismatch: The argument`

### `v18_exists_intro_eq` — exists — `type_mismatch`
- statement: `(n : Nat) : ∃ m, n = m`
- expected head: `exact`
- alt-config first-verified rank: {'raw': None}
- top-3 candidates:
  - `'exact ⟨4, rfl⟩'`
  - `'exact ⟨20, rfl⟩'`
  - `'exact ⟨m, rfl⟩'`
- top-3 errors:
  - `/tmp/claude-1000/mini_elf_lean_8gmlw7bh.lean:2:12: error: Application type mismatch: The argument`
  - `/tmp/claude-1000/mini_elf_lean_pvzrzj4n.lean:2:13: error: Application type mismatch: The argument`
  - `/tmp/mini_elf_lean_fhx4aorr.lean:2:9: error(lean.unknownIdentifier): Unknown identifier 'm'`

### `v18_nat_zero_add` — nat_succ — `type_mismatch`
- statement: `(n : Nat) : 0 + n = n`
- expected head: `exact`
- alt-config first-verified rank: {'raw': None}
- top-3 candidates:
  - `'exact rfl'`
  - `'rfl'`
  - `'exact Eq.refl _'`
- top-3 errors:
  - `/tmp/mini_elf_lean_rwu272dh.lean:2:2: error: Type mismatch`
  - `/tmp/mini_elf_lean_kxc7h6qf.lean:2:2: error: Tactic 'rfl' failed: The left-hand side`
  - `/tmp/claude-1000/mini_elf_lean_pvl8zbqy.lean:2:2: error: Type mismatch`

### `v18_nat_succ_inj` — nat_succ — `tactic_failed`
- statement: `(n m : Nat) (h : n.succ = m.succ) : n = m`
- expected head: `exact`
- alt-config first-verified rank: {'raw': None}
- top-3 candidates:
  - `'rw [h]'`
  - `'subst h\n  rfl'`
  - `'exact h ▸ rfl'`
- top-3 errors:
  - `/tmp/mini_elf_lean_i_3iky_0.lean:2:6: error: Tactic 'rewrite' failed: Did not find an occurrence of the pattern`
  - `/tmp/mini_elf_lean_326atd3o.lean:2:2: error: Tactic 'subst' failed: invalid equality proof, it is not of the form (x = t) or (t = x)`
  - `/tmp/mini_elf_lean_qw1zgho4.lean:2:8: error: invalid '▸' notation, expected result type of cast is `

### `v18_list_append_nil` — list — `tactic_failed`
- statement: `(α : Type) (xs : List α) : xs ++ [] = xs`
- expected head: `exact`
- alt-config first-verified rank: {'raw': None}
- top-3 candidates:
  - `'rfl'`
  - `'exact rfl'`
  - `'decide'`
- top-3 errors:
  - `/tmp/mini_elf_lean_r0yfg6s_.lean:2:2: error: Tactic 'rfl' failed: The left-hand side`
  - `/tmp/mini_elf_lean_nnnb7fmy.lean:2:2: error: Type mismatch`
  - `/tmp/claude-1000/mini_elf_lean_orlitinl.lean:2:2: error: Expected type must not contain free variables`
