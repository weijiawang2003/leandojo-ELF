# V29 — Part 7: Specialist Evaluation Report

_`scripts/evaluate_v29_mathlib_specialists.py` → `data/baselines/v29_specialist_eval/`.
9 models × 7 benches + 3 transfer cells; **7491 unique (theorem, candidate) pairs**
verified in one shared pass by `TrustedMathlibVerifier` (110 invocations, 529 s).
pass@10, best rerank config per cell._

## Main matrix — pass@10 (best rerank config per cell)

| model | v25 | v26 | v27 | v28 | v29 | family_density | low_density |
|---|---:|---:|---:|---:|---:|---:|---:|
| v27_widened (v27 best) | 0.929 | 0.909 | 0.714 | 0.633 | 0.250 | 0.382 | 0.385 |
| v28_general (v28 best) | **1.000** | 0.955 | 0.857 | 0.867 | 0.450 | 0.441 | 0.769 |
| **v29_general** | 0.857 | **1.000** | 0.857 | **0.933** | **1.000** | 0.824 | **1.000** |
| v29_v28best_plus | 0.857 | 1.000 | 0.857 | 0.933 | 1.000 | 0.824 | 1.000 |
| **v29_set_finset_order_heavy** | 0.857 | 1.000 | **1.000** | **0.967** | 1.000 | **0.853** | 1.000 |
| v29_category_balanced (neg ctrl) | 0.857 | 1.000 | 1.000 | 0.900 | 0.900 | 0.765 | 0.923 |
| v29_function_order | 0.929 | 0.955 | 0.857 | 0.933 | 1.000 | 0.765 | 1.000 |

## Against the v29 targets

| target | v28 | v29 | verdict |
|---|---:|---:|---|
| **improve v28 fresh holdout > 0.867** | 0.867 | **0.933** (general) / **0.967** (heavy) | ✅ improved |
| preserve v26 holdout ≥ 0.955 | 0.955 | **1.000** | ✅ improved |
| preserve v27 holdout | 0.857 | **1.000** (heavy) | ✅ improved |
| new v29 fresh holdout | — | **1.000** | ✅ |
| preserve v25 held-out = 1.000 | 1.000 | **0.857** (general) / 0.929 (function_order) | ⚠️ **regressed 2/14** |

### The v25 regression (honest)

v29 trades **2 of 14** v25 micro-benchmark theorems: `v25_nat_add_assoc`
(`a+b+c = a+(b+c)`, needs `omega`/`Nat.add_assoc a b c`) and `v25_set_empty_subset`
(`∅ ⊆ s`, needs `Set.empty_subset s`). The correct tactics **verify** — they simply
fell **out of the top-10 beam** as the 492 new rows shifted the small seq2seq's
distribution toward the densified families (the model now emits `simp`/hallucinated
`Nat.append_assoc` for `add_assoc`, and `Subset.refl`/`diff_subset` for
`empty_subset`). This is the cost of unweighted scaling on a 14-theorem
micro-benchmark; it is **recoverable** (v30: a few `add_assoc`/`empty_subset` siblings
or a light reranker fix) and does **not** touch broad-core. The net over the larger,
fresher held-outs is a clear gain. The v28 residuals that v29 *fixed* are the headline
direction: `v28_fun_comp_assoc3` and `v28_ord_antisymm` now verify (v29_general's
v28-holdout misses are now the un-densified `fs_empty_subset`, `ord_le_refl`).

## Whole-category transfer (each model on its held-out category) — pass@10

| category | v28 | v29 | n (v29) |
|---|---:|---:|---:|
| set | 0.237 | **0.292** | 48 |
| finset | 0.333 | 0.136 | 44 |
| order | 0.778 | 0.556 | 36 |

Transfer did **not** improve (set slightly up; finset/order down — partly because the
v29 transfer test sets are larger and now include the dense-family members the
category-stripped model cannot reach). **Answer to RQ3: no — adding sibling families
does not lift whole-category transfer; density is within-family, not cross-category.**

## Reading

- `v29_set_finset_order_heavy` is the **strongest single model** on the structured /
  hard benches (v27 1.000, v28 0.967, family_density 0.853); `v29_general` is the
  unweighted default and ties or wins on v26/v29/low_density.
- `v29_category_balanced` (negative control) is ≤ general on 5/7 benches → **balancing
  remains unhelpful** (RQ4: unweighted general is the right default; targeted
  *upsampling* of weak categories helps a little, *capping* does not).
- Real `import Mathlib` typecheck, `TrustedMathlibVerifier` only, no `state_after`, no
  manual oracle as predictions, v24 untouched.
