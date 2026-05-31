# Mini-ELF v26 — Part 8: Failure & Success Examples

Concrete worked cases from the verified evaluation predictions (`data/baselines/v26_specialist_eval/`). Every 'success' is a real `import Mathlib` typecheck of a model-generated tactic.

## 1. Zero-shot success (v24 broad-core solved it)
`v25_nat_add_zero` [nat] → v24 verified `exact rfl` at rank 0.

## 2. Specialist-only success (v24 failed, v26 specialist solved)
`v25_nat_mul_one` [nat] → v26 verified `simp` at rank 0; v24 produced 0 verified candidates (dominant error: wrong_shape).

## 3. Routed success on a Set goal
Router sends `v25_set_mem_univ` (Mathlib import) → specialist, which verified `simp` at rank 0. v24 = 0 verified.

## 4. Remaining Set failure (v26 specialist)
`v26_set_inter_comm_subset` — 0 verified candidates; dominant error `wrong_shape`. Sample error: `error: : Type mismatch`. Needs anonymous-constructor / membership-projection shapes (→ optional widening).

## 5. Remaining ≤ / order failure
None — every order/≤ tier-C theorem is solved by the specialist (v24 left them at 0).

## 6. Broad-core preservation (routed → v24, unchanged)
On the 48-theorem broad-core benchmark the router sends every theorem to the untouched v24 model; p@5/p@10 = 0.938/0.958 with `bool`/`implication`/`equality`/`list`/`negation` at 1.00 — meeting the protected bar. Example: `v18_imp_p_self` `(p : Prop) (hp : p) : p` → `exact hp` (rank 0).

## 7. v25 co-training regression (why v26 routes instead)
The single co-trained v25 model regressed broad-core `bool` from p@10 1.00 (v24) to 0.667 and overall broad-core p@10 0.938→0.833 (see `data/baselines/v25_broadcore_regression/`). A protected `bool` theorem that v24 solves with `cases b <;> rfl` was lost. v26's router never sends broad-core to a Mathlib-trained model, so this cannot happen.

