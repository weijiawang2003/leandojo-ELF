# V20 implication + bool corpus report

The v20 brief asks two corpus-level questions following v19's honest
negative result:

> 1. Does adding trivial implication shapes improve the v18 implication category?
> 2. Does adding Bool cases examples improve the v18 bool category?

This document records the corpus generation step (Parts 2–3 of the
v20 brief). The actual transfer measurements live in
[`V20_BROAD_TRANSFER_REPORT.md`](V20_BROAD_TRANSFER_REPORT.md).

## Why these two categories

The v18 broad-only baseline scored **0.000 pass@5** on both
`implication` and `bool` rows. The v20 [shape-gap
audit](V20_SHAPE_GAP_AUDIT.md) confirmed why:

- **bool** has *zero* training support across v11+v16+v17. The
  substring probes `cases b`, `Bool`, and `decide` all return 0
  rows out of 3,984. The model has never seen a Bool data shape.
- **implication** is more subtle. The probe `exact hp` matches 400
  training rows — so the bare identity proof shape *is* in
  training. But the v18 broad-only model emits
  `exact (hpfalse hp).elim` (a v17 contradiction shape) on the
  v18 implication state, where `hpfalse` is out of scope. The
  rank, not the shape, is the issue. v20 corpus adds many fresh
  implication shapes so the model learns to emit *bare*
  identity / modus-ponens / composition without a `.elim` tail.

## Implication corpus

[`scripts/generate_v20_implication_corpus.py`](../scripts/generate_v20_implication_corpus.py)
produces seven surface families:

| family | example statement | canonical proof |
|---|---|---|
| `implication_identity` | `(a : Prop) (hp : a) : a` | `exact hp` |
| `implication_intro_const` | `(p q : Prop) (hp : p) : q → p` | `intro hq\n  exact hp` |
| `implication_modus_ponens` | `(p q : Prop) (h : p → q) (hp : p) : q` | `exact h hp` |
| `implication_compose` | `(p q r) (hpq : p→q) (hqr : q→r) (hp : p) : r` | `exact hqr (hpq hp)` |
| `implication_fun_compose` | `(A B C : Type) (f : A→B) (g : B→C) (a : A) : C` | `exact g (f a)` |
| `implication_swap_args` | `(p q r) (h : p→q→r) (hq : q) (hp : p) : r` | `exact h hp hq` |
| `implication_arrow_arrow` | `(p q) (h : (p→q)→p) (hpq : p→q) : p` | `exact h hpq` |

Multiple variable-name and hypothesis-name combinations are tried
per family so the model sees the *role* across surface
realisations (e.g. `h`, `himp`, `hpq`, `hf`, `hImp` all play the
implication-hypothesis role).

### Lean / corpus rules

* Every candidate verified by lean-cli (`lean` direct, not `lake
  env lean` — the latter triggered a lakefile discovery hang on
  WSL).
* `MINI_ELF_LEAN_COMMAND=lean` enforces direct binary invocation.
* No Mathlib (`uses_mathlib: false`, no imports).
* No `state_after`.
* No manual oracle (each candidate is a Lean syntactic proof; only
  those Lean accepts are kept).
* v18 leakage guards by `theorem_name` and by
  `(theorem_statement, state_before, tactic)` triple. Both report 0
  drops by construction (names use `v20_imp_*`, variable names are
  drawn from a disjoint pool).
* WSL subprocess flakiness occasionally returns spurious 30s
  timeouts; the generator retries once on timeout before
  classifying as a real failure. The retry never substitutes a
  passing candidate for a failing one — only converts intermittent
  noise into real success.

### Counts

`lean-cli` (direct `lean`, not `lake env lean`) verified **759 / 760**
proposed candidates across **266 theorems**; the single drop was a
spurious retry-timeout on a redundant `exact (h hp) hq` variant whose
sibling candidates for the same theorem verified. **0** leakage drops
on both the name and triple guards.

