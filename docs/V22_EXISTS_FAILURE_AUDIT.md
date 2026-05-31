# v22 exists failure audit

Read-only audit of the v18 broad-core `exists` category (the most fragile: 0.250 baseline, 0.000 under both v21 single-retrain and capacity).

## Training-pool probes (v21 broad-plus+forall pool)

- rows with anonymous constructor `⟨...⟩`: 141
- rows with `cases ... with` + `intro`: 11
- rows tagged exists category/operation: 34
- pool total: 2776

## Per-theorem detail

### `v18_exists_compose` — train

- statement: `(p q : Nat → Prop) (h : ∃ n, p n) (hpq : ∀ n, p n → q n) : ∃ n, q n`
- expected head: `cases`
- first-verified rank — v20: `None`, routed: `None`
- v20 top-3 candidates:
  - `'rcases h with ⟨n, hpq⟩\n  exact hpq'`
  - `'rcases h with ⟨n, hpq⟩\n  exact hq'`
  - `'rcases h with ⟨n, hpq⟩ => exact ⟨n,'`
- v20 top-3 errors:
  - `/tmp/mini_elf_lean_r5mqomez.lean:3:2: error: Type mismatch`
  - `/tmp/mini_elf_lean_ta9w552g.lean:3:8: error(lean.unknownIdentifier): Unknown identifier 'hq'`
  - `/tmp/mini_elf_lean_98j3wcot.lean:1:79: error: unsolved goals`

### `v18_exists_intro_eq` — test

- statement: `(n : Nat) : ∃ m, n = m`
- expected head: `exact`
- first-verified rank — v20: `0`, routed: `0`
- v20 top-3 candidates:
  - `'refine ⟨n, ?_⟩\n  rfl'`
  - `'refine ⟨0, ?_⟩\n  rfl'`
  - `'refine ⟨3, ?_⟩\n  rfl'`
- v20 top-3 errors:
  - ``
  - `/tmp/mini_elf_lean_a0eknmi2.lean:3:2: error: Tactic 'rfl' failed: The left-hand side`
  - `/tmp/mini_elf_lean_nmejzc5t.lean:3:2: error: Tactic 'rfl' failed: The left-hand side`

### `v18_exists_intro_nat` — val

- statement: `(p : Nat → Prop) (h : p 3) : ∃ n, p n`
- expected head: `exact`
- first-verified rank — v20: `None`, routed: `None`
- v20 top-3 candidates:
  - `'refine ⟨n, ?_⟩\n  rfl'`
  - `'refine ⟨n, ?_⟩\n  | ⟨n, ?_⟩'`
  - `'rcases h with ⟨hp, hq⟩\n  exact hq'`
- v20 top-3 errors:
  - `/tmp/mini_elf_lean_so5trlb7.lean:2:10: error(lean.unknownIdentifier): Unknown identifier 'n'`
  - `/tmp/mini_elf_lean_hoy1ea0u.lean:2:10: error(lean.unknownIdentifier): Unknown identifier 'n'`
  - `/tmp/mini_elf_lean_uwyvm1ji.lean:2:16: error: Tactic 'rcases' failed: 'h : p 3' is not an inductive datatype`

### `v18_exists_relabel` — train

- statement: `(p : Nat → Prop) (h : ∃ n, p n) : ∃ m, p m`
- expected head: `exact`
- first-verified rank — v20: `None`, routed: `None`
- v20 top-3 candidates:
  - `'rcases h with ⟨n, hp⟩\n  exact hp'`
  - `'rcases h with ⟨n, hp, hq⟩\n  exact hq'`
  - `'rcases h with ⟨n, hp, hq⟩\n  exact hp'`
- v20 top-3 errors:
  - `/tmp/mini_elf_lean_nvymtvhl.lean:3:2: error: Type mismatch`
  - `/tmp/mini_elf_lean_thb092yy.lean:2:16: error: Tactic 'rcases' failed: 'h✝ : p n' is not an inductive datatype`
  - `/tmp/mini_elf_lean_a0t_onyf.lean:2:16: error: Tactic 'rcases' failed: 'h✝ : p n' is not an inductive datatype`

## Needed proof shapes (core Lean)

- `∃ n, p n` from `h : p k` → `exact ⟨k, h⟩` (anonymous-constructor witness intro)
- `∃ m, n = m` → `exact ⟨n, rfl⟩` (reflexive witness)
- `∃ n, p n` from `h : ∃ n, p n` → `exact h` / `cases h with | intro n hn => exact ⟨n, hn⟩`
- compose: `cases h with | intro n hn => exact ⟨n, hpq n hn⟩`

## Read

The exists category needs **witness-introduction** shapes (`exact ⟨witness, proof⟩`) and **exists-elimination** (`cases h with | intro ...`). The v22 exists corpus (Part 3b) supplies these with varied witnesses and predicate names so a single model can learn witness-copy without overfitting to a fixed literal set (the v8-era `{0,1,2}`-only limitation).
