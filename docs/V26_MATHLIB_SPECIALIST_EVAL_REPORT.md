# Mini-ELF v26 — Part 6: Mathlib Specialist Evaluation

`scripts/evaluate_v26_specialist.py` compares four token-seq2seq models on two
Mathlib-tier benchmarks. Candidate pools come only from each model's beams
(+ literal-adapt compose); every candidate is verified by the **batched
`import Mathlib`** typecheck (`mini_elf_lean.mathlib_verifier`). Rerank configs
and the failure taxonomy are identical to the v25 eval; only the verifier is
faster (1,192 unique pairs verified in **16 Lean invocations / 70 s**).

## Models

| label | model | training data |
|---|---|---|
| v24 | `token_seq2seq_v24_broad_residual` | broad-core, **zero Mathlib** (untouched) |
| v25_aug | `token_seq2seq_v25_tierc_augmented` | broad-core **+ tiny Mathlib (co-trained)** |
| **v26_base** | `token_seq2seq_v26_mathlib_specialist_base` | **Mathlib specialist only (149 rows)** |
| v26_plus_core | `token_seq2seq_v26_mathlib_specialist_plus_core` | Mathlib + 58 curated v18 core rows |

## Headline comparison (best rerank config per cell)

| model | v25 held-out (14) p@1/5/10 | v26 holdout (22) p@1/5/10 |
|---|---|---|
| v24 (zero-shot) | 0.429 / 0.571 / 0.571 | 0.273 / 0.318 / 0.318 |
| v25_aug (co-trained) | 0.643 / 0.714 / 0.786 | 0.455 / 0.591 / 0.636 |
| **v26_base** | **0.857 / 0.929 / 0.929** | **0.500 / 0.864 / 0.909** |
| v26_plus_core | 0.786 / 0.857 / 0.857 | 0.182 / 0.773 / 0.773 |

> **Verifier soundness.** All numbers use the *confirmed* batched verifier:
> Lean's parser recovery can silently skip a malformed declaration that follows
> a parse-error candidate, which would mark a *failing* beam as "verified". The
> verifier re-batches successes until stable (a gold-standard check confirmed
> **0 mismatches vs one-example-per-file** over 468 broad-core candidates). This
> only ever inflated the *weaker* models' scores (their beams contain more
> malformed multi-line garbage); after the fix v24/v25_aug drop slightly on the
> v26 holdout while **v26_base is unchanged** (its beams are clean), so the
> specialist's margin is, if anything, larger.

* **Target met:** the task asked to push v25 held-out tier-C pass@10 **above
  0.786** — `v26_base` reaches **0.929** (and 0.909 on the fresh v26 holdout).
* **Specialist > co-training:** v26_base beats v25_aug by **+0.143** (v25
  held-out) and **+0.273** (v26 holdout, 0.909 vs 0.636) pass@10; it beats v24
  zero-shot by +0.358 and +0.591 respectively.
* **`plus_core` is *worse* than `base`** on both benchmarks. Even *within* the
  specialist, mixing in core rows dilutes Mathlib-specific learning (its
  Mathlib-val peaked at epoch 5 then fell). → adopt **`v26_base`**, pure Mathlib.

## Per-category: Set and the Mathlib-lemma tier are now reachable

`v26_base` vs `v24`, both on the fresh **v26 holdout** (best config `abstract`):

| category | v24 p@10 | v26_base p@10 |
|---|---|---|
| set | **0.00** (0/4) | **0.50** (2/4) |
| nat | 0.33 | 1.00 |
| list | 0.25 | 1.00 |
| logic | 0.75 | 1.00 |
| bool_option | 0.33 | 1.00 |
| function | 0.00 | 1.00 |
| **transfer = mathlib-lemma** | **0.20** | **0.87** |
| transfer = core | 0.57 | 1.00 |

On the v25 held-out set, `v26_base` Set p@10 = **1.00** (2/2), and nat/list/
logic/bool all ≥ 0.75. Set — flagged categorically **unreachable** in v25 —
is now solved on the established benchmark and **partially** solved (0 → 0.50)
on harder fresh Set goals.

## Was the "large" config (C) needed? No.

The task says train config C (embed 128 / hidden 192) **only if A/B underfit
badly**. They did not: `v26_base` reaches 0.909–0.929 pass@10 and ≥0.86 pass@5,
with the residual failures being *vocabulary/shape* misses on a handful of hard
Set goals — not capacity starvation. Adding capacity to a 149-row corpus would
mostly overfit. **Config C was skipped** (documented, not silently dropped). The
next lever is *more verified Mathlib rows* for the hard Set shapes, not bigger
models (see the optional widening pass).

## Remaining failures (honest)

* **v25 held-out (1/14):** `v25_nat_add_assoc` — the specialist's beams miss
  `omega` / `Nat.add_assoc`; dominant class `unknown_identifier`.
* **v26 holdout (2/22):** `v26_set_inter_comm_subset`, `v26_set_mem_inter_left`
  — both `type_mismatch`. These need anonymous-constructor reconstruction
  (`⟨h.2, h.1⟩`) or projection through set membership, which the small model
  did not learn from few examples. → fed to the optional widening pass.

Full failure taxonomy per (model, benchmark, config) is in
`data/baselines/v26_specialist_eval/<model>__<bench>/<config>/metrics.json`.

## Honesty

Real Mathlib typecheck (no mock). Pools come from beams only — the manual
reference candidates are never given to a model. No `state_after`; no v10
leakage. The v24 broad-core model is read-only here. v26_base never trained on
either benchmark's theorems (theorem-level + triple leakage guards).
