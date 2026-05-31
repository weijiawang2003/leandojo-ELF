# v24 residual row-by-row results (Part 7)

The 8 v18 generator-bound theorems, v22 plus_exists → v24 broad+residual (`abstract` beam order). v22 had **no verified candidate in the top-10** for every one of these. **v24 fixes 5 / 8.**

| theorem | category | old fvr | new fvr | verifying candidate / reason |
|---|---|---|---|---|
| `v18_and_assoc_one` | conjunction | None | None | no verified candidate in v24 top-10 |
| `v18_or_inr` | disjunction | None | None | no verified candidate in v24 top-10 |
| `v18_or_elim_to_common` | disjunction | None | None | no verified candidate in v24 top-10 |
| `v18_neg_or_left` | negation | None | 0 | 'intro hgoal\n  exact h (Or.inl hgoal)' |
| `v18_exists_intro_eq` | exists | None | 8 | 'exact ⟨n, rfl⟩' |
| `v18_nat_zero_add` | nat_succ | None | 2 | 'simp' |
| `v18_nat_succ_inj` | nat_succ | None | 3 | 'exact Nat.succ.inj h' |
| `v18_list_append_nil` | list | None | 0 | 'simp' |
