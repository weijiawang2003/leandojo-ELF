# v23 residual generator-bound audit (Part 6)

After the best v23 reranker on the fixed `v22_general_plus_exists_eval` pool (48 broad-core theorems). pass@10 is the generator ceiling; reranking can only move verified candidates that already exist in the top-10.

## Classification

| class | count |
|---|---:|
| solved@1 | 39 |
| ranking_bound | 1 |
| generator_bound | 8 |

## Generator-bound theorems by dominant error class

- `unknown_identifier`: 4
- `other`: 3
- `type_mismatch`: 1

## Per-theorem

| theorem | category | class | raw_fvr | best_v23_fvr | dom_error |
|---|---|---|---|---|---|
| v18_imp_p_self | implication | solved@1 | 0 | 0 | ok |
| v18_imp_intro_basic | implication | solved@1 | 0 | 0 | ok |
| v18_imp_chain | implication | solved@1 | 0 | 0 | ok |
| v18_imp_swap_args | implication | solved@1 | 0 | 0 | ok |
| v18_imp_compose | implication | solved@1 | 0 | 0 | ok |
| v18_imp_arrow_arrow | implication | solved@1 | 0 | 0 | ok |
| v18_and_intro | conjunction | solved@1 | 0 | 0 | ok |
| v18_and_left | conjunction | solved@1 | 0 | 0 | ok |
| v18_and_right | conjunction | solved@1 | 0 | 0 | ok |
| v18_and_swap | conjunction | solved@1 | 0 | 0 | ok |
| v18_and_assoc_one | conjunction | generator_bound | None | None | type_mismatch |
| v18_and_proj_3rd | conjunction | solved@1 | 0 | 0 | ok |
| v18_or_inl | disjunction | solved@1 | 0 | 0 | ok |
| v18_or_inr | disjunction | generator_bound | None | None | unknown_identifier |
| v18_or_swap | disjunction | solved@1 | 0 | 0 | ok |
| v18_or_elim_to_common | disjunction | generator_bound | None | None | unknown_identifier |
| v18_or_constant | disjunction | solved@1 | 0 | 0 | ok |
| v18_neg_not_intro | negation | ranking_bound | 3 | 3 | ok |
| v18_neg_absurd | negation | solved@1 | 0 | 0 | ok |
| v18_neg_double_in | negation | solved@1 | 0 | 0 | ok |
| v18_neg_modus_tollens | negation | solved@1 | 0 | 0 | ok |
| v18_neg_or_left | negation | generator_bound | None | None | unknown_identifier |
| v18_eq_refl_nat | equality_rewrite | solved@1 | 0 | 0 | ok |
| v18_eq_symm | equality_rewrite | solved@1 | 0 | 0 | ok |
| v18_eq_trans | equality_rewrite | solved@1 | 0 | 0 | ok |
| v18_eq_subst_lhs | equality_rewrite | solved@1 | 0 | 0 | ok |
| v18_eq_subst_rhs | equality_rewrite | solved@1 | 0 | 0 | ok |
| v18_eq_double_apply | equality_rewrite | solved@1 | 0 | 0 | ok |
| v18_exists_intro_nat | exists | solved@1 | 0 | 0 | ok |
| v18_exists_intro_eq | exists | generator_bound | None | None | unknown_identifier |
| v18_exists_relabel | exists | solved@1 | 0 | 0 | ok |
| v18_exists_compose | exists | solved@1 | 0 | 0 | ok |
| v18_forall_inst_at_7 | forall | solved@1 | 0 | 0 | ok |
| v18_forall_inst_compose | forall | solved@1 | 0 | 0 | ok |
| v18_forall_to_arrow | forall | solved@1 | 0 | 0 | ok |
| v18_nat_succ_unfold | nat_succ | solved@1 | 0 | 0 | ok |
| v18_nat_zero_add | nat_succ | generator_bound | None | None | other |
| v18_nat_add_zero | nat_succ | solved@1 | 0 | 0 | ok |
| v18_nat_succ_inj | nat_succ | generator_bound | None | None | other |
| v18_nat_add_one_eq_succ | nat_succ | solved@1 | 0 | 0 | ok |
| v18_bool_true_or_false | bool | solved@1 | 0 | 0 | ok |
| v18_bool_and_left | bool | solved@1 | 0 | 0 | ok |
| v18_bool_not_not | bool | solved@1 | 0 | 0 | ok |
| v18_list_append_nil | list | generator_bound | None | None | other |
| v18_list_nil_append | list | solved@1 | 0 | 0 | ok |
| v18_list_length_cons | list | solved@1 | 2 | 0 | ok |
| v18_list_singleton_len | list | solved@1 | 0 | 0 | ok |
| v18_list_head_some | list | solved@1 | 0 | 0 | ok |

## v24 direction: **generator/corpus-bound**

The residual broad-core gap is dominated by **generator_bound** theorems (no verified candidate in the top-10), which **no reranker can fix**. v24 should therefore be **corpus augmentation / generation** (the v22 exists-corpus recipe applied to the residual categories), not more ranking work. Ranking-bound theorems are the (small) headroom v23 addresses.
