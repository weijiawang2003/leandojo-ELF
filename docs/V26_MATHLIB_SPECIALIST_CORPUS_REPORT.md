# Mini-ELF v26 — Parts 2/3: Mathlib Specialist Corpus Report

`scripts/generate_v26_mathlib_specialist_corpus.py` builds and **verifies** a
tiny-but-broad Mathlib-tier corpus, targeting exactly the categories the v25
audit flagged as generator-bound (Set, order/≤, Mathlib-lemma logic, List).

## Verification method (the throughput win)

All candidates are verified by **whole-file `import Mathlib` typecheck** using
the batched direct-binary verifier (`mini_elf_lean.mathlib_verifier`):
direct v4.30.0 `lean` + precomputed `LEAN_PATH`, many `example` declarations
per file, per-line error attribution.

| metric | value |
|---|---|
| theorems planned | 93 |
| candidate (theorem, tactic) rows proposed | 288 |
| **Lean invocations** | **5** |
| total Lean wall-time | 22.1 s |
| **amortized verify time / candidate** | **0.077 s** |

For comparison, the v25 per-candidate `lake env lean` path would have spent
~288 × ~4.7 s ≈ **22 min** on the same work. The batched verifier is ~60×
faster and removed the elan-shim hang risk.

## Results

* **237 verified training rows** (target was 150–300). ✅
* **8 candidates Lean-rejected** (real API friction — see taxonomy below).
* **0 true coverage gaps** — every theorem with a novel statement has at least
  one Lean-accepted proof.
* **14 theorems were stripped to zero training rows by the leakage guards** —
  these are *benchmark duplicates* (their statements coincide with v25 held-out
  test or v18 broad-core theorems), so their verified proofs are deliberately
  kept **out of training**. This is leakage hygiene, **not** a coverage gap.

### Per-category verified training rows

| category | train rows | candidates | theorems |
|---|---|---|---|
| nat | 66 | 81 | 24 |
| set | **54** | 60 | 19 |
| logic | 49 | 57 | 17 |
| bool_option | 29 | 34 | 12 |
| list | 25 | 41 | 16 |
| function | 14 | 15 | 5 |
| **total** | **237** | **288** | **93** |

### By expected skill (the v25-gap skills are now covered)

| skill | rows | | skill | rows |
|---|---|---|---|---|
| core-shaped | 57 | | arithmetic | 25 |
| **set** | **54** | | **order (≤)** | **37** |
| bool/option | 20 | | list | 18 |
| **mathlib-lemma** | **14** | | function | 12 |

`transfer`: 167 rows need a Mathlib lemma/tactic, 70 are core-shaped.

### Verified proof-head distribution

`exact` 92 · `simp` 47 · `omega` 18 · `intro` 18 · `tauto` 15 · `rfl` 14 ·
`cases` 8 · `rw` 5 · `ring` 4 · `funext` 3 · `apply` 3 · `by_cases` 2.
52/237 rows use `simp`; 54 are Set goals; 37 are order/≤ goals.

## Lean-rejected candidates (API/arity friction taxonomy)

The 8 rejected candidates are **informative** — they pin down where my
hypothesized Mathlib API was wrong, and every affected theorem still has a
verified alternative (`simp` / `rw` / `rfl` / `omega`):

| candidate | error | lesson |
|---|---|---|
| `exact List.length_cons x xs` | function expected | `length_cons` takes **implicit** args here; use `simp`/`rfl` |
| `exact List.length_append xs ys` | function expected | same — use `simp`/`rw [List.length_append]` |
| `exact List.length_reverse xs` | function expected | use `simp` |
| `exact List.mem_cons_self x xs` | function expected | arity differs; use `simp` |
| `left; rfl` (mem_cons_self) | no goals to be solved | `left` already closed it |
| `exact (List.map_map g f xs)` | function expected | use `simp`/`rw [List.map_map]` |
| `simp` (comp assoc) | simp made no progress | definitional; use `rfl`/`funext` |
| `exact Nat.add_sub_cancel` | type mismatch | lemma form differs; use `omega`/`simp` |

**Takeaway:** the friction is *lemma vocabulary/arity*, never the environment
(0 import errors). This matches the v25 audit conclusion.

## Leakage guards applied

* v18 broad-core: 0 name drops, 9 (statement,state,tactic)-triple drops.
* v25 held-out **test**: 34 triple drops (these are exactly the
  benchmark-overlapping easy theorems — n+0=n, s ⊆ s membership, etc.).
* All theorem names are `v26_*`, distinct from v25/v18.

## Honesty

Real `import Mathlib` typecheck (no mock). Manual candidates are corpus targets
**verified by Lean, never used as model predictions**. No `state_after`. Mathlib
is real and lives in the external scratch project (not in this repo).

Artifacts: `data/seeds/v26_mathlib_specialist_seeds.jsonl`,
`data/manual/v26_mathlib_specialist_candidates.jsonl`,
`data/traces/v26_mathlib_specialist_{verified,failed}.jsonl`,
`data/processed/v26_mathlib_specialist/{train_rows.jsonl,summary.json}`.
