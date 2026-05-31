# v23 failure examples

Residual failures on the fixed **v22 plus_exists** candidate pool after
the best v23 reranker — the theorems no *ranking* change can fix. Of the
48 broad-core theorems, **8 are generator-bound** (no verified candidate
anywhere in the top-10; reranking is powerless) and **1 is ranking-bound**
(`v18_neg_not_intro`: the verified `intro hp\n  exact absurd hp h` sits at
rank 3 but is feature-indistinguishable from failing siblings like
`intro hp\n  exact absurd (h hp)`, so the learned reranker does not lift
it). The per-theorem candidate/error detail below is the v22 generator's
raw beam (reranking changes only the order, not *which* candidates exist).
See [`V23_GENERATOR_BOUND_AUDIT.md`](V23_GENERATOR_BOUND_AUDIT.md) for the
full classification and the v24 (corpus-augmentation) direction. No
state_after, no manual oracle, no Mathlib.

## Failure-class tally
- `type_mismatch`: 3
- `wrong_var_name`: 3
- `tactic_failed`: 2

## Per-theorem detail

### `v18_and_assoc_one` — conjunction — `type_mismatch`
- statement: `(p q r : Prop) (h : p ∧ q ∧ r) : (p ∧ q) ∧ r`
- expected head: `exact`
- alt-config first-verified rank: {'abstract': None}
- top-3 candidates:
  - `'exact ⟨h.2, h.1⟩'`
  - `'rcases h with ⟨hp, hq⟩\n  exact ⟨hq'`
  - `'cases h with\n  | intro hp hq =>'`
- top-3 errors:
  - `/tmp/mini_elf_lean_de4f3k2h.lean:2:9: error: Application type mismatch: The argument`
  - `/tmp/claude-1000/mini_elf_lean_0cnen_8r.lean:4:0: error: unexpected end of input; expected '⟩'`
  - `/tmp/claude-1000/mini_elf_lean_a4wn41gj.lean:4:0: error: unexpected end of input; expected '?', '_' or '{'`

### `v18_or_inr` — disjunction — `wrong_var_name`
- statement: `(p q : Prop) (hq : q) : p ∨ q`
- expected head: `exact`
- alt-config first-verified rank: {'abstract': None}
- top-3 candidates:
  - `'left\n  exact hp\n  exact hq'`
  - `'exact Or.inr hp\n  exact hq'`
  - `'right\n  exact hp\n  exact hq'`
- top-3 errors:
  - `/tmp/mini_elf_lean_5o62t5g5.lean:3:8: error(lean.unknownIdentifier): Unknown identifier 'hp'`
  - `/tmp/claude-1000/mini_elf_lean_v5j4d9_c.lean:2:15: error(lean.unknownIdentifier): Unknown identifier 'hp'`
  - `/tmp/mini_elf_lean_btt_1qw0.lean:3:8: error(lean.unknownIdentifier): Unknown identifier 'hp'`

### `v18_or_elim_to_common` — disjunction — `wrong_var_name`
- statement: `(p q r : Prop) (h : p ∨ q) (hpr : p → r) (hqr : q → r) : r`
- expected head: `exact`
- alt-config first-verified rank: {'abstract': None}
- top-3 candidates:
  - `'cases h with | inl ht => exact hpq hx'`
  - `'cases h with\n  | inl hp => exact hpq hx'`
  - `'cases h with\n  | inl ht => exact hpq hx'`
- top-3 errors:
  - `/tmp/claude-1000/mini_elf_lean_5q4k2t6p.lean:2:33: error(lean.unknownIdentifier): Unknown identifier 'hpq'`
  - `/tmp/claude-1000/mini_elf_lean_ngo2sa99.lean:3:20: error(lean.unknownIdentifier): Unknown identifier 'hpq'`
  - `/tmp/claude-1000/mini_elf_lean_c7utw338.lean:3:20: error(lean.unknownIdentifier): Unknown identifier 'hpq'`

