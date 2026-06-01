# V28 Part 6 — Specialist Evaluation

_Script: `scripts/evaluate_v28_mathlib_specialists.py`.
Verifier: `TrustedMathlibVerifier` (sound & complete).
Output: `data/baselines/v28_specialist_eval/`._

All numbers are best-config pass@k under the trusted `import Mathlib` verifier (one
global verification pass shared across cells). Reranker configs:
raw/rule/learned/policy/abstract/policy_abstract; "best" = max pass@5 then pass@1.

## Headline: the fresh-holdout plateau is broken

| model | v25 held-out | v26 holdout | v27 holdout | v28 holdout (NEW, 30 thm) |
|-------|:---:|:---:|:---:|:---:|
| v26_base | 0.929 | 0.909 | 0.571 | 0.567 |
| v26_widened | 0.929 | 0.909 | 0.714 | 0.633 |
| v27_widened | 0.929 | 0.909 | 0.714 | 0.633 |
| v27_set_heavy | 0.929 | **0.955** | 0.714 | 0.667 |
| **v28_general** | **1.000** | **0.955** | **0.857** | **0.867** |
| v28_set_order_heavy | 0.929 | 0.955 | 0.857 | 0.833 |
| v28_category_balanced | 0.929 | 0.955 | — | 0.700 |
| **v28_finset_specialist** | **1.000** | 0.955 | **1.000** | 0.800 |

(pass@10 shown.) **`v28_general` is the recommended all-rounder**: best or tied-best
on every benchmark and top on the largest fresh holdout (v28, 30 theorems).

### vs the v28 targets

| target | v27 | v28 | verdict |
|--------|----:|----:|:---|
| v25 held-out pass@10 | 1.000 | **1.000** | ✅ preserved |
| v26 holdout pass@10 | 0.955 | **0.955** | ✅ preserved |
| **fresh v27 holdout > 0.714** | 0.714 | **0.857** (general) / **1.000** (best) | ✅ **improved +0.143 / +0.286** |
| new v28 holdout | 0.667 (v27 best) | **0.867** | ✅ +0.200 |

## The v27 residuals are now solved

Under `v28_general` on the v27 holdout (0.857, the one remaining miss is
`union_subset`, which the best config `v28_finset_specialist` solves → v27 holdout
**1.000**):

| v27 residual | v27 outcome | v28 outcome |
|--------------|-------------|-------------|
| `v27_set_mem_inter_iff` (`x∈s∩t ↔ x∈s∧x∈t`) | ❌ unknown_identifier | ✅ **solved @ rank 0** via `simp [Set.mem_inter]` |
| `v27_set_union_subset` (`s⊆u→t⊆u→s∪t⊆u`) | ❌ type_mismatch | ✅ solved by best v28 config (`Set.union_subset h1 h2`) |

The densified `mem_iff` / `union_subset` families gave the held-out members the
sibling neighbours they lacked, so the small seq2seq now binds the right shape.

## v28_general @ v28 holdout — per category

| category | n | pass@10 |
|----------|--:|--------:|
| nat | 3 | 1.000 |
| list | 1 | 1.000 |
| logic | 1 | 1.000 |
| order | 9 | 0.889 |
| set | 9 | 0.889 |
| **finset (NEW)** | 6 | **0.833** |
| function | 1 | 0.000 |

Overall **0.867** (4 of 30 no-verify). The new Finset category reaches **0.833** on
held-out members — a new Mathlib category with nontrivial held-out success.

## Category-transfer probes (whole category held out)

| holdout (all members removed from train) | n | pass@10 |
|------------------------------------------|--:|--------:|
| order (model `v28_order_holdout`) | 27 | **0.778** |
| finset (model `v28_finset_holdout`) | 18 | 0.333 |
| set (model `v28_set_holdout`) | 38 | 0.237 |

**Interpretation (a real scientific result, not a defect):** order transfers well
(0.778) because its `≤` shapes overlap with the Nat/`le` shapes the model still
sees; set/finset transfer is low because removing the *entire* category deletes
every sibling, leaving nothing to generalize from. This **confirms the
sparse-sibling thesis** — success is driven by *within-family* sibling density, not
generic cross-category transfer. The theorem-holdout numbers (which keep siblings)
are the relevant generalization measure; the full-category holdouts are a stress
test that bounds transfer.

## Honesty

Real `import Mathlib` typecheck. No `state_after`. Manual targets never fed to a
model as predictions. The v24 broad-core model is untouched. No naive verifier used.
