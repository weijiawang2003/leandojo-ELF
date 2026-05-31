# Mini-ELF v11 — failure examples (per-family LOFO)

Concrete beam outputs from `data/baselines/v11_family_lofo_eval/<fam>/<model>/predictions.jsonl`.
Each block is verbatim from disk; characters are unchanged. `OK` =
lean-cli verified, `FAIL` = lean rejected (or timed out).

## `forall_inst` — primary v11 target

Gold tactics: `exact h 7`, `exact h 3`, `exact h 5`, `exact h 9`,
`exact h 13`, `exact h 8` (twice). Hypothesis `h : ∀ x : Nat, x = N`
(varies). v8_lofo (0/7) → v11 (1/7, **+0.143 pass@5**).

### v8_lofo: never emits the `exact h <num>` schema

```
forall_inst_7_0  (gold: exact h 7)
  [0] FAIL [timeout]                    rcases h with ⟨n, hn⟩ \n   exact h
  [1] FAIL [timeout]                    exact h
  [2] FAIL [timeout]                    rcases h with ⟨n, hn⟩ \n   exact hq
  [3] FAIL [Tactic `rcases` …]          rcases h with ⟨n, hn⟩ \n   rfl
  [4] FAIL [Tactic `rcases` …]          rcases h with ⟨n, hn⟩ \n   exact rf
```

Mode: Mathlib `rcases` transplant (the v8 base pool has Mathlib-style
rows). The model has never seen `exact h N` with a literal `N`, so it
never tries it.

### v11: top-0 = `exact h 7` on the one theorem whose literal matches v10

```
forall_inst_7_0  (gold: exact h 7)
  [0] OK                                exact h 7              ← MATCH
  [1] FAIL [unexpected end]             rcases h with ⟨
  [2] FAIL [unsolved goals]             rcases h with h
  [3] FAIL [timeout]                    exact h
  [4] FAIL [Type mismatch]              exact h 4
```

```
forall_inst_13_6  (gold: exact h 13)
  [0] FAIL [timeout]                    exact h 4              ← wrong literal
  [1] FAIL [unknown ident]              rcases h w
  [2] FAIL [Type mismatch]              exact h 7              ← wrong literal
  [3] FAIL [Type mismatch]              exact h 5              ← wrong literal
  [4] FAIL [unknown ident]              cases h wi
```

Mode: **literal extrapolation failure.** v10's `instantiate_forall`
cells use literals `{3, 4, 5, 7}` and the identifier `p`. The held
`forall_inst` test theorems need `{3, 5, 7, 9, 13, 8}`. The model
correctly composes the SHAPE (`exact h <num>`) but cannot generalise
the literal — it draws from the in-train literal vocabulary and gets a
match exactly when the gold literal happens to be `7` (the one held
test theorem that aligns with v10's `nat_eq_7`).

```
forall_inst_3_0  (gold: exact h 3)   — v10 has `exact h 3`, but the
  [0] FAIL [timeout]                    exact h 4              ← wrong literal,
  [1] FAIL [unknown ident]              rcases h w                even though
  [2] FAIL [Type mismatch]              exact h                  v10's nat_eq_3
  [3] FAIL [unknown ident]              exact h w                supplies it
  [4] FAIL [Type mismatch]              exact h 7
```

Mode: **beam-rank failure**. The model knows `exact h 3` exists in
train (v10 `nat_eq_3`) but the beam ordering puts `exact h 4` and
`exact h 7` ahead of it. A reranker (v1-style verifier-aware) or a
literal-bias decoder would likely fix this.

## `rewrite_succ` — primary v11 target

Gold tactics: `rw [h]`, `exact congrArg Nat.succ h`,
`subst h\n  rfl`, `exact h ▸ rfl`. v8_lofo (0/5) → v11 (4/5,
**+0.800 pass@5**).

### v8_lofo: emits everything except `rw [h]`

```
rewrite_succ_nm  (gold: rw [h] | exact congrArg Nat.succ h | subst h \n   rfl | exact h ▸ rfl)
  [0] FAIL [Type mismatch]              exact h.symm
  [1] FAIL [Type mismatch]              exact Eq.refl
  [2] FAIL [Invalid project]            exact h.2
  [3] FAIL [Type mismatch]              exact rfl
  [4] FAIL [unknown ident]              exact Eq.reft
```

Mode: same as v8 matrix. The v8 base pool has *no* `rw [h]` for an
equality hypothesis at any point — the model has never seen the
tactic, so it doesn't try it.

### v11: top-0 = `rw [h]` on 4 of 5 unique theorems

```
rewrite_succ_nm  (gold includes rw [h])
  [0] OK                                rw [h]                 ← MATCH
  [1] FAIL [Invalid field n]            exact h.
  [2] FAIL [Type mismatch]              exact Eq
  [3] FAIL [Type mismatch]              exact h
  [4] FAIL [unexpected ident]           rw [h] h
```

```
rewrite_succ_xy   [0] OK rw [h]
rewrite_succ_kl   [0] OK rw [h]
rewrite_succ_ab   [2] OK rw [h]   ← lands at rank 2, pass@5 still wins
rewrite_succ_ij   [0] FAIL [timeout]  rw [h]   ← cold-start lean timeout
                  [3] FAIL [unexpected end]    rw [hns
                  ...
```

**The fifth theorem (`rewrite_succ_ij`) emitted the correct `rw [h]`
at beam rank 0 but the lean-cli verifier hit a 20 s cold-start timeout.**
The reported `pass@5 = 0.800` is therefore a lower bound — under a
warmer verifier the cell would have verified. Reported honestly as 0.800,
not retconned to 1.000.

## `exists_reconstruct` — secondary lift

Gold = `cases h with | intro n hn => exact ⟨n, hn⟩` (approximately).
v8_lofo (0.400, 2/5 verified) → v11 (0.800, 5/5 verified, **+0.400
pass@5**). The v10 `exists_elim` cells supply the exact tactic shape;
v11's beam now leads with it.

## `neg_exfalso` — precision lift only

Gold = `exact absurd hp hnp` family. Both v8_lofo and v11 verify 5 of
8 test theorems at pass@5 (no recall change), but **v11 pass@1 jumps
0.125 → 0.625**: v10's redundancy reorders the beam so the correct
tactic lands at rank 0 on more theorems. The 3 still-failing theorems
need shape variants v10 also lacks.

## `neg_imp_exfalso` — no movement

Gold = `intro hp\n  exact hnq (h hp)` family (the contrapositive
shape). Both v8_lofo and v11 verify 0/5. The v10 `contradiction`
redundancy cells use surface forms (`p ∧ ¬p`, `p → False`, `p ↔ False`)
that do NOT include the contrapositive `(p → q) → ¬q → ¬p` shape, so
v11 has no sibling to copy from on this family.

## Aggregate failure-mode counts (v11 top-5)

Hand-tallied across the 5 family folds' v11 `predictions.jsonl`:

| failure mode | rough count |
|---|---:|
| Mathlib transplant (`rcases h with ⟨…⟩`) | ~14 |
| Type mismatch (`exact h`, `exact rfl`, `exact h.symm`) | ~20 |
| Char-level truncation (`exact h.`, `rw [hns`, `cases h wi`) | ~12 |
| Wrong literal substitution (`exact h 4` for goal needing `exact h 13`) | ~10 |
| lean-cli cold-start timeout | 2–3 |

Mid-token truncation and Mathlib-transplant inherit unchanged from
v8/v10; literal-substitution is the new v11-visible failure mode, and
it's the one most directly addressable by a tokenizer/reranker change
in v12.