### `v18_neg_or_left` — negation — `type_mismatch`
- statement: `(p q : Prop) (h : ¬(p ∨ q)) : ¬p`
- expected head: `intro`
- alt-config first-verified rank: {'abstract': None}
- top-3 candidates:
  - `'exact fun hp => h (h hp)'`
  - `'exact fun hp => absurd hp hnp\n  | inr'`
  - `'exact fun hp => absurd hp hnp => h'`
- top-3 errors:
  - `/tmp/claude-1000/mini_elf_lean_1ewperfe.lean:2:23: error: Application type mismatch: The argument`
  - `/tmp/claude-1000/mini_elf_lean_6vf8jlet.lean:2:28: error(lean.unknownIdentifier): Unknown identifier 'hnp'`
  - `/tmp/claude-1000/mini_elf_lean_39u7ce7_.lean:2:28: error(lean.unknownIdentifier): Unknown identifier 'hnp'`

### `v18_exists_intro_eq` — exists — `wrong_var_name`
- statement: `(n : Nat) : ∃ m, n = m`
- expected head: `exact`
- alt-config first-verified rank: {'abstract': None}
- top-3 candidates:
  - `'exact ⟨m, rfl⟩'`
  - `'refine ⟨m, ?_⟩\n  rfl'`
  - `'rcases h with ⟨n, hn⟩'`
- top-3 errors:
  - `/tmp/mini_elf_lean_fhx4aorr.lean:2:9: error(lean.unknownIdentifier): Unknown identifier 'm'`
  - `/tmp/mini_elf_lean_q6euh7yy.lean:2:10: error(lean.unknownIdentifier): Unknown identifier 'm'`
  - `/tmp/claude-1000/mini_elf_lean_eoqqlruq.lean:2:9: error(lean.unknownIdentifier): Unknown identifier 'h'`

### `v18_nat_zero_add` — nat_succ — `type_mismatch`
- statement: `(n : Nat) : 0 + n = n`
- expected head: `exact`
- alt-config first-verified rank: {'abstract': None}
- top-3 candidates:
  - `'exact rfl'`
  - `'exact Eq.refl _'`
  - `'exact ⟨m, rfl⟩'`
- top-3 errors:
  - `/tmp/mini_elf_lean_rwu272dh.lean:2:2: error: Type mismatch`
  - `/tmp/claude-1000/mini_elf_lean_pvl8zbqy.lean:2:2: error: Type mismatch`
  - `/tmp/claude-1000/mini_elf_lean_wmtocpmo.lean:2:8: error: Insufficient number of fields for '⟨...⟩' constructor: Constructor 'Eq.refl' does n`

### `v18_nat_succ_inj` — nat_succ — `tactic_failed`
- statement: `(n m : Nat) (h : n.succ = m.succ) : n = m`
- expected head: `exact`
- alt-config first-verified rank: {'abstract': None}
- top-3 candidates:
  - `'rw [h]'`
  - `'subst h\n  rfl'`
  - `'exact congrArg Nat.succ'`
- top-3 errors:
  - `/tmp/mini_elf_lean_i_3iky_0.lean:2:6: error: Tactic 'rewrite' failed: Did not find an occurrence of the pattern`
  - `/tmp/mini_elf_lean_326atd3o.lean:2:2: error: Tactic 'subst' failed: invalid equality proof, it is not of the form (x = t) or (t = x)`
  - `/tmp/mini_elf_lean_hnriyczr.lean:2:2: error: Type mismatch`

### `v18_list_append_nil` — list — `tactic_failed`
- statement: `(α : Type) (xs : List α) : xs ++ [] = xs`
- expected head: `exact`
- alt-config first-verified rank: {'abstract': None}
- top-3 candidates:
  - `'rfl'`
  - `'exact rfl'`
  - `'exact Eq.refl'`
- top-3 errors:
  - `/tmp/mini_elf_lean_r0yfg6s_.lean:2:2: error: Tactic 'rfl' failed: The left-hand side`
  - `/tmp/mini_elf_lean_nnnb7fmy.lean:2:2: error: Type mismatch`
  - `/tmp/mini_elf_lean_sdhg2da4.lean:2:2: error: Type mismatch`
