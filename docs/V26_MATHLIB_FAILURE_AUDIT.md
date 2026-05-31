# Mini-ELF v26 — Part 1: v25 Mathlib tier-C Failure Audit

Audit of the **already-verified** v25 tier-C evaluations (no Lean re-run). Generator order audited: `raw` (pure beam order); the *best* column takes the min rank over learned/abstract/policy_abstract rerankers.

**Honesty:** summarizes prior real-Mathlib (`import Mathlib`) typecheck results. No state_after, no manual oracle as predictions, Mathlib real & external.

## Bound distribution (36 tier-C theorems)

| bound | count | meaning |
|---|---|---|
| solved | 17 | v24 verifies a candidate at rank <5 |
| generator_bound | 10 | no candidate verifies; missing lemma / wrong shape |
| syntax_api_bound | 6 | failures dominated by parse / arity / type-mismatch |
| ranking_bound | 3 | a candidate verifies but only at rank >=5 |

## Bound x expected-skill

| skill | solved | ranking_bound | generator_bound | syntax_api_bound | import_env_bound |
|---|---|---|---|---|---|
| arithmetic | 3 | 0 | 0 | 1 | 0 |
| bool/option | 2 | 0 | 0 | 1 | 0 |
| core-shaped | 11 | 2 | 3 | 0 | 0 |
| list | 1 | 1 | 3 | 0 | 0 |
| mathlib-lemma | 0 | 0 | 0 | 1 | 0 |
| order | 0 | 0 | 0 | 2 | 0 |
| set | 0 | 0 | 4 | 1 | 0 |

## Per-theorem audit

| theorem | cat | skill | transfer | v24 rank (raw/best) | held-out | v25-aug rank | Δ | bound | dominant fail | missing ids |
|---|---|---|---|---|---|---|---|---|---|---|
| v25_bool_and_true | bool_option | bool/option | mathlib | 1/0 | test | 0 | both_solved | solved | unknown_identifier | simpa |
| v25_bool_decide_true | bool_option | core-shaped | core | —/— | train | — | — | generator_bound | unknown_identifier | «using».heq |
| v25_bool_not_not | bool_option | bool/option | mathlib | 0/0 | train | — | — | solved | unknown_identifier | — |
| v25_bool_true_and | bool_option | core-shaped | core | —/— | test | 8 | aug_fixed | generator_bound | unknown_identifier | h1.trans, «using».trans |
| v25_list_append_nil | list | list | mathlib | 0/0 | test | 0 | both_solved | solved | unknown_identifier | — |
| v25_list_length_append | list | list | mathlib | 7/0 | train | — | — | ranking_bound | unknown_identifier | — |
| v25_list_length_reverse | list | list | mathlib | —/— | train | — | — | generator_bound | unknown_identifier | Or.refl |
| v25_list_map_id | list | list | mathlib | —/— | test | 0 | aug_fixed | generator_bound | unknown_identifier | Eq.zero_add |
| v25_list_mem_cons_self | list | list | mathlib | —/— | train | — | — | generator_bound | unknown_identifier | — |
| v25_list_nil_append | list | core-shaped | core | 0/0 | train | — | — | solved | other | — |
| v25_list_reverse_nil | list | core-shaped | core | 1/0 | test | 0 | both_solved | solved | unknown_identifier | List.refl, Or.refl |
| v25_logic_and_imp | logic | core-shaped | core | 0/0 | test | 0 | both_solved | solved | type_or_arity | — |
| v25_logic_and_symm | logic | core-shaped | core | 0/0 | train | — | — | solved | type_or_arity | — |
| v25_logic_em | logic | mathlib-lemma | mathlib | —/— | train | — | — | syntax_api_bound | parse_error | — |
| v25_logic_iff_refl | logic | core-shaped | core | —/— | test | — | both_fail | generator_bound | unknown_identifier | — |
| v25_logic_imp_self | logic | core-shaped | core | 0/0 | train | — | — | solved | unknown_identifier | — |
| v25_logic_modus_ponens | logic | core-shaped | core | 0/0 | train | — | — | solved | parse_error | hpqhpq |
| v25_logic_not_intro | logic | core-shaped | core | 6/0 | test | 0 | both_solved | ranking_bound | type_or_arity | — |
| v25_logic_or_symm | logic | core-shaped | core | 0/0 | train | — | — | solved | unknown_identifier | — |
| v25_nat_add_assoc | nat | arithmetic | mathlib | 2/0 | test | 4 | both_solved | solved | unknown_identifier | — |
| v25_nat_add_comm | nat | arithmetic | mathlib | 1/0 | train | — | — | solved | type_or_arity | Nat.Nat |
| v25_nat_add_one_eq | nat | core-shaped | core | 0/0 | train | — | — | solved | type_or_arity | Eq.add_comm |
| v25_nat_add_zero | nat | core-shaped | core | 0/0 | test | 0 | both_solved | solved | type_or_arity | — |
| v25_nat_le_refl | nat | order | mathlib | —/— | train | — | — | syntax_api_bound | parse_error | — |
| v25_nat_le_succ | nat | order | mathlib | —/— | train | — | — | syntax_api_bound | type_or_arity | — |
| v25_nat_mul_one | nat | arithmetic | mathlib | —/— | test | 0 | aug_fixed | syntax_api_bound | type_or_arity | Eq.add_comm, Or.refl |
| v25_nat_mul_zero | nat | core-shaped | core | 0/0 | train | — | — | solved | unknown_identifier | Eq.zero_add, Eq.nil_append, Or.refl |
| v25_nat_succ_eq | nat | core-shaped | core | 0/0 | train | — | — | solved | type_or_arity | — |
| v25_nat_zero_add | nat | arithmetic | mathlib | 2/0 | test | 0 | both_solved | solved | type_or_arity | — |
| v25_option_map_id | bool_option | bool/option | mathlib | —/— | train | — | — | syntax_api_bound | type_or_arity | Eq.nil_append, Eq.rfl, Eq.succ, Or.refl |
| v25_option_some_isSome | bool_option | core-shaped | core | 8/0 | train | — | — | ranking_bound | unknown_identifier | Or.refl |
| v25_set_empty_subset | set | set | mathlib | —/— | test | — | both_fail | generator_bound | unknown_identifier | g.intro, g.elim, g.trans, g.refl |
| v25_set_inter_subset_left | set | set | mathlib | —/— | train | — | — | syntax_api_bound | parse_error | — |
| v25_set_mem_singleton | set | set | mathlib | —/— | train | — | — | generator_bound | unknown_identifier | g.a, g.refl, g.intro, g.trans |
| v25_set_mem_univ | set | set | mathlib | —/— | test | — | both_fail | generator_bound | unknown_identifier | g.refl, g.trans, g.intro |
| v25_set_subset_refl | set | set | mathlib | —/— | train | — | — | generator_bound | unknown_identifier | g.refl, g.intro |

