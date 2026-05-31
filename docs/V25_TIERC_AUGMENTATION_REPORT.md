# V25 tier-C augmentation report (Part 5)

Builder: [`scripts/build_v25_tierc_training_set.py`](../scripts/build_v25_tierc_training_set.py);
trained with `scripts/train_v20_broad_plus_seq2seq.py` (the v24 architecture,
unchanged); evaluated with [`scripts/evaluate_v25_tierc.py`](../scripts/evaluate_v25_tierc.py).

**Question (research Q3): does adding a tiny verified Mathlib corpus improve
transfer?** **Answer: yes — measurably — but naive co-training pays for it with a
broad-core regression** (Part 6). The augmented model is therefore an
informative diagnostic, **not** a drop-in replacement for v24.

## Setup

- **Base** = v24 broad-plus-residual pool, **3,410 rows** (exactly the v24
  generator's training data).
- **+ tier-C** = the **68 verified** Mathlib rows from the **22 train-split**
  theorems only (theorem-level split). The corpus's 36 theorems were stratified
  by category into **22 train / 14 held-out test**; the held-out 14 never appear
  in training.
- Augmented set = **3,476 rows** (3,410 + 68). Leakage drops:
  v18-name 0 / v18-triple 0 / held-out-theorem 35 / held-out-triple 2 / dedup 0.
- Trained identically to v24 (20 epochs, batch 64, lr 3e-3, embed 96 / hidden
  128, seed 0, beam 10). **Vocab grew 253 → 280** (+27 Mathlib tokens) — the
  concrete mechanism by which augmentation can help.
- Both the **v25 augmented** model and the fixed **v24** model are scored on the
  **same 14 held-out tier-C theorems**, with live Mathlib verification.

## Result on held-out tier-C (the 14 unseen theorems)

| model | best pass@1 | best pass@5 | pass@10 | no-verify |
|---|---|---|---|---|
| v24 zero-shot | 0.429 | 0.571 | 0.571 (8/14) | 6 |
| **v25 augmented** | **0.643** | **0.714** | **0.786 (11/14)** | **3** |

Per transfer flag (learned config):

| transfer | n | v24 pass@10 | **v25 aug pass@10** |
|---|---|---|---|
| core | 6 | 0.667 | **0.833** |
| mathlib | 8 | 0.500 | **0.750** |

**The augmentation strictly helps on tier-C: +3 theorems reachable, 0 lost.**
Newly reachable after augmentation: `v25_bool_true_and` (`(b && true) = b`),
`v25_list_map_id` (`xs.map id = xs`), `v25_nat_mul_one` (`n * 1 = n`) — precisely
the *Mathlib-lemma-needing* shapes the zero-shot v24 generator could not produce
(it now emits `simp` / `Bool.and_true` / `Nat.mul_one`-style tactics for them).
No held-out theorem regressed on the Mathlib side.

This confirms **research question 3 (yes)** and, with Part 4, **research question
4**: the next wall is **generator coverage** (vocabulary + shape), and even a
*tiny* verified Mathlib corpus moves it.

## The catch (forward pointer to Part 6)

The same 68 rows, co-trained from scratch into the broad generator at fixed
capacity/budget, **regress v18 broad-core**: pass@10 0.938 → 0.833, and the
protected `bool` category drops 1.000 → 0.667 (plus negation / exists / nat_succ
/ disjunction). Full detail and the verdict in
[`V25_BROADCORE_REGRESSION_REPORT.md`](V25_BROADCORE_REGRESSION_REPORT.md).

**Net: tier-C transfer is a generator-coverage problem that a tiny verified
corpus can fix, but naive single-model co-training is the wrong delivery
mechanism — it trades broad-core for Mathlib-tier.** v24 remains the broad-core
model; the augmented model is kept only as evidence.

## Files

- `data/processed/v25_tierc_augmented/{train_rows.jsonl,summary.json,test_theorems.json}`
- `data/seeds/v25_mathlib_tierc_test_seeds.jsonl` — the 14 held-out seeds.
- `data/models/token_seq2seq_v25_tierc_augmented/` — the augmented model.
- `data/baselines/v25_aug_tierc_test/` , `data/baselines/v24_zeroshot_tierc_test/`.

## Confirmation

- ✅ split by theorem; held-out 14 absent from train (verified by test).
- ✅ no state_after; no manual oracle; v18 + held-out leakage guards.
- ✅ honest tradeoff reported; no retcon of v24.