| family | theorems | verified / proposed |
|---|---:|---:|
| `implication_identity` | 40 | 40 / 40 |
| `implication_intro_const` | 72 | 288 / 288 |
| `implication_modus_ponens` | 40 | 120 / 120 |
| `implication_compose` | 35 | 105 / 105 |
| `implication_fun_compose` | 24 | 72 / 72 |
| `implication_swap_args` | 25 | 74 / 75 |
| `implication_arrow_arrow` | 30 | 60 / 60 |
| **total** | **266** | **759 / 760** |

See [`data/processed/v20_implication_corpus/summary.json`](../data/processed/v20_implication_corpus/summary.json).

## Bool corpus

[`scripts/generate_v20_bool_corpus.py`](../scripts/generate_v20_bool_corpus.py)
produces seven Bool families:

| family | example statement | canonical proof |
|---|---|---|
| `bool_refl` | `(b : Bool) : b = b` | `rfl` |
| `bool_cases_taut` | `(b : Bool) : b = true ∨ b = false` | `cases b <;> simp` |
| `bool_no_conf` | `(b : Bool) : b = false ∨ b = true` | `cases b <;> simp` |
| `bool_if_id` | `(b : Bool) : (if b then true else false) = b` | `cases b <;> rfl` |
| `bool_eq_rw` | `(b : Bool) (h : b = true) : b = true` | `exact h` |
| `bool_double_neg` | `(b : Bool) : !!b = b` | `cases b <;> rfl` |
| `bool_and_rw` | `(b : Bool) (h : (b && true) = true) : b = true` | `exact h` (definitional) |

Some syntactic variants (e.g. `simpa`, `by_cases`) require Mathlib
or have core-Lean variants that fail elaboration. The generator
proposes all variants and **persists only those Lean accepts**.
The failure list is logged but kept out of the verified set.

### Counts

`lean-cli` verified **189 / 239** proposed candidates across **77
theorems**. The 49 rejects are the deliberately-included
`by_cases`/`simpa`/`rw [Bool.and_true]` variants that fail core-Lean
elaboration (the `by_cases h : b = true` form leaves a goal that
`Or.inl rfl` cannot close after the redundant `cases`) — proposing
and discarding them is exactly the "propose-all, persist-only-verified"
discipline. **1** triple-guard drop (a generic `rfl` proof coinciding
with a v18 row, correctly removed); **0** name-guard drops. Every one
of the 7 families retains verified candidates:

| family | theorems | verified / proposed |
|---|---:|---:|
| `bool_refl` | 11 | 33 / 33 |
| `bool_cases_taut` | 8 | 24 / 32 |
| `bool_no_conf` | 6 | 11 / 18 |
| `bool_if_id` | 6 | 11 / 18 |
| `bool_eq_rw` | 25 | 68 / 75 |
| `bool_double_neg` | 6 | 16 / 18 |
| `bool_and_rw` | 15 | 26 / 45 |
| **total** | **77** | **189 / 239** |

The `cases b <;> simp` and explicit `cases b\n  · exact Or.inl rfl\n
· exact Or.inr rfl` forms both verify in core Lean — so the Bool
case-split shape the v18 `bool` category needs **is** now present in
training. `simp` and `decide` are core-Lean tactics (no Mathlib
required); `<;>` combinator works.

See [`data/processed/v20_bool_corpus/summary.json`](../data/processed/v20_bool_corpus/summary.json).

## Why corpus-then-train, not corpus-as-eval

The v20 brief separates corpus design from transfer measurement.
Adding the corpus to v18's broad-synthetic training pool produces
a *single* retrained model whose evaluation gives the honest
transfer signal. The corpus alone tells us only that the shapes
*can* verify in Lean; the transfer report tells us whether the
model *learns* them well enough to displace the v17-pattern
suggestions on a v18 implication state.

## Claims this report does NOT make

* It does not claim v20 generalises to Mathlib (no Mathlib in env).
* It does not claim the corpus is exhaustive across implication
  shapes (forall, exists, sigma, etc. are explicitly *not*
  targeted here — v18 already handles forall, exists is the
  next-priority residual after v20).
* It does not retcon v19 — v19 generation-time abstraction stays
  a negative result.
* It does not use `state_after` anywhere.
