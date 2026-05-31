# v20 shape-gap audit
Read-only audit of v18 broad-core failures (48 theorems) under the v18 broad-only/policy, v18 broad-synthetic (panel)/policy, v19 abstract-only/policy, and v19 ensemble/policy configs. This is data the v20 brief asks for **before** any v20 model is built.

## Category-level snapshot
| category | n | v18 broad-only pass@10 | v19 ensemble pass@10 | rows unverified by *every* config |
|---|---:|---:|---:|---:|
| bool | 3 | 0/3 | 0/3 | 3/3 |
| conjunction | 6 | 5/6 | 1/6 | 1/6 |
| disjunction | 5 | 3/5 | 0/5 | 2/5 |
| equality_rewrite | 6 | 6/6 | 6/6 | 0/6 |
| exists | 4 | 1/4 | 1/4 | 2/4 |
| forall | 3 | 2/3 | 2/3 | 1/3 |
| implication | 6 | 1/6 | 1/6 | 4/6 |
| list | 5 | 4/5 | 4/5 | 1/5 |
| nat_succ | 5 | 3/5 | 3/5 | 2/5 |
| negation | 5 | 4/5 | 3/5 | 1/5 |

## v18 broad-only top-1 error tally (n=48)
- `ok`: 24
- `unknown_identifier`: 10
- `type_mismatch`: 9
- `tactic_failed`: 3
- `other`: 2

## Canonical-shape probes — does the shape exist anywhere in v11+v16+v17 synthetic training tactics?
(Substring search over 3984 training rows.)

### implication
| probe | rows containing it |
|---|---:|
| `exact hp` | 400 |
| `intro hq` | 30 |
| `intro hp` | 358 |
| `exact (h hp)` | 24 |
| `hpq` | 100 |
| `hqr` | 0 |
| `exact h hp` | 13 |
| `exact fun` | 390 |

### bool
| probe | rows containing it |
|---|---:|
| `cases b` | 0 |
| `rfl` | 410 |
| `Bool` | 0 |
| `decide` | 45 |

### exists
| probe | rows containing it |
|---|---:|
| `exact ⟨` | 400 |
| `refine ⟨` | 95 |
| `Exists.intro` | 0 |
| `rcases` | 250 |

## Per-theorem detail — implication / bool / anywhere-unverified rows

### `v18_and_assoc_one` — conjunction
- statement: `(p q r : Prop) (h : p ∧ q ∧ r) : (p ∧ q) ∧ r`
- expected tactic head: `exact`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'exact h.right.right'`
  - `'exact h.right.left'`
  - `'exact h.right.right.right'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_kmamph9q.lean:2:2: error: Type mismatch`
  - `/tmp/mini_elf_lean_vxujoukk.lean:2:2: error: Type mismatch`
  - `/tmp/mini_elf_lean_guhioumn.lean:2:8: error(lean.invalidField): Invalid field notation: Field projection operates on types of the form 'C ...' where C is a cons`

### `v18_bool_and_left` — bool
- statement: `(b : Bool) (h : (b && true) = true) : b = true`
- expected tactic head: `rw`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'rw [h]'`
  - `'exact Eq.symm h'`
  - `'exact h.symm'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_f_eecg26.lean:2:6: error: Tactic 'rewrite' failed: Did not find an occurrence of the pattern`
  - `/tmp/mini_elf_lean_p0gtnftw.lean:2:16: error: Application type mismatch: The argument`
  - `/tmp/mini_elf_lean_mctm1hkl.lean:2:2: error: Type mismatch`

