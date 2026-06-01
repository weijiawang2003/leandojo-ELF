# V31 — Part 2: Identifier-Normalization Design

_`src/mini_elf_lean/v31_identifier_normalization.py`. **This is NOT v19 placeholder
decoding.**_

## Why v19 failed, and how v31 differs

v19 abstracted local identifiers to **placeholders** and *replaced* raw generation.
At inference the model emitted placeholders for slots absent in the new state →
`unresolved_placeholder` became the dominant failure (40–44 %) and pass@k dropped
0.583 → 0.208. v31 keeps the *idea* (identifier invariance) but fixes the three things
that made v19 unsafe:

| v19 (failed) | v31 (safe) |
|---|---|
| angle-bracket placeholders (not valid Lean) | **canonical names `c0,c1,…`** — valid Lean identifiers; a canonicalized statement type-checks |
| abstraction *replaces* raw generation | **union**: concretized canonical candidates are *added* to the raw v30 pool (raw fallback always present) |
| unresolved placeholders reach the verifier | **reject-before-verify**: `concretize_or_reject` returns `None` for any unmapped `cN`, dropping it before Lean |

## Approach A — input-side binder canonicalization (primary)

- `parse_binders(statement)` extracts binder identifiers in source order
  (instance binders `[…]` skipped — they bind no new name).
- `build_canonical_map` assigns `c0, c1, …` to those binders (returns `ok=False`,
  i.e. no-op → raw, if there are no binders or a binder already looks like `cN`).
- `canonicalize_text` rewrites real binder identifiers → canonical slots in
  statement / state / tactic (word-boundary, leaving keywords and lemma names alone).
- `concretize_or_reject` inverts on a generated tactic; **`None` if any `cN` is
  unmapped**. Tactic-introduced names (from `intro`/`rintro`) are not `cN`, so they
  pass through unchanged.

**The key property — identifier invariance.** Two parallel theorems that differ only by
identifier naming collapse to the *same* canonical form:

```
(s t : Set α) (x : α) (h : x ∈ s ∩ t) : x ∈ s   exact h.1   ─canon→  exact c4.1
(u v : Set α) (w : α) (hw : w ∈ u ∩ v) : w ∈ u   exact hw.1  ─canon→  exact c4.1
```

So a model trained on canonical data sees **one** projection form regardless of whether
the held-out member uses `h`, `hw`, or `hm` — directly dissolving the v30 token-coverage
ceiling. At inference: canonicalize the new state → decode → `concretize_or_reject` →
union with the raw v30 candidates → verify.

## Approach C — normalized-pattern reranking (fallback / always-on scorer)

`tactic_pattern(tactic)` erases local identifiers to `ID` (keeping lemma names,
operators, projections) so a candidate can be scored against the identifier-free
patterns of known-verified tactics — **without ever emitting a normalized tactic**.
`exact hw.1` and `exact h.1` share the pattern `exact ID.1`.

## Approach B — verified rename augmentation (Part 4, projection families only)

Not normalization but the data complement: add verified projection siblings that *use*
the missing identifiers (`hw`, `hm`, `g`), bringing them in-distribution. Guaranteed
safe (every row Lean-verified). Used if A alone is insufficient — and, given v19's
history, the expected practical winner.

## Verified behaviour (roundtrip checks, mirrored in `tests/test_v31_identifier_normalization.py`)

- `hw` and `h` both → `c4` (invariance) ✓
- `exact c4.1` → `exact hw.1` (concretize) ✓; `exact hw.1` → `exact c4.1` → back ✓
- `exact c9.1` (no slot) → **rejected (`None`)** ✓
- `intro x hx; exact hx.1` passes through ✓
- `(Finset.mem_inter.mp ha).1` roundtrips ✓; `rfl` no-op ✓
- canonical names are valid Lean identifiers; no `state_after`; no placeholders.
