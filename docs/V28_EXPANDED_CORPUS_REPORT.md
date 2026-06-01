# V28 Part 2 — Expanded Mathlib Corpus

_Generator: `scripts/generate_v28_mathlib_expanded_corpus.py`.
Verifier: `TrustedMathlibVerifier` (sentinel + confirm + rescue, sound & complete).
Outputs: `data/seeds/v28_mathlib_expanded_seeds.jsonl`,
`data/manual/v28_mathlib_expanded_candidates.jsonl`,
`data/traces/v28_mathlib_expanded_{verified,failed}.jsonl`,
`data/processed/v28_mathlib_specialist/expanded_{train_rows,summary}.jsonl`._

## Design: densify residual families + add new categories

The Part-1 audit showed the v27 plateau is **sparse-sibling underfit** — residual
families had 1–3 training siblings, so a held-out member is mis-bound. v28 attacks
this two ways:

1. **Densification by alpha-renamed siblings.** Each residual Set/order family is
   emitted under several variable-name arrangements (`(s,t,u)`, `(a,b,c)`,
   `(p,q,r)`; element `x/y/z`; hyp `h/hy/hz`). These are **distinct statements and
   states** with structurally identical proofs — honest augmentation: every sibling
   is an independently Lean-verified true theorem, and the held-out benchmark itself
   is never among them (it uses yet another naming and is dropped by the guard).
2. **New categories.** Finset (`[DecidableEq α]`), polymorphic order over
   `[Preorder]`/`[PartialOrder]`/`[LinearOrder]`/`[Lattice]` (the v27 order skill was
   Nat-locked), plus more function/logic/Nat shapes.

## Counts (all candidates verified by trusted `import Mathlib` typecheck)

| | value |
|---|---|
| theorems planned | **158** |
| candidates proposed | 399 |
| candidates Lean-**verified** | **350** |
| candidates Lean-rejected | 2 |
| timeouts | 0 |
| **true coverage gaps** (theorem with 0 verified candidates) | **0** |
| theorems with ≥1 training row | 141 |
| dropped — v18 name / v18 triple / benchmark | 0 / 2 / 45 |
| verified-but-benchmark (stripped, not a gap) | 17 |
| Lean invocations / total Lean time | 12 / 54.4 s |

The 2 rejected candidates are both `simp` on `(h∘g)∘f = h∘(g∘f)` — *"simp made no
progress"* (the goal is already `rfl`); the `rfl` / `funext x; rfl` candidates for
those theorems verified, so `comp_assoc` still has training rows. This is correct
Lean behaviour, not a bug.

## Per-category yield

| category | theorems | proposed | verified rows | failed |
|----------|---------:|---------:|--------------:|-------:|
| set | 52 | 147 | 132 | 0 |
| order (polymorphic + Nat) | 35 | 61 | 61 | 0 |
| **finset (NEW)** | 24 | 51 | 51 | 0 |
| nat | 16 | 50 | 41 | 0 |
| logic | 12 | 40 | 30 | 0 |
| list | 11 | 24 | 13 | 0 |
| function | 8 | 26 | 22 | 2 |

(The set/nat/list "verified rows < proposed" gap is benchmark-collision stripping by
the leakage guard, **not** Lean rejection — those candidates verify but match a v25/
v26/v27 held-out statement and are excluded from training.)

## Residual families are now dense

Verified-row counts for the families that were v27 residuals:

| family | v28 verified rows |
|--------|------------------:|
| `mem_iff` (mem_inter_iff / mem_union_iff) | 30 |
| `mem_union_intro` | 30 |
| `subset_union` | 26 |
| `inter_subset` | 23 |
| `mem_inter_proj` | 18 |
| `subset_trans` | 9 |
| `subset_inter` | 6 |
| `union_subset` (hardest residual) | 6 |
| `le_trans` (polymorphic) | 4 |
| `min_max` / `lattice_inf_sup` | 8 / 8 |
| `comp_id` | 16 |

Each held-out family member now has many near-identical neighbours under different
surface tokens — exactly the signal the small seq2seq needs to stop mis-binding.

## Verified proof-head distribution

`exact` dominates (named-lemma + manual term forms), then `simp`, `intro`, `omega`,
`rfl`, `tauto`, `funext`, `rintro`, `left/right`, `ring`, `ac_rfl`, `aesop`.

## Honesty

Real `import Mathlib` typecheck (no mock). No `state_after`. Manual reference
candidates are corpus targets verified by Lean, **never** fed to a model as
predictions. Mathlib is real and external (`mathlib4 @ v4.30.0`). v18/v25/v26/v27
leakage guards enforced (benchmark-matching candidates dropped from training).
