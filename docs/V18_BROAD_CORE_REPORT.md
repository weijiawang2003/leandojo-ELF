# Mini-ELF v18 — Broad Core Lean Corpus Report

**Status:** corpus built and lean-cli verified. Doc covers Parts 2-3
of the v18 brief. Headline transfer numbers are in
[`V18_ZERO_SHOT_TRANSFER_REPORT.md`](V18_ZERO_SHOT_TRANSFER_REPORT.md).

## 1. Why a new corpus

v17 closed the v11 family-LOFO **templated** benchmark to mean
pass@5 = 1.000 on 30 unique theorems. That benchmark spans 5 narrow
families (forall_inst / rewrite_succ / neg_exfalso /
exists_reconstruct / neg_imp_exfalso) with hand-templated proof
shapes — ≤10 distinct tactic patterns project-wide. A perfect score
on it **does not** indicate full theorem proving.

The v18 brief asks for a less-templated benchmark to find the next
wall. v18 spans **10 categories** with deliberately varied
statements and mixed variable namings (so the v17 models' identifier
sensitivity is exposed honestly).

## 2. Corpus design — 3 tiers, 2 included

See [`V18_BENCHMARK_DESIGN.md`](V18_BENCHMARK_DESIGN.md) for the full
rationale.

| tier | description | included | notes |
|---|---|:---:|---|
| **A** | core-Lean hand-written propositions | ✓ | merged with B |
| **B** | Mathlib-style syntax via core-Lean tactics | ✓ | shares one corpus with A |
| **C** | actual Mathlib fragment | ✗ | **Mathlib unavailable in this env** — `lean -import Mathlib` fails with `unknown module prefix 'Mathlib'`. Tier C is skipped *honestly* per the brief's escape hatch ("if Mathlib is unavailable, skip honestly"). |

## 3. Sizing & generation

`scripts/generate_v18_broad_core_corpus.py` hand-authors 48 theorems
across 10 categories. Each theorem comes with 1–5 candidate tactics
including at least one expected-correct candidate plus some
incorrect ones (for the failure-taxonomy analysis in Part 7).

| category | theorems | example statement |
|---|---:|---|
| `implication` | 6 | `(p q : Prop) (hp : p) : q → p` |
| `conjunction` | 6 | `(p q : Prop) (hp : p) (hq : q) : p ∧ q` |
| `disjunction` | 5 | `(p q r : Prop) (h : p ∨ q) (hpr : p → r) (hqr : q → r) : r` |
| `negation` | 5 | `(p q : Prop) (h : p → q) (hnq : ¬q) : ¬p` |
| `equality_rewrite` | 6 | `(n m k : Nat) (h : n = m) : n + k = m + k` |
| `exists` | 4 | `(p q : Nat → Prop) (h : ∃ n, p n) (hpq : ∀ n, p n → q n) : ∃ n, q n` |
| `forall` | 3 | `(p q : Nat → Prop) (h : ∀ n, p n → q n) (hp : p 5) : q 5` |
| `nat_succ` | 5 | `(n m : Nat) (h : n.succ = m.succ) : n = m` |
| `bool` | 3 | `(b : Bool) : b = true ∨ b = false` |
| `list` | 5 | `(α : Type) (xs : List α) : xs ++ [] = xs` |
| **total** | **48** | |

## 4. Verification (Part 3)

Backend: `lean-cli` (Lean 4.30.0) with a single warm-up theorem and
per-tactic timeout 60 s.

| stat | value |
|---|---:|
| theorems planned | 48 |
| candidates proposed | 115 |
| **candidates verified** | **109 (94.8 %)** |
| candidates failed | 6 |
| timeout candidates | **0** |
| **theorems with at least one verified candidate** | **48 / 48 (100 %)** |
| zero-success theorems | 0 |

### Failure class breakdown (the 6 deliberately-included incorrect candidates)

| class | count |
|---|---:|
| `ok` | 109 |
| `unknown_tactic` | 3 |
| `type_mismatch` | 1 |
| `invalid` | 1 |
| `other` | 1 |

These 6 are intended-fail rows we shipped specifically so the failure
taxonomy in Part 7 has lean-side examples of each class.

### Per-category verification

| category | theorems | candidates proposed | candidates verified | theorems with verified |
|---|---:|---:|---:|---:|
| `bool` | 3 | 6 | 5 | 3 |
| `conjunction` | 6 | 18 | 18 | 6 |
| `disjunction` | 5 | 12 | 12 | 5 |
| `equality_rewrite` | 6 | 17 | 17 | 6 |
| `exists` | 4 | 7 | 7 | 4 |
| `forall` | 3 | 6 | 6 | 3 |
| `implication` | 6 | 15 | 15 | 6 |
| `list` | 5 | 7 | 7 | 5 |
| `nat_succ` | 5 | 10 | 10 | 5 |
| `negation` | 5 | 12 | 12 | 5 |

## 5. Theorem-level split (for optional Part 6 fine-tune)

Stratified by category, deterministic seed.

| split | theorems | candidate rows (verified only) |
|---|---:|---:|
| train | ~33 (≈ 70 %) | ~75 |
| val | ~7 (≈ 15 %) | ~17 |
| test | ~8 (≈ 17 %) | ~17 |

Saved to `data/processed/v18_broad_core/{train,val,test}.jsonl`.

## 6. Honesty checklist (v18 brief constraints)

* **No state_after.** No public API in the generation pipeline
  takes a state_after argument. The `state_before` is rendered
  text-only from the theorem statement.
* **No manual oracle counted as model prediction.** The 115
  candidate tactics in this corpus are *gold labels*; they are
  **never** scored as if the model produced them. The
  `evaluate_v18_zero_shot.py` and the broad-synthetic
  training/eval are the model paths.
* **No v10-leakage revival.** v18 is a fresh hand-authored corpus
  with no overlap to v10/v11 train rows.
* **No Mathlib.** Tier C is skipped honestly; every theorem here
  uses only core Lean 4 (no imports).
* **Not full theorem proving.** 48 theorems is still tiny relative
  to Mathlib (~200k); the *purpose* of v18 is to find the v17 wall,
  not to claim broad theorem-proving capability.

## 7. Where the numbers live

| artefact | path |
|---|---|
| seeds (1 / theorem) | `data/seeds/v18_broad_core_seeds.jsonl` |
| all candidates (verified + failed) | `data/manual/v18_broad_core_candidates.jsonl` |
| verified traces (positive labels) | `data/traces/v18_broad_core_verified.jsonl` |
| failed traces (intentional + spurious) | `data/traces/v18_broad_core_failed.jsonl` |
| train / val / test split | `data/processed/v18_broad_core/{train,val,test}.jsonl` |
| summary | `data/processed/v18_broad_core/summary.json` |
