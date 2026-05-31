# V25 Mathlib tier-C corpus report (Parts 2–3)

Generator: [`scripts/generate_v25_mathlib_tierc_corpus.py`](../scripts/generate_v25_mathlib_tierc_corpus.py).
Summary JSON: `data/processed/v25_mathlib_tierc_corpus/summary.json`.

This is the **real-Mathlib path** (Part 2A) — the env probe confirmed Mathlib
v4.30.0 imports ([`V25_MATHLIB_ENV_REPORT.md`](V25_MATHLIB_ENV_REPORT.md)), so
the core-Lean surrogate fallback (Part 2B) was **not** used.

## What was built

**36 tiny Mathlib-tier theorems**, each with 2–5 reference candidate tactics,
spanning 5 categories. Every candidate is verified by **whole-file typecheck
against real Mathlib** — `lake env lean` with `import Mathlib`, run inside the
external scratch project `../mini_elf_mathlib_probe`. The `import Mathlib` line
is the fixed *environment*; it is not predicted by any model.

| category | theorems | candidates verified | rows | example goal |
|---|---|---|---|---|
| nat | 10 | 31 | 31 | `0 + n = n`, `a + b = b + a`, `n ≤ n + 1` |
| list | 7 | 11 | 11 | `xs ++ [] = xs`, `(xs ++ ys).length = …`, `xs.map id = xs` |
| bool_option | 6 | 16 | 16 | `(b && true) = b`, `(!!b) = b`, `o.map id = o` |
| set | 5 | 17 | 17 | `s ⊆ s`, `a ∈ {a}`, `s ∩ t ⊆ s`, `∅ ⊆ s` |
| logic | 8 | 28 | 28 | `p ∨ ¬p`, `p ∧ q → q ∧ p`, `p ↔ p` |
| **total** | **36** | **103** | **103** | |

## Verification result (Part 3)

| metric | value |
|---|---|
| theorems | 36 |
| candidates proposed | 114 |
| candidates **verified** | **103** |
| candidates failed | 3 |
| timeouts | 0 |
| **zero-success theorems** | **0** (every theorem has ≥1 verified proof) |
| dropped by v18 name guard | 0 |
| dropped by v18 (stmt,state,tactic) triple guard | 8 |
| imports used | `import Mathlib` |
| Lean command | `lake env lean` (inside `mini_elf_mathlib_probe`) |
| Mathlib available | **yes** (v4.30.0, commit `c5ea00351c28`) |

**Transfer design.** Of the 36 theorems, **16 are "core"** (a broad-core-style
tactic such as `rfl`/`exact ⟨…⟩`/`intro` should suffice) and **20 are
"mathlib"** (expected to need a Mathlib lemma name or tactic like `simp`/`omega`/
`ring`/`tauto`/`Set.*`). This split is what makes the zero-shot transfer test
(Part 4) meaningful: it separates "can the v24 generator reuse a skill it has"
from "does it know the Mathlib-specific move".

### The 8 triple-guard drops (leakage control working)

8 reference candidates exactly matched a v18 core-Lean `(statement, state_before,
tactic)` triple and were dropped from the stored corpus — e.g. `n + 0 = n` by
`rfl`, `0 + n = n` by `simp`. One originally-planned item,
`(x :: xs).length = xs.length + 1`, was **identical** to a v18 theorem (both
`rfl` and `simp`), so it was replaced with the distinct
`(xs ++ ys).length = xs.length + ys.length` to keep the benchmark genuinely
novel vs v18. After the swap, **no theorem is left with zero verified
candidates.**

### The 3 verification failures (honest Mathlib-API friction)

All 3 are `Function expected` errors on explicit-argument lemma applications:

- `exact List.length_append xs ys`
- `exact List.length_reverse xs`
- `exact List.mem_cons_self x xs`

In Mathlib v4.30.0 these lemmas are stated with **implicit** list arguments
(`@[simp] theorem length_reverse {l} : l.reverse.length = l.length`), so applying
them to explicit `xs`/`ys` is a type error. Each of these theorems still has a
verified proof (via `simp`), so coverage is unaffected — but the failures are a
real, recorded data point for research question 2 (the wall is partly Mathlib
**identifier/arity vocabulary**, not just theorem shape). They are written to
`data/traces/v25_mathlib_tierc_failed.jsonl`, not silently dropped.

## Files

- `data/seeds/v25_mathlib_tierc_seeds.jsonl` — 36 benchmark seeds.
- `data/manual/v25_mathlib_tierc_candidates.jsonl` — 103 **verified** reference
  candidates (corpus targets; **never fed to the model as predictions**).
- `data/traces/v25_mathlib_tierc_verified.jsonl` — 103 verified rows.
- `data/traces/v25_mathlib_tierc_failed.jsonl` — 3 failed candidates + errors.
- `data/processed/v25_mathlib_tierc_corpus/{train_rows.jsonl,summary.json}`.

## Confirmation

- ✅ real `lake env lean` Mathlib typecheck; **no mock verification**.
- ✅ no unverified candidate counted as positive.
- ✅ manual candidates are verified corpus targets, **not model predictions**.
- ✅ no state_after; v18 name + triple leakage guards applied.
