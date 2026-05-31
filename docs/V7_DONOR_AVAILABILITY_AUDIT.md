# Mini-ELF v7 — donor-availability audit (planner-blind, current split)

> **Scope.** Documents the donor structure behind v6's pass@5 1.00. The current split is `family_interpolation`: every test family also has members in train, so the retriever can reuse a *same-family* donor (one numeric/identifier edit from the answer). This audit measures how much of v6's success rides on that, by also verifying candidates when **same-family donors are forbidden at retrieval time** (`forbid_same_family`) — a preview of the Part-3 family-holdout regime on the rich split. Real lean-cli verification; no `state_after`; no new templates; example reuse, not reasoning.

## 1. Corpus donor conditions

- test rows: **84** (32 theorems)
- rows with a **same-family** donor in train: **84/84**
- rows with a **same-operation** donor in train: **75/84**
- rows whose **proof schema** is present in train: **84/84**
- rows that **require numeric adaptation** (literal absent from a same-schema train donor): **11/84**

## 2. Verified pass@k — full retriever vs cross-family-only

| condition | pass@1 | pass@5 |
| --- | --- | --- |
| v6 (same-family donors allowed) | 1.000 | 1.000 |
| v6 — same-family donors **forbidden** | 0.000 | 0.000 |

- v6 rank-0 donor is **same-family** in **1.000** of test rows (retrieval prefers the same-family donor when it exists).
- with same-family donors forbidden, **0/84** rows still find a verifying candidate from a *cross-family* donor.

## 3. pass@k by family (v6 vs cross-family-only)

| family | n | v6 @1 | v6 @5 | xfam @1 | xfam @5 |
| --- | --- | --- | --- | --- | --- |
| exists_elim_conj | 8 | 1.000 | 1.000 | 0.000 | 0.000 |
| exists_elim_prop | 9 | 1.000 | 1.000 | 0.000 | 0.000 |
| exists_reconstruct | 9 | 1.000 | 1.000 | 0.000 | 0.000 |
| forall_inst | 3 | 1.000 | 1.000 | 0.000 | 0.000 |
| neg_contrapositive | 6 | 1.000 | 1.000 | 0.000 | 0.000 |
| neg_double_intro | 6 | 1.000 | 1.000 | 0.000 | 0.000 |
| neg_exfalso | 16 | 1.000 | 1.000 | 0.000 | 0.000 |
| neg_imp_exfalso | 9 | 1.000 | 1.000 | 0.000 | 0.000 |
| neg_or_cases | 6 | 1.000 | 1.000 | 0.000 | 0.000 |
| rewrite_succ | 12 | 1.000 | 1.000 | 0.000 | 0.000 |

## 4. pass@k by required operation (v6 vs cross-family-only)

| operation | n | v6 @1 | v6 @5 | xfam @1 | xfam @5 |
| --- | --- | --- | --- | --- | --- |
| contradiction | 22 | 1.000 | 1.000 | 0.000 | 0.000 |
| destruct_exists | 17 | 1.000 | 1.000 | 0.000 | 0.000 |
| instantiate_forall | 3 | 1.000 | 1.000 | 0.000 | 0.000 |
| intro_negation | 21 | 1.000 | 1.000 | 0.000 | 0.000 |
| rewrite | 12 | 1.000 | 1.000 | 0.000 | 0.000 |
| unknown | 9 | 1.000 | 1.000 | 0.000 | 0.000 |

## 5. Per-theorem donor table