## Special focus

* **Set goals (5):** all unsolved by v24 zero-shot (every rerank config). Set names: v25_set_empty_subset, v25_set_inter_subset_left, v25_set_mem_singleton, v25_set_mem_univ, v25_set_subset_refl.
* **≤ / order goals:** v25_nat_le_refl(rank raw=—, bound=syntax_api_bound), v25_nat_le_succ(rank raw=—, bound=syntax_api_bound).
* **n*1=n (`v25_nat_mul_one`):** bound=syntax_api_bound, v24 raw rank=—, missing=['Eq.add_comm', 'Or.refl'].
* **List goals:** v25_list_append_nil(bound=solved), v25_list_length_append(bound=ranking_bound), v25_list_length_reverse(bound=generator_bound), v25_list_map_id(bound=generator_bound), v25_list_mem_cons_self(bound=generator_bound), v25_list_nil_append(bound=solved), v25_list_reverse_nil(bound=solved).
* **v25 augmentation FIXED (held-out):** v25_bool_true_and, v25_list_map_id, v25_nat_mul_one.
* **v25 augmentation REGRESSED a tier-C theorem:** none.

## Most-missing Mathlib identifiers (what the generator never proposes)

| identifier | #theorems |
|---|---|
| `Or.refl` | 6 |
| `g.intro` | 4 |
| `g.refl` | 4 |
| `g.trans` | 3 |
| `Eq.zero_add` | 2 |
| `Eq.add_comm` | 2 |
| `Eq.nil_append` | 2 |
| `simpa` | 1 |
| `«using».heq` | 1 |
| `h1.trans` | 1 |
| `«using».trans` | 1 |
| `List.refl` | 1 |
| `hpqhpq` | 1 |
| `Nat.Nat` | 1 |
| `Eq.rfl` | 1 |

## Co-training interference on broad-core (v24 vs v25 augmented)

Evidence for why v26 must route, not co-train. v24 = `policy_abstract`, v25 augmented = `raw` (its best broad-core config).

| broad-core category | v24 p@10 | v25-aug p@10 | Δ |
|---|---|---|---|
| bool | 1.000 | 0.667 | -0.333 ⬇️ |
| conjunction | 0.833 | 0.833 | +0.000 |
| disjunction | 0.600 | 0.400 | -0.200 ⬇️ |
| equality_rewrite | 1.000 | 1.000 | +0.000 |
| exists | 1.000 | 0.750 | -0.250 ⬇️ |
| forall | 1.000 | 1.000 | +0.000 |
| implication | 1.000 | 1.000 | +0.000 |
| list | 1.000 | 1.000 | +0.000 |
| nat_succ | 1.000 | 0.800 | -0.200 ⬇️ |
| negation | 1.000 | 0.800 | -0.200 ⬇️ |
| **overall** | 0.938 | 0.833 | -0.104 |

## Conclusions (feeding Parts 2–7)

1. **10/36 tier-C failures are generator-bound** — the model never proposes the needed Mathlib lemma or proof shape. The environment is **not** the wall (import_env_bound = 0).
2. **Set goals are categorically unreachable** for the broad generator — a dedicated specialist must learn `intro x hx; exact hx`, `Set.Subset.refl`, `Set.inter_subset_left`, membership unfolding.
3. Missing-identifier counts show the gap is **lemma vocabulary** (`Nat.*`, `Set.*`, `List.*` names) plus proof-shape, not syntax.
4. Co-training improved tier-C held-out but **regressed broad-core** (table above) → v26 builds a **specialist + router** so broad-core stays on the untouched v24 model.
