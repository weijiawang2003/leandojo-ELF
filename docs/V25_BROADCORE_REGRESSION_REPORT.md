# V25 broad-core regression report (Part 6)

Driver: [`scripts/evaluate_v21_broad_core.py`](../scripts/evaluate_v21_broad_core.py)
with `--model-root token_seq2seq_v25_tierc_augmented` on the v18 broad-core
benchmark (48 theorems, **core-Lean** verifier — pinned toolchain binary, no
Mathlib). Compared against the fixed v24 model
(`data/baselines/v24_broad_residual_eval/`).

## Headline: the tiny Mathlib augmentation **regresses broad-core**

| model | best pass@1 | best pass@5 | pass@10 | no-verify |
|---|---|---|---|---|
| **v24 (adopted)** | 0.792 | **0.917** | **0.938** | **3** |
| v25 augmented | 0.729 | 0.833 | 0.833 | 8 |

`pass@10` is rerank-invariant, so the drop **0.938 → 0.833** is a pure
**generator** regression: 5 theorems v24 reached are no longer reached. The 68
co-trained Mathlib rows (+27 vocab tokens), retrained from scratch at the same
capacity/epoch budget, shifted the generator's beam distribution away from the
v24 residual gains — i.e. **catastrophic-forgetting-style interference**, not a
reranking artifact.

## Per-category pass@5 (best-of configs)

| category | v24 | v25 aug | |
|---|---|---|---|
| forall | 1.000 | 1.000 | held ✅ |
| implication | 1.000 | 1.000 | held ✅ |
| equality_rewrite | 1.000 | 1.000 | held ✅ |
| list | 1.000 | 1.000 | held ✅ |
| conjunction | 0.833 | 0.833 | held |
| **bool** | **1.000** | **0.667** | **REGRESSED** ❌ |
| **negation** | 1.000 | 0.800 | REGRESSED |
| **exists** | 1.000 | 0.750 | REGRESSED |
| **nat_succ** | 1.000 | 0.800 | REGRESSED |
| **disjunction** | 0.600 | 0.400 | REGRESSED |

forall / implication / equality / list held at 1.000, **but `bool` — a category
the brief required preserved at 1.000 — regressed to 0.667**, along with the
negation / exists / nat_succ gains v24 had won. So the **v25 augmented model
fails the broad-core preservation bar.**

## Verdict (honest tradeoff, as the brief requires)

The tiny verified Mathlib corpus **does** improve Mathlib-tier transfer
(held-out tier-C pass@10 0.571 → 0.786, +3 theorems, Part 5) **and** regresses
v18 broad-core (pass@10 0.938 → 0.833, protected `bool` 1.000 → 0.667). This is a
genuine **tradeoff**, not a free improvement.

**Decision: v24 remains the broad-core model. The v25 augmented model is NOT
adopted** — it is retained only as evidence that (a) generator coverage is the
real wall and a tiny corpus moves it, and (b) **naive single-model co-training is
the wrong delivery mechanism** for adding a new tier. The protected-category
guarantee (forall / implication / bool = 1.000) is preserved precisely *because*
v24 is kept; nothing in v24's metrics on disk was changed or retconned.

This directly motivates the v26 recommendation: deliver Mathlib via a **separate
specialist + router** (as v21 routing did for forall) or via a **larger,
category-balanced Mathlib corpus with more capacity/epochs**, so broad-core is
not cannibalised. See [`NEXT_STEPS.md`](NEXT_STEPS.md).

## Confirmation

- ✅ same v18 benchmark / verifier / harness as v24 — apples-to-apples.
- ✅ v24 metrics on disk unchanged; regression measured, not hidden.
- ✅ core-Lean pinned binary; no Mathlib; no state_after; no manual oracle.