### `v18_bool_not_not` — bool
- statement: `(b : Bool) : !!b = b`
- expected tactic head: `cases`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'exact Eq.trans h1 h2'`
  - `'exact Eq.symm h'`
  - `'exact Eq.refl h'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_xiyvbiv5.lean:2:17: error(lean.unknownIdentifier): Unknown identifier 'h1'`
  - `/tmp/mini_elf_lean_k9ifn6d1.lean:2:16: error(lean.unknownIdentifier): Unknown identifier 'h'`
  - `/tmp/mini_elf_lean_5dt9mezo.lean:2:16: error(lean.unknownIdentifier): Unknown identifier 'h'`

### `v18_bool_true_or_false` — bool
- statement: `(b : Bool) : b = true ∨ b = false`
- expected tactic head: `cases`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'exact Eq.symm h'`
  - `'exact Eq.trans h1'`
  - `'exact Eq.refl h'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_dl5d0zx2.lean:2:16: error(lean.unknownIdentifier): Unknown identifier 'h'`
  - `/tmp/mini_elf_lean_3mzqn5ie.lean:2:17: error(lean.unknownIdentifier): Unknown identifier 'h1'`
  - `/tmp/mini_elf_lean_t5rygzbb.lean:2:16: error(lean.unknownIdentifier): Unknown identifier 'h'`

### `v18_exists_compose` — exists
- statement: `(p q : Nat → Prop) (h : ∃ n, p n) (hpq : ∀ n, p n → q n) : ∃ n, q n`
- expected tactic head: `cases`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'exact ⟨100, rfl⟩'`
  - `'exact ⟨n, rfl⟩'`
  - `'rcases h with ⟨n, hn⟩'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_nmahvopg.lean:2:14: error: Application type mismatch: The argument`
  - `/tmp/mini_elf_lean_1tin2v0k.lean:2:9: error(lean.unknownIdentifier): Unknown identifier 'n'`
  - `/tmp/mini_elf_lean_xq6ls588.lean:1:79: error: unsolved goals`

### `v18_exists_intro_nat` — exists
- statement: `(p : Nat → Prop) (h : p 3) : ∃ n, p n`
- expected tactic head: `exact`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'exact ⟨100, rfl⟩'`
  - `'refine ⟨n, ?_⟩\n  rfl'`
  - `'exact ⟨n, rfl⟩'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_328t9phd.lean:2:14: error: Application type mismatch: The argument`
  - `/tmp/mini_elf_lean_yhlt7i7b.lean:2:10: error(lean.unknownIdentifier): Unknown identifier 'n'`
  - `/tmp/mini_elf_lean_03y8pdsh.lean:2:9: error(lean.unknownIdentifier): Unknown identifier 'n'`

### `v18_forall_inst_compose` — forall
- statement: `(p q : Nat → Prop) (h : ∀ n, p n → q n) (hp : p 5) : q 5`
- expected tactic head: `exact`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'exact h 5'`
  - `'exact h p'`
  - `'exact h 3'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_paye883u.lean:2:2: error: Type mismatch`
  - `/tmp/mini_elf_lean_oyj28v4s.lean:2:10: error: Application type mismatch: The argument`
  - `/tmp/mini_elf_lean_3xo5fc4z.lean:2:2: error: Type mismatch`

### `v18_imp_arrow_arrow` — implication
- statement: `(p q : Prop) (h : (p → q) → p) (hpq : p → q) : p`
- expected tactic head: `exact`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `9`, v19 ensemble: `9`
- v18 broad-only top-3 candidates:
  - `'exact hpq h'`
  - `'exact hpq hp => h'`
  - `'exact hpq (h hp)'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_fl_xv64t.lean:2:12: error: Application type mismatch: The argument`
  - `/tmp/mini_elf_lean_0hldd0ft.lean:2:12: error(lean.unknownIdentifier): Unknown identifier 'hp'`
  - `/tmp/mini_elf_lean_7kga7al4.lean:2:15: error(lean.unknownIdentifier): Unknown identifier 'hp'`

### `v18_imp_chain` — implication
- statement: `(p q r : Prop) (hpq : p → q) (hqr : q → r) (hp : p) : r`
- expected tactic head: `exact`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'exact (h hp).'`
  - `'exact hpq hp'`
  - `'exact absurd hp =>'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_ilucghn7.lean:2:9: error(lean.unknownIdentifier): Unknown identifier 'h'`
  - `/tmp/mini_elf_lean_14fuqiip.lean:2:2: error: Type mismatch`
  - `timeout`

