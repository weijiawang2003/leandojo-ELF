# V30 — Part 1: v25 Micro-Regression Audit

_`scripts/audit_v30_v25_regression.py` →
`data/baselines/v30_v25_regression/report.json`. Reads v28/v29 eval + verified corpora.
No Lean run; expected proofs are Lean-verified references, never predictions._

v29 dropped 2 of 14 v25 held-out theorems (pass@10 1.000 → 0.857). Both are diagnosed
as **`beam_absence_sparse_sibling`** — the correct tactic is **absent from the v29
top-10 beam**, and the family is sparse in v29 training.

## `v25_nat_add_assoc` — `(a b c : Nat) : a + b + c = a + (b + c)`

| | value |
|---|---|
| rank: v28 → v29 | **1 → none** (regressed) |
| correct tactic in beam? | **No** (absent) |
| v29 train siblings (this family) | **0** |
| v29 top beams | `simp` (no progress), `exact Nat.add_zero a`, `exact Nat.append_assoc a` (hallucinated), `Nat.zero_add a` |
| error classes | type_mismatch 7, unknown_identifier 2 |
| expected | `Nat.add_assoc a b c` / `omega` / `ring` / `simp [Nat.add_assoc]` |

**Why it regressed.** v28 trained an `add_assoc` sibling (`m,n,k`) and emitted the
right tactic at rank 1 for the `(a,b,c)` test. v29 added `add_assoc` siblings under a
*different family tag* (`nat::add_assoc` with `omega`/`Nat.add_assoc`/`ring`), but the
`(a,b,c)` benchmark statement itself is guard-dropped (it's a v25 benchmark), and the
broader v29 distribution shift pushed `omega`/`Nat.add_assoc a b c` **out of the
beam** — the model now emits `simp`/`Nat.add_zero`/hallucinated `Nat.append_assoc`.

## `v25_set_empty_subset` — `(∅ : Set α) ⊆ s`

| | value |
|---|---|
| rank: v28 → v29 | **1 → none** (regressed) |
| correct tactic in beam? | **No** (absent) |
| v29 train siblings (this family) | **0** |
| v29 top beams | `intro x hx; exact hx`, `Set.Subset.refl s`, `Set.Subset.trans s`, `Set.Subset.mpr x hx` (hallucinated) |
| error classes | type_mismatch 5, unknown_identifier 5 |
| expected | `Set.empty_subset s` / `simp` / `intro x hx; cases hx` |

**Why it regressed.** v28 solved this at **density 0** (the model emitted
`Set.empty_subset s`/`simp` from general Set training) — v29 dropped `empty_subset`
from its Set families, and the distribution shift knocked the correct tactic out,
leaving `Subset.refl`/`Subset.trans` confusions. So it is a **ranking/coverage
casualty**, not an unprovable goal (the lemma verifies — Part 0).

## Classification & fix

| theorem | classification | v29 density | fix |
|---|---|---:|---|
| `v25_nat_add_assoc` | beam_absence_sparse_sibling | 0 | densify `add_assoc` to 6 var-sets with `Nat.add_assoc`/`omega`/`ring` |
| `v25_set_empty_subset` | beam_absence_sparse_sibling | 0 | densify `empty_subset` to ~6 with `Set.empty_subset`/`simp` |

Both are **single-tactic, correct-tactic-verifies, absent-from-beam, sparse-family** —
exactly what the density law predicts more siblings should fix. v30 Part 3 adds these
(families **A** `add_assoc` and **B** `empty_subset`) to density ~6. **No ranking
hacks, no manual oracle** — just verified siblings so the canonical tactic re-enters
the beam for any variable naming.
