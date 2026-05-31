# Mini-ELF v18 — Benchmark Design

**Goal of v18 (verbatim, from the brief).** *"Build and evaluate a
less-templated Lean benchmark to find the next generator/ranker
wall."*

v17 closed the v11 family-LOFO **templated** benchmark to mean
pass@5 = 1.000 on 30 unique test theorems. That result does **not
imply full theorem proving** — the test set is a small templated
corpus with ≤10 unique tactic patterns. v18 deliberately moves off
that benchmark to find what the v17 pipeline cannot do.

## 1. Three tiers (the brief)

| tier | description | included in v18 |
|---|---|---|
| **A. Core-Lean hand-written** | 50–100 theorem statements over Prop / Nat / Bool, varied (not Cartesian templates), mix of tactic shapes | **YES** |
| **B. Mathlib-style syntax, core-Lean only** | theorem shapes inspired by Mathlib tactics but using only core Lean 4 (no Mathlib import) | **YES (merged into Tier A)** |
| **C. Mathlib fragment** | 20 tiny Mathlib theorems with imports | **SKIPPED** — see §3 |

For practical purposes Tiers A and B are merged in this run — the
distinction in the brief was "Mathlib-style proof shapes are OK as
long as core Lean accepts them". Every theorem in v18 is in core
Lean 4.30.0 with no imports.

## 2. Why merge Tier A and B

The brief lists 10 categories to cover (implication, conjunction,
disjunction, negation, equality rewrite, exists, forall, Nat-succ,
Bool, List). Some of these naturally use Mathlib-style tactics
(`exact fun`, `False.elim`, `Exists.elim`, `Or.elim`) which are
**built into core Lean 4** even without Mathlib. Splitting them into
two tiers would have been bookkeeping without benefit; the per-row
`category` metadata still carries the distinction.

## 3. Tier C deferred (Mathlib)

We probed the local environment:

```
$ echo 'import Mathlib' > /tmp/mathlib_check.lean
$ lean /tmp/mathlib_check.lean
/tmp/mathlib_check.lean:1:0: error: unknown module prefix 'Mathlib'
```

Mathlib is **not** installed in this environment. The brief is
explicit:

> "Tier C: optional Mathlib fragment — only if local environment
> supports Mathlib quickly. If Mathlib is unavailable, skip honestly."

Tier C is **skipped honestly**. This is not a v18 failure; it's a
benchmark scoping decision documented in `V18_BROAD_CORE_REPORT.md`
and `RESULTS_SUMMARY.md`.

A v19 task is to install Mathlib (likely via a Lean toolchain
upgrade + `lake update Mathlib`) and re-run v18 against the Mathlib
fragment; or to use LeanDojo's traced Mathlib once
`run_tac` is unblocked.

## 4. The 10 categories

| # | category | example theorem | typical proof |
|---|---|---|---|
| 1 | implication / intro | `(p : Prop) (hp : p) : p` | `exact hp` |
| 2 | conjunction intro | `(p q : Prop) (hp : p) (hq : q) : p ∧ q` | `exact ⟨hp, hq⟩` |
| 3 | disjunction cases | `(p q r : Prop) (h : p ∨ q) (hp : p → r) (hq : q → r) : r` | `cases h with | inl hp' => exact hp hp' | inr hq' => exact hq hq'` |
| 4 | negation / contradiction | `(p : Prop) (hp : p) (hnp : ¬p) : False` | `exact hnp hp` |
| 5 | equality rewrite | `(n m : Nat) (h : n = m) : m = n` | `exact h.symm` |
| 6 | exists intro | `(p : Nat → Prop) (h : p 3) : ∃ n, p n` | `exact ⟨3, h⟩` |
| 7 | forall instantiation | `(p : Nat → Prop) (h : ∀ n, p n) : p 7` | `exact h 7` |
| 8 | Nat succ / zero | `(n : Nat) : n.succ = n + 1` | `rfl` |
| 9 | Bool cases | `(b : Bool) : b = true ∨ b = false` | `cases b <;> simp` (if `simp` core), else explicit |
| 10 | List simple | `(α : Type) (xs : List α) : xs ++ [] = xs` | `exact List.append_nil xs` (if core), else `induction` |

`simp` is in core Lean 4 but with a much smaller default simp set
than Mathlib provides. Some category-9/10 theorems may fall back
to explicit case-analysis proofs.

## 5. Sizing target

| tier | category count | theorems per category | target total |
|---|---:|---:|---:|
| A/B merged | 10 | 5–10 | **~75 theorems** |

Each theorem carries 1–5 candidate tactics (a mix of correct and
incorrect proof shapes — incorrect ones used for the failure-class
taxonomy in Part 7). After lean-cli verification, a subset survives
as positive labels; honest about zero-success theorems.

## 6. Variable-name policy

The v18 corpus uses **mixed** variable naming:

* Single-letter Greek + Latin (`p`, `q`, `α`, `n`, `m`, `xs`).
* Multi-letter descriptive names (`hp`, `hq`, `hand`, `xs`, `prf`).
* Mathlib-style camelCase identifiers (`xs`, `goal`, `hImp`).

This is intentional: the v18 brief wants *less templated*, so the
benchmark must avoid the v11/v16/v17 trap of "same variable pair
across many theorems". We do NOT reuse the v11 LOFO test variable
pairs `((p,q)/(a,b)/(x,y)/(m,n)/(a,d))` exclusively; we
deliberately include them ALONGSIDE other namings so the v17 model's
sensitivity to identifier choice is exposed.

## 7. Splits

For Parts 4 (zero-shot) and 5 (synthetic-trained, tested on v18) we
do not split v18 — every v18 theorem is held-out from any v17 train
set by construction (different theorem names, different statements).

For Part 6 (optional v18 fine-tune, only if zero-shot collapses), we
split v18 by **theorem name** (not by candidate) so candidates from
the same theorem cannot leak across train/test:

* train 70 % / val 15 % / test 15 %, stratified by category if
  possible.

## 8. What v18 metrics are

For each evaluated configuration:

* `pass@1` / `pass@5` / `pass@10`
* per-category breakdown
* malformed candidate rate
* timeout rate (lean-cli at warm 120 s)
* "no-candidate-verified" theorem count
* first-verified-rank distribution
* `tactic-head accuracy` (does the predicted top-1 candidate's
  first token match a tactic head that any verifying candidate
  uses?)

## 9. What v18 is NOT

* **Not Mathlib.** Tier C skipped honestly.
* **Not a templated benchmark.** v11 LOFO scoped 5 families × 3
  variable pairs; v18 spans 10 categories with mixed naming.
* **Not full theorem proving.** Even at 100 % pass@5 on v18, the
  ~75-theorem core-Lean corpus is still a *tiny* benchmark
  relative to Mathlib (~200 k theorems).
* **Not retconning v11–v17.** All prior metrics on disk are
  unchanged. v18 publishes at parallel paths under
  `data/baselines/v18_*/`.
* **Not state_after.** Same template-substitution lean-cli backend.
* **Not manual oracle.** Candidates in v18 train/test come from
  human-edited templates **but**: the train rows are
  lean-cli-verified before being used as labels (same honesty bar as
  v16/v17). At evaluation time the model's beam is the *prediction*;
  manual candidates are gold labels and never count as model
  outputs.