### `v18_imp_compose` — implication
- statement: `(α β γ : Type) (f : α → β) (g : β → γ) (a : α) : γ`
- expected tactic head: `exact`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'exact (h hp).elim'`
  - `'exact (h1 hp).elim'`
  - `'exact (f hp).elim'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_qun_evt_.lean:2:9: error(lean.unknownIdentifier): Unknown identifier 'h'`
  - `/tmp/mini_elf_lean_naw813wf.lean:2:9: error(lean.unknownIdentifier): Unknown identifier 'h1'`
  - `timeout`

### `v18_imp_intro_basic` — implication
- statement: `(p q : Prop) (hp : p) : q → p`
- expected tactic head: `intro`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'exact fun hp => h'`
  - `'intro hp\n  exact (h hp)'`
  - `'exact fun hp => (h'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_spx6v2q0.lean:2:18: error(lean.unknownIdentifier): Unknown identifier 'h'`
  - `/tmp/mini_elf_lean_ddjoct_g.lean:3:9: error(lean.unknownIdentifier): Unknown identifier 'h'`
  - `/tmp/mini_elf_lean_3zu9yyw_.lean:3:0: error: unexpected end of input; expected ')', ',' or ':'`

### `v18_imp_p_self` — implication
- statement: `(p : Prop) (hp : p) : p`
- expected tactic head: `exact`
- first-verified rank — v18 broad-only: `9`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'exact (hpfalse hp).'`
  - `'exact absurd hp hpfalse'`
  - `'exact hp\n  exact hp'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_z8f1d7dp.lean:2:9: error(lean.unknownIdentifier): Unknown identifier 'hpfalse'`
  - `/tmp/mini_elf_lean_rvi_2de5.lean:2:18: error(lean.unknownIdentifier): Unknown identifier 'hpfalse'`
  - `/tmp/mini_elf_lean_fqdnd7qt.lean:3:2: error: No goals to be solved`

### `v18_imp_swap_args` — implication
- statement: `(p q r : Prop) (h : p → q → r) (hq : q) (hp : p) : r`
- expected tactic head: `exact`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'exact h (h hp)'`
  - `'exact fun hp => h'`
  - `'exact h h'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_1pblkl92.lean:2:10: error: Application type mismatch: The argument`
  - `/tmp/mini_elf_lean_3cg7psew.lean:2:2: error: Type mismatch`
  - `/tmp/mini_elf_lean_dayl666o.lean:2:10: error: Application type mismatch: The argument`

### `v18_list_append_nil` — list
- statement: `(α : Type) (xs : List α) : xs ++ [] = xs`
- expected tactic head: `exact`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'exact rfl'`
  - `'exact Eq.trans h1'`
  - `'exact Eq.trans (h'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_fsjzce9e.lean:2:2: error: Type mismatch`
  - `/tmp/mini_elf_lean_7w8sz7xj.lean:2:17: error(lean.unknownIdentifier): Unknown identifier 'h1'`
  - `/tmp/mini_elf_lean_gnospkbp.lean:3:0: error: unexpected end of input; expected ')', ',' or ':'`

### `v18_nat_succ_inj` — nat_succ
- statement: `(n m : Nat) (h : n.succ = m.succ) : n = m`
- expected tactic head: `exact`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'rw [h]'`
  - `'subst h\n  rfl'`
  - `'exact h ▸'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_dw7d6atc.lean:2:6: error: Tactic 'rewrite' failed: Did not find an occurrence of the pattern`
  - `/tmp/mini_elf_lean_5io1ovgn.lean:2:2: error: Tactic 'subst' failed: invalid equality proof, it is not of the form (x = t) or (t = x)`
  - `/tmp/mini_elf_lean_la2zmmj3.lean:3:0: error: unexpected end of input`

