# V24 residual shape corpus report (Parts 2-3)

v23 proved the broad-core residual is **generator-bound**: 8 v18 theorems
have no verified candidate in the v22 plus_exists top-10, so no reranker
can reach them. v24 adds a small, **lean-cli-verified, core-Lean** shape
corpus — one family per generator-bound failure — and retrains the broad
generator (no ranking work, per the v23 finding).

## Verification result (direct toolchain binary, warm)

- planned theorems: **69**
- candidates proposed: **163** · **verified: 163 / 163** · failed: 0 ·
  timeout: 0
- **zero-success theorems: 0** · v18 name-guard drops: 0 · v18
  triple-guard drops: 0
- categories covered: conjunction, disjunction, exists, list, nat_succ,
  negation

## Families (target failure → verified core-Lean shape)

| family | theorems | verified | target v18 failure | shape |
|---|---:|---:|---|---|
| or_intro | 10 | 25 | `or_inr` | `exact Or.inl/inr h` / `left`/`right` |
| or_elim | 5 | 15 | `or_elim_to_common` | `Or.elim h f g` / cases inl/inr |
| conj_reassoc | 10 | 20 | `and_assoc_one` | `⟨⟨h.1,h.2.1⟩,h.2.2⟩`, conj swap |
| neg_of_or | 10 | 20 | `neg_or_left` | `intro hgoal; exact h (Or.inl hgoal)` |
| exists_eq_rev | 10 | 20 | `exists_intro_eq` | `exact ⟨n, rfl⟩` (reversed-eq witness) |
| nat_zero_add | 9 | 23 | `nat_zero_add` | `Nat.zero_add n` / `omega` / `simp` |
| nat_succ_inj | 5 | 15 | `nat_succ_inj` | `Nat.succ.inj h` / `injection h` / `omega` |
| list_append_nil | 10 | 25 | `list_append_nil` | `List.append_nil xs` / `simp` (+ nil_append) |

## Honesty

- **core Lean only, no Mathlib** — every tactic typechecks against Init
  (`Nat.zero_add`, `Nat.succ.inj`, `List.append_nil`, `omega`, `simp` are
  all core in Lean 4.30); confirmed by lean-cli.
- every candidate **lean-cli verified** before becoming a training row;
  no mock, no unverified candidate counted as a positive.
- **no manual oracle** (candidates are corpus targets verified by Lean,
  never decoder outputs), **no state_after**, **no v10-leakage**.
- v18 leakage-guarded: theorem names are `v24_*`; variable / proposition /
  hypothesis names are deliberately disjoint from v18 (`a/b/c`, `i/j/k`,
  `ys/zs`, `hgoal`, …) and a (statement, state, tactic) triple guard
  catches any accidental overlap (0 drops). The intro name `hgoal` is
  chosen disjoint from the hypothesis-name pool so it never shadows the
  hypothesis (an earlier collision on the `hx` name was fixed).

Artifacts: `data/seeds/v24_residual_shape_seeds.jsonl`,
`data/manual/v24_residual_shape_candidates.jsonl`,
`data/processed/v24_residual_shape_corpus/`.
