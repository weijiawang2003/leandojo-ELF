# V31 — Part 0: Repo / Process / Environment Status

_Start of the Mini-ELF v31 token-coverage / identifier-normalization run._

## Git (untouched — constraints forbid abort/reset/rebase/commit)

- `HEAD` = `b4fcd6c` on `v27-mathlib-specialist`; **0 new commits** (v28–v30 also
  committed nothing). Stale **`.git/rebase-merge/` from 2026-05-28 present, untouched**.
  v31 makes **zero git changes**.

## Processes

No stale `lean`/`lake`/`pytest` jobs (only OS daemons). Clean start.

## Toolchain

Lean **4.30.0**, Lake **5.0.0**; external pinned Mathlib at
`~/code/mini_elf_mathlib_probe`; verifier uses the direct toolchain binary + cached
`LEAN_PATH`. All four v31-relevant lemmas verify (`Set.mem_inter_iff`,
`Finset.mem_inter`, `Set.union_subset`, `Nat.add_assoc`).

## The v19 lesson v31 must NOT repeat

A prior **v19 identifier-abstraction** attempt (`docs/V19_IDENTIFIER_ABSTRACTION_REPORT.md`,
`src/mini_elf_lean/{local_context,identifier_abstraction}.py`) was a **documented
negative result**: abstracting local identifiers to **placeholders** *replaced* the
`unknown_identifier` failure class with a new dominant `unresolved_placeholder` class
(40–44 %) and **dropped pass@k 0.583 → 0.208** — the model emitted placeholders for
slots absent in the new state, and abstraction *replaced* raw generation.

v31's design differs on three points that make it safe (Part 2):

1. **Valid Lean identifiers**, not angle-bracket placeholders — canonical names like
   `c0`, `c4` are real binder names; a canonical statement type-checks.
2. **Union, not replacement** — concretized canonical candidates are added to the
   **raw v30 pool**; raw fallback is always present, so v31 can only *add* coverage.
3. **Reject-unresolved-before-verify** — any candidate still carrying an unmapped
   canonical token is dropped *before* Lean ever sees it, so the
   `unresolved_placeholder` failure mode cannot occur.

We **reuse** v19's `local_context.parse_state` parser; we do **not** reuse its
placeholder decoder as the main model (constraint).

## v30 state v31 starts from

| metric | v30 | v31 obligation |
|---|---|---|
| v25 / v26 / v27 / v29 held-out pass@10 | 1.000 | preserve |
| v28 fresh holdout pass@10 | 0.967 | preserve ≥0.967 |
| routed broad-core p@5 / p@10 | 0.9375 / 0.9583 | preserve (v24 untouched) |
| `_3` projection / token-diversity residuals | ~0.82 (flat) | **improve** |
| remaining residuals | 13 (5 vocab / 8 API / 0 multi-step) | reduce if possible |
| trusted-verifier gold mismatches | 0 | maintain 0 |

## Refined density law (from v30) v31 acts on

Density helps **only when the held-out member's surface tokens are in-distribution**.
v31 attacks that token-coverage ceiling via (A) input-side canonicalization, (B)
verified rename augmentation for projection families, (C) ranker-time normalized
pattern scoring — **not** v19 generation-time placeholders.

## Honesty constraints

Trusted verifier only · no `state_after` · no manual-oracle predictions · no v10
leakage · no full-proving claim · no naive verifier for headline metrics · v24
untouched · no category balancing · no capacity probe (unless all normalization fails)
· **not v19 placeholder generation** · git untouched.