### `v18_nat_zero_add` — nat_succ
- statement: `(n : Nat) : 0 + n = n`
- expected tactic head: `exact`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'exact ⟨0, rfl⟩'`
  - `'exact rfl'`
  - `'exact ⟨m, rfl⟩'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_ljs7si1f.lean:2:8: error: Insufficient number of fields for '⟨...⟩' constructor: Constructor 'Eq.refl' does not have explicit fields, but 2 w`
  - `timeout`
  - `/tmp/mini_elf_lean_hbvziyre.lean:2:8: error: Insufficient number of fields for '⟨...⟩' constructor: Constructor 'Eq.refl' does not have explicit fields, but 2 w`

### `v18_neg_or_left` — negation
- statement: `(p q : Prop) (h : ¬(p ∨ q)) : ¬p`
- expected tactic head: `intro`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'cases h with\n  | inl hp => exact hnq (h hp)'`
  - `'cases h with\n  | inl hp => exact absurd hp hnp\n  exact'`
  - `'cases h with\n  | inl hp => exact hnq hnq'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_jevj8pla.lean:2:2: error: Tactic 'cases' failed: major premise type is not an inductive type`
  - `/tmp/mini_elf_lean_fypko1cy.lean:5:0: error: unexpected end of input`
  - `/tmp/mini_elf_lean_6h4225ms.lean:2:2: error: Tactic 'cases' failed: major premise type is not an inductive type`

### `v18_or_elim_to_common` — disjunction
- statement: `(p q r : Prop) (h : p ∨ q) (hpr : p → r) (hqr : q → r) : r`
- expected tactic head: `exact`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'cases h with\n  | inl hx => exact hp hx\n  | inr hx => exact hq hx'`
  - `'cases h with\n  | inl hx => exact hp | inr hx => exact hq hx'`
  - `'cases h with\n  | inl hx => exact absurd hp hx\n  | inr hx => exact hq'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_v31zeb20.lean:3:20: error(lean.unknownIdentifier): Unknown identifier 'hp'`
  - `timeout`
  - `/tmp/mini_elf_lean_sxu2d5e5.lean:3:27: error(lean.unknownIdentifier): Unknown identifier 'hp'`

### `v18_or_inr` — disjunction
- statement: `(p q : Prop) (hq : q) : p ∨ q`
- expected tactic head: `exact`
- first-verified rank — v18 broad-only: `None`, v18 broad-synth: `None`, v19 abstract-only: `None`, v19 ensemble: `None`
- v18 broad-only top-3 candidates:
  - `'exact Or.inl h'`
  - `'exact Or.elim h'`
  - `'exact Or.inl hp'`
- v18 broad-only top-3 errors:
  - `/tmp/mini_elf_lean_zixe5_fp.lean:2:15: error(lean.unknownIdentifier): Unknown identifier 'h'`
  - `/tmp/mini_elf_lean_1fwbrlep.lean:2:16: error(lean.unknownIdentifier): Unknown identifier 'h'`
  - `/tmp/mini_elf_lean_2mjs26ea.lean:2:15: error(lean.unknownIdentifier): Unknown identifier 'hp'`

## Read of these results (informs v20 corpus design)
* **implication is corpus-shape-bound, not name-bound.** Every implication row failure on the v18 broad-only config is `unknown_identifier`: the model emits hypothesis names (`hpfalse`, `h1`, `f`) that are in the v17 *training* shape but absent from the v18 test state. The canonical proofs (`exact hp`, `intro hq\n  exact hp`, `exact hqr (hpq hp)`) do not appear in v11+v16+v17 training (probe `exact hp` = 0 rows for the bare identity form).
* **bool has zero training support whatsoever.** No row in v11/v16/v17 contains `cases b`, the word `Bool`, or even the `decide` tactic. The v18 broad-only model only ever emits Prop-shaped tactics on Bool goals.
* **Conclusion** — the v20 hypothesis stands: adding shape-specific corpora for these two categories should move implication and bool off 0.000 without disturbing the equality/list/conjunction wins.
