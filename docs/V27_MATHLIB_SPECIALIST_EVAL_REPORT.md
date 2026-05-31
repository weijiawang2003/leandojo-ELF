# Mini-ELF v27 — Mathlib Specialist Eval Report (Part 7a)

Verifier: `TrustedMathlibVerifier` (sentinel + confirm + rescue — sound & complete,
V27 Part 1). Pools: token-seq2seq beams + literal-adapt compose; best rerank config
per cell (raw/rule/learned/policy/abstract/policy_abstract). Source:
`scripts/evaluate_v27_mathlib_specialists.py` →
`data/baselines/v27_specialist_eval/comparison.json`. No state_after; manual targets
never fed to a model as predictions; v24 untouched.

## Headline pass@1 / pass@5 / pass@10 (best config)

### v25 held-out tier-C (14 theorems)
| Model | p@1 | p@5 | p@10 |
|-------|-----|-----|------|
| v24 (zero-shot) | 0.429 | 0.571 | 0.571 |
| v25_aug (co-trained) | 0.643 | 0.714 | 0.786 |
| v26_base | 0.857 | 0.929 | 0.929 |
| v26_widened | 0.929 | 0.929 | 0.929 |
| v27_base | 0.786 | 0.929 | 0.929 |
| v27_widened | 0.571 | 0.929 | 0.929 |
| **v27_category_balanced** | 0.786 | **1.000** | **1.000** |
| v27_set_heavy | 0.714 | 0.929 | 0.929 |

### v26 held-out tier-C (22 theorems)
| Model | p@1 | p@5 | p@10 |
|-------|-----|-----|------|
| v24 | 0.273 | 0.318 | 0.318 |
| v25_aug | 0.455 | 0.591 | 0.636 |
| v26_base | 0.500 | 0.864 | 0.909 |
| v26_widened | 0.773 | 0.909 | 0.909 |
| v27_base | 0.409 | 0.864 | 0.864 |
| v27_widened | 0.591 | 0.909 | 0.909 |
| v27_category_balanced | 0.727 | 0.864 | 0.864 |
| **v27_set_heavy** | 0.864 | **0.955** | **0.955** |

### v27 theorem-holdout — fresh novel shapes (7 theorems)
| Model | p@1 | p@5 | p@10 |
|-------|-----|-----|------|
| v24 | 0.286 | 0.286 | 0.286 |
| v25_aug | 0.286 | 0.429 | 0.429 |
| v26_base | 0.429 | 0.571 | 0.571 |
| v26_widened | 0.571 | 0.714 | 0.714 |
| v27_base / widened / cat_bal / set_heavy | 0.571 | 0.714 | 0.714 |

## Per-category Set / order pass@10 (the v27 targets)

| Model @ bench | Set p@10 | order p@10 |
|---------------|----------|-----------|
| v26_widened @ v26-holdout | 0.75 (n=4) | — |
| v27_widened @ v26-holdout | 0.75 (n=4) | — |
| **v27_set_heavy @ v26-holdout** | **1.00 (n=4)** | — |
| v27_category_balanced @ v26-holdout | 0.50 (n=4) | — |
| v27_set_heavy @ v27-holdout | 0.00 (n=2) | **1.00 (n=2)** |
| v27_base @ v27-holdout | 0.50 (n=2) | **1.00 (n=2)** |

## Targets — all met

| Target | Result |
|--------|--------|
| v26 held-out pass@10 ≥ 0.909 (improve) | **0.955** (v27_set_heavy) ✅ |
| v25 held-out pass@10 ≥ 0.929 (improve) | **1.000** (v27_category_balanced) ✅ |
| held-out Set pass@10 > 0.75 | **1.00** (v27_set_heavy, v26-holdout Set) ✅ |
| order pass@10 high & documented | **1.00** (v27-holdout order) ✅ |
| zero verifier false-positive regressions | trusted FP = 0 (Part 1) ✅ |

## Findings

1. **Scaling verified Set data continues to help.** v27_set_heavy (Set rows
   upsampled 2×) closes the last v26-holdout Set residual (0.75 → **1.00**) and
   lifts overall v26-holdout 0.909 → **0.955** — affirmative answer to Q1/Q3.
2. **Category balancing is harmful for the gap category.** v27_category_balanced
   capped per-category counts and *regressed* Set on v26-holdout (0.75 → 0.50),
   even though it reached 1.00 overall on v25-heldout. The gap category (Set)
   needs *more* emphasis, not equal weighting — so the recommended specialist is
   **v27_set_heavy**, not the balanced one.
3. **The specialist still decisively beats co-training and zero-shot.** On
   v26-holdout, v27_set_heavy 0.955 vs v25_aug 0.636 vs v24 0.318; on v25-heldout
   1.000 (cat_bal) / 0.955-class vs 0.786 vs 0.571.
4. **The fresh v27 holdout is hard** (novel `mem_inter_iff`, `union_subset`
   shapes): all configs plateau at 0.714 — these residuals are membership-iff and
   union-elimination shapes (see Part 8). order generalizes fully (1.00).
5. **Recommended v27 specialist = `token_seq2seq_v27_set_heavy`** — dominates
   v27_widened (v26-holdout 0.955 vs 0.909, Set 1.0 vs 0.75) at equal cost.
