# v24 failure examples

The **3 residual generator-bound theorems** that the v24 residual corpus
did **not** close (the other 5 of the original 8 are now solved — see
[`V24_RESIDUAL_ROW_RESULTS.md`](V24_RESIDUAL_ROW_RESULTS.md)). All 3 are
**disjunction / conjunction** shapes: `v18_or_inr` (`exact Or.inr hq` —
the model still emits the wrong hyp / a malformed two-line block),
`v18_or_elim_to_common` (or-elimination), and `v18_and_assoc_one` (nested
`⟨⟨h.1, h.2.1⟩, h.2.2⟩`). The v24 corpus *did* include verified
`or_intro` / `or_elim` / `conj_reassoc` families, but 5–10 examples each
were too few to shift the generator off its biased shapes — an
**insufficient-shape-diversity** residual, the v25 target. No state_after,
no manual oracle, no Mathlib.

## Failure-class tally
- `type_mismatch`: 2
- `wrong_var_name`: 1

## Per-theorem detail

### `v18_and_assoc_one` — conjunction — `type_mismatch`
- statement: `(p q r : Prop) (h : p ∧ q ∧ r) : (p ∧ q) ∧ r`
- expected head: `exact`
- alt-config first-verified rank: {'raw': None}
- top-3 candidates:
  - `'exact ⟨h.2, h.1⟩'`
  - `'exact ⟨⟨h.1, h.1⟩'`
  - `'exact ⟨⟨h.2, h.1⟩'`
- top-3 errors:
  - `/tmp/mini_elf_lean_de4f3k2h.lean:2:9: error: Application type mismatch: The argument`
  - `/tmp/claude-1000/mini_elf_lean_ql_obqkh.lean:3:0: error: unexpected end of input; expected '⟩'`
  - `/tmp/claude-1000/mini_elf_lean_22fsxmaj.lean:3:0: error: unexpected end of input; expected '⟩'`

### `v18_or_inr` — disjunction — `type_mismatch`
- statement: `(p q : Prop) (hq : q) : p ∨ q`
- expected head: `exact`
- alt-config first-verified rank: {'raw': None}
- top-3 candidates:
  - `'exact Or.inl hq'`
  - `'exact Or.inr hq'`
  - `'exact Or.intro hq'`
- top-3 errors:
  - `/tmp/mini_elf_lean_w584wep6.lean:2:15: error: Application type mismatch: The argument`
  - `timeout`
  - `/tmp/claude-1000/mini_elf_lean_em9d5uu5.lean:2:8: error(lean.unknownIdentifier): Unknown constant 'Or.intro'`

### `v18_or_elim_to_common` — disjunction — `wrong_var_name`
- statement: `(p q r : Prop) (h : p ∨ q) (hpr : p → r) (hqr : q → r) : r`
- expected head: `exact`
- alt-config first-verified rank: {'raw': None}
- top-3 candidates:
  - `'cases h with | inl hp => exact f hp hx'`
  - `'cases h with | inl hp => exact f hp | inr hq => exact Or.inl hq'`
  - `'cases h with | inl hp => exact f hp | inr hq => exact (h hp)'`
- top-3 errors:
  - `/tmp/claude-1000/mini_elf_lean_jvne7gjt.lean:2:33: error(lean.unknownIdentifier): Unknown identifier 'f'`
  - `/tmp/claude-1000/mini_elf_lean_4a2vb0_a.lean:2:33: error(lean.unknownIdentifier): Unknown identifier 'f'`
  - `/tmp/claude-1000/mini_elf_lean_gpx7z20l.lean:2:33: error(lean.unknownIdentifier): Unknown identifier 'f'`
