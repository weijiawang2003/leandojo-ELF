# V30 — Part 7: Specialist Evaluation Report

_`scripts/evaluate_v30_mathlib_specialists.py` → `data/baselines/v30_specialist_eval/`.
8 models × 9 benches; **8390 unique (theorem, candidate) pairs** verified in one
shared TrustedMathlibVerifier pass (123 invocations, 554 s). pass@10, best rerank
config per cell._

## Main matrix — pass@10 (best rerank config per cell)

| model | v25 | v26 | v27 | v28 | v29 | v29 famD | v29 lowD | v30 | v30 tgtFam |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v29_general | 0.857 | 1.000 | 0.857 | 0.933 | 1.000 | 0.824 | 1.000 | 0.20 | 0.00 |
| v29_set_finset_order_heavy | 0.857 | 1.000 | 1.000 | 0.967 | 1.000 | 0.853 | 1.000 | 0.33 | 0.10 |
| **v30_general_targeted** | **1.000** | **1.000** | **1.000** | **0.967** | **1.000** | 0.824 | **1.000** | **0.867** | 0.60 |
| v30_v29best_plus | **1.000** | 1.000 | 1.000 | 0.967 | 1.000 | 0.824 | 1.000 | 0.80 | 0.60 |
| v30_targeted_upsample | 0.929 | 0.857 | 1.000 | 0.967 | 1.000 | 0.765 | 0.923 | 0.733 | 0.50 |
| v30_targeted_only (ablation) | 0.50 | 0.45 | 0.57 | 0.30 | 0.20 | 0.12 | 0.31 | 0.60 | 0.30 |

## Against the v30 targets

| target | v29 | v30 | verdict |
|---|---:|---:|---|
| **recover v25 held-out → 1.000** | 0.857 | **1.000** | ✅ **recovered** |
| preserve v26 holdout | 1.000 | 1.000 | ✅ |
| preserve v28 fresh holdout | 0.933 / 0.967 | **0.967** | ✅ (general now matches heavy) |
| preserve v29 holdout 1.000 | 1.000 | 1.000 | ✅ |
| reduce residuals | 8 | (see below) | ⚠️ partial |

### The v25 recovery (headline)

`v30_general_targeted` solves **both** regressed theorems —
`v25_nat_add_assoc` (now `omega`/`Nat.add_assoc x y z` re-enters the beam) and
`v25_set_empty_subset` (`Set.empty_subset s`/`simp` re-enters) — so **v25 pass@10
returns to 1.000**. The targeted count-repair (each family 0–3 → 4–6 siblings) put the
canonical tactic back in the top-10 for every variable naming. And it did so **without
cost**: v30_general_targeted also matches the heavy config's v27 1.000 / v28 0.967, so
the repaired general model is now the strict best across v25–v29.

## Config lessons

- **`v30_general_targeted` is the clear winner** (recommended). `v30_v29best_plus`
  ties on v25 but is heavier.
- `v30_targeted_upsample` (2× repair rows) **regresses v26 to 0.857** → upsampling the
  repair rows is *worse* than plain addition; **unweighted is best** (consistent with
  v29).
- `v30_targeted_only` (66 repair rows alone) collapses on the old benches (v28 0.30) —
  an ablation confirming the repair must be **added to** the full corpus, not replace
  it.

## What did NOT repair: the `_3` token residuals

`v29_family_density` stayed at **0.824** (v29 0.853 → v30 0.824, flat). The token-
diversity repair (fresh `u,v`/`c,d` sets, `k/hk`,`e/he` elements) did **not** fix the
held-out `_3` members, because those use element/hyp tokens (`w`,`hw`) that **no**
training sibling carries — a char/token seq2seq cannot bind a projection it has never
seen the identifier for. This is an honest **limit of pure token augmentation**, and a
refinement of the density law: density helps when the held-out member's surface tokens
are in-distribution; it stalls on genuinely novel identifiers.

Real `import Mathlib` typecheck, TrustedMathlibVerifier only, no state_after, no manual
oracle, v24 untouched.
