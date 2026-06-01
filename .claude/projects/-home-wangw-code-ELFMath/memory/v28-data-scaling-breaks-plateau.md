---
name: v28-data-scaling-breaks-plateau
description: v28 broke the v27 fresh-holdout plateau by densifying sibling shapes + adding Finset; data-coverage-bound confirmed, broad-core preserved.
metadata:
  type: project
---

Mini-ELF v28 (completed 2026-05-31) tested whether the v27 fresh-holdout plateau
(pass@10 **0.714**) was data-volume bound. It was — and scaling verified single-tactic
shapes broke it.

**Diagnosis (Part 1):** v27 residuals (`mem_inter_iff`, `union_subset`, …) are
**sparse-sibling underfit** — the small seq2seq lands in the right neighbourhood but
**mis-binds** the identifier/shape when a family has 1–3 siblings (emits the *swap*
`⟨h.2,h.1⟩` for `s∩t⊆s`; hallucinates `Nat.append_assoc`). Single-tactic-provable, not
a planning/architecture wall.

**Fix:** densify each residual family with alpha-renamed siblings (distinct
statements, identical proofs — honest augmentation; benchmark guard-dropped) + new
categories. Corpus **158 theorems → 350 verified rows, 0 coverage gaps** (set 132,
order 61, **finset 51 NEW**, nat 41, logic 30, function 22, list 13). Trusted verifier
only; integrity 350/350; gold sample 24/all-7-cats, **0 mismatches / 0 false positives**.

**Results (`token_seq2seq_v28_general`, recommended):**
- v25 held-out **1.000** preserved, v26 **0.955** preserved
- **fresh v27 holdout 0.714 → 0.857** (best v28 config **1.000**); `mem_inter_iff`
  solved @ rank 0 via `simp [Set.mem_inter]`
- **new 30-theorem v28 holdout 0.867** (vs 0.667 v27-best)
- new **Finset** category **0.833** held-out
- routed broad-core **bit-identical** 0.9375/0.9583 (v24 untouched, adopt_router=True),
  routed Mathlib tier 0.918 over 73 combined held-outs
- **category balancing harmful again** (0.700 vs 0.867)

**Key levers / gotchas for v29:**
- Whole-category transfer is weak (set 0.237, finset 0.333; order 0.778 because it
  overlaps Nat `≤`) → success is **within-family sibling density**, not generic
  transfer. Each new category needs its own siblings.
- Prefer **unweighted `general`** config; never category-balance.
- New residuals are single-sibling shapes: Finset projection direction
  (`Finset.mem_of_mem_inter_left/right`), `le_antisymm`, renamed `comp_assoc` — densify
  these next.
- LeanDojo next-state still premature (1/5 residuals multi-step).
- Polymorphic order needs typeclass binders (`[Preorder]`/`[LinearOrder]`/`[Lattice]`);
  Finset needs `[DecidableEq α]`.

New code: `scripts/{audit_v28_mathlib_residuals,generate_v28_mathlib_expanded_corpus,
verify_v28_mathlib_expanded_corpus,build_v28_mathlib_dataset,train_v28_mathlib_specialist,
evaluate_v28_mathlib_specialists,evaluate_v28_routed_system,analyze_v28_scaling_plateau}.py`,
`src/mini_elf_lean/v28_mathlib_router.py` (V28MathlibRouter + optional Finset sub-route,
off by default). Builds on [[v27-scaled-mathlib-specialist]] and
[[lean-verifier-use-direct-toolchain-binary]].

Repo note: a **stale `.git/rebase-merge/` from 2026-05-28** was present and left
untouched (constraints forbid abort/reset/rebase/commit); v28 made no git changes.