| theorem | family | operation | same-fam | same-op | schema∈train | adapt? | v6@5 | xfam@5 | v6 top-donor (fam) |
| --- | --- | --- | :--: | :--: | :--: | :--: | :--: | :--: | --- |
| exists_elim_conj_l_ab | exists_elim_conj | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_conj_l_xy (exists_elim_conj) |
| exists_elim_conj_l_ab | exists_elim_conj | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_conj_l_xy (exists_elim_conj) |
| exists_elim_conj_l_pq | exists_elim_conj | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_conj_l_ps (exists_elim_conj) |
| exists_elim_conj_l_pq | exists_elim_conj | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_conj_l_ps (exists_elim_conj) |
| exists_elim_conj_r_pq | exists_elim_conj | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_conj_r_ps (exists_elim_conj) |
| exists_elim_conj_r_pq | exists_elim_conj | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_conj_r_ps (exists_elim_conj) |
| exists_elim_conj_r_xy | exists_elim_conj | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_conj_r_ab (exists_elim_conj) |
| exists_elim_conj_r_xy | exists_elim_conj | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_conj_r_ab (exists_elim_conj) |
| exists_elim_prop_b | exists_elim_prop | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_prop_s (exists_elim_prop) |
| exists_elim_prop_b | exists_elim_prop | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_prop_s (exists_elim_prop) |
| exists_elim_prop_b | exists_elim_prop | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_prop_s (exists_elim_prop) |
| exists_elim_prop_q | exists_elim_prop | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_prop_s (exists_elim_prop) |
| exists_elim_prop_q | exists_elim_prop | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_prop_s (exists_elim_prop) |
| exists_elim_prop_q | exists_elim_prop | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_prop_s (exists_elim_prop) |
| exists_elim_prop_r | exists_elim_prop | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_prop_s (exists_elim_prop) |
| exists_elim_prop_r | exists_elim_prop | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_prop_s (exists_elim_prop) |
| exists_elim_prop_r | exists_elim_prop | destruct_exists | ✓ | ✓ | ✓ | · | ✓ | · | exists_elim_prop_s (exists_elim_prop) |
| exists_reconstruct_11 | exists_reconstruct | unknown | ✓ | · | ✓ | ✓ | ✓ | · | exists_reconstruct_3 (exists_reconstruct) |
| exists_reconstruct_11 | exists_reconstruct | unknown | ✓ | · | ✓ | ✓ | ✓ | · | exists_reconstruct_3 (exists_reconstruct) |
| exists_reconstruct_11 | exists_reconstruct | unknown | ✓ | · | ✓ | ✓ | ✓ | · | exists_reconstruct_3 (exists_reconstruct) |
| exists_reconstruct_20 | exists_reconstruct | unknown | ✓ | · | ✓ | ✓ | ✓ | · | exists_reconstruct_3 (exists_reconstruct) |
| exists_reconstruct_20 | exists_reconstruct | unknown | ✓ | · | ✓ | ✓ | ✓ | · | exists_reconstruct_3 (exists_reconstruct) |
| exists_reconstruct_20 | exists_reconstruct | unknown | ✓ | · | ✓ | ✓ | ✓ | · | exists_reconstruct_3 (exists_reconstruct) |
| exists_reconstruct_7 | exists_reconstruct | unknown | ✓ | · | ✓ | ✓ | ✓ | · | exists_reconstruct_3 (exists_reconstruct) |
| exists_reconstruct_7 | exists_reconstruct | unknown | ✓ | · | ✓ | ✓ | ✓ | · | exists_reconstruct_3 (exists_reconstruct) |
| exists_reconstruct_7 | exists_reconstruct | unknown | ✓ | · | ✓ | ✓ | ✓ | · | exists_reconstruct_3 (exists_reconstruct) |
| forall_inst_13_6 | forall_inst | instantiate_forall | ✓ | ✓ | ✓ | ✓ | ✓ | · | forall_inst_var_k (forall_inst) |
| forall_inst_9_4 | forall_inst | instantiate_forall | ✓ | ✓ | ✓ | ✓ | ✓ | · | forall_inst_var_k (forall_inst) |
| forall_inst_var_m | forall_inst | instantiate_forall | ✓ | ✓ | ✓ | · | ✓ | · | forall_inst_var_k (forall_inst) |
| neg_contrapositive_ab | neg_contrapositive | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_contrapositive_ac (neg_contrapositive) |
| neg_contrapositive_ab | neg_contrapositive | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_contrapositive_ac (neg_contrapositive) |
| neg_contrapositive_pq | neg_contrapositive | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_contrapositive_pr (neg_contrapositive) |
| neg_contrapositive_pq | neg_contrapositive | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_contrapositive_pr (neg_contrapositive) |
| neg_contrapositive_xy | neg_contrapositive | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_contrapositive_ac (neg_contrapositive) |
| neg_contrapositive_xy | neg_contrapositive | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_contrapositive_ac (neg_contrapositive) |
| neg_double_intro_a | neg_double_intro | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_double_intro_q (neg_double_intro) |
| neg_double_intro_a | neg_double_intro | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_double_intro_q (neg_double_intro) |
| neg_double_intro_p | neg_double_intro | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_double_intro_q (neg_double_intro) |
| neg_double_intro_p | neg_double_intro | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_double_intro_q (neg_double_intro) |
| neg_double_intro_r | neg_double_intro | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_double_intro_q (neg_double_intro) |
| neg_double_intro_r | neg_double_intro | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_double_intro_q (neg_double_intro) |
| neg_exfalso_arrow_pq | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_arrow_ab (neg_exfalso) |
| neg_exfalso_arrow_pq | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_arrow_ab (neg_exfalso) |
| neg_exfalso_arrow_pq | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_arrow_ab (neg_exfalso) |
| neg_exfalso_arrow_pq | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_arrow_ab (neg_exfalso) |
| neg_exfalso_pq | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_ab (neg_exfalso) |
| neg_exfalso_pq | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_ab (neg_exfalso) |
| neg_exfalso_pq | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_ab (neg_exfalso) |
| neg_exfalso_pq | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_ab (neg_exfalso) |
| neg_exfalso_pr | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_ab (neg_exfalso) |
| neg_exfalso_pr | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_ab (neg_exfalso) |
| neg_exfalso_pr | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_ab (neg_exfalso) |
| neg_exfalso_pr | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_ab (neg_exfalso) |
| neg_exfalso_xy | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_ab (neg_exfalso) |
| neg_exfalso_xy | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_ab (neg_exfalso) |
| neg_exfalso_xy | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_ab (neg_exfalso) |
| neg_exfalso_xy | neg_exfalso | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_exfalso_ab (neg_exfalso) |
| neg_imp_exfalso_ab | neg_imp_exfalso | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_imp_exfalso_xy (neg_imp_exfalso) |
| neg_imp_exfalso_ab | neg_imp_exfalso | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_imp_exfalso_xy (neg_imp_exfalso) |
| neg_imp_exfalso_ab | neg_imp_exfalso | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_imp_exfalso_xy (neg_imp_exfalso) |
| neg_imp_exfalso_ad | neg_imp_exfalso | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_imp_exfalso_xy (neg_imp_exfalso) |
| neg_imp_exfalso_ad | neg_imp_exfalso | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_imp_exfalso_xy (neg_imp_exfalso) |
| neg_imp_exfalso_ad | neg_imp_exfalso | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_imp_exfalso_xy (neg_imp_exfalso) |
| neg_imp_exfalso_pq | neg_imp_exfalso | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_imp_exfalso_ps (neg_imp_exfalso) |
| neg_imp_exfalso_pq | neg_imp_exfalso | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_imp_exfalso_ps (neg_imp_exfalso) |
| neg_imp_exfalso_pq | neg_imp_exfalso | intro_negation | ✓ | ✓ | ✓ | · | ✓ | · | neg_imp_exfalso_ps (neg_imp_exfalso) |
| neg_or_cases_ab | neg_or_cases | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_or_cases_ad (neg_or_cases) |
| neg_or_cases_ab | neg_or_cases | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_or_cases_ad (neg_or_cases) |
| neg_or_cases_mn | neg_or_cases | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_or_cases_xy (neg_or_cases) |
| neg_or_cases_mn | neg_or_cases | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_or_cases_xy (neg_or_cases) |
| neg_or_cases_ps | neg_or_cases | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_or_cases_pq (neg_or_cases) |
| neg_or_cases_ps | neg_or_cases | contradiction | ✓ | ✓ | ✓ | · | ✓ | · | neg_or_cases_pq (neg_or_cases) |
| rewrite_succ_ij | rewrite_succ | rewrite | ✓ | ✓ | ✓ | · | ✓ | · | rewrite_succ_ab (rewrite_succ) |
| rewrite_succ_ij | rewrite_succ | rewrite | ✓ | ✓ | ✓ | · | ✓ | · | rewrite_succ_ab (rewrite_succ) |
| rewrite_succ_ij | rewrite_succ | rewrite | ✓ | ✓ | ✓ | · | ✓ | · | rewrite_succ_ab (rewrite_succ) |
| rewrite_succ_ij | rewrite_succ | rewrite | ✓ | ✓ | ✓ | · | ✓ | · | rewrite_succ_ab (rewrite_succ) |
| rewrite_succ_kl | rewrite_succ | rewrite | ✓ | ✓ | ✓ | · | ✓ | · | rewrite_succ_ab (rewrite_succ) |
| rewrite_succ_kl | rewrite_succ | rewrite | ✓ | ✓ | ✓ | · | ✓ | · | rewrite_succ_ab (rewrite_succ) |
| rewrite_succ_kl | rewrite_succ | rewrite | ✓ | ✓ | ✓ | · | ✓ | · | rewrite_succ_ab (rewrite_succ) |
| rewrite_succ_kl | rewrite_succ | rewrite | ✓ | ✓ | ✓ | · | ✓ | · | rewrite_succ_ab (rewrite_succ) |
| rewrite_succ_xy | rewrite_succ | rewrite | ✓ | ✓ | ✓ | · | ✓ | · | rewrite_succ_ab (rewrite_succ) |
| rewrite_succ_xy | rewrite_succ | rewrite | ✓ | ✓ | ✓ | · | ✓ | · | rewrite_succ_ab (rewrite_succ) |
| rewrite_succ_xy | rewrite_succ | rewrite | ✓ | ✓ | ✓ | · | ✓ | · | rewrite_succ_ab (rewrite_succ) |
| rewrite_succ_xy | rewrite_succ | rewrite | ✓ | ✓ | ✓ | · | ✓ | · | rewrite_succ_ab (rewrite_succ) |

## 6. Reading

- The current split is **interpolation**: a same-family donor is available for essentially every test row, and v6 reuses it.
- Forbidding same-family donors is a retrieval-time preview of family holdout; the gap between the two rows in §2 is the share of v6's success attributable to same-family interpolation rather than transferable proof structure.
- This audit motivates Part 2/3: genuinely hold the family (and the whole operation) out of **train** and re-measure. Retrieval is ranking + reuse, never reasoning; no `state_after`; no new templates.
