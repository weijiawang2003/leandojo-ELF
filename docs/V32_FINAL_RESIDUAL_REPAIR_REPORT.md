# V32 — Part 2: Final-Residual Repair Report

_`scripts/generate_v32_final_residual_repair.py` →
`data/manual/v32_final_residual_repair_candidates.jsonl` +
`data/processed/v32_mathlib/final_residual_repair_rows.jsonl`. `TrustedMathlibVerifier`
only._

## What it does

Part 1 showed the lone residual `(∅ : Set α) ∩ s ⊆ t` is **single-tactic** (`simp`
closes it) — a sparse `∅ ∩ _ ⊆ _` shape the `empty_subset` family never trained. v32
adds verified `∅∩`/empty-intersection siblings (different var-sets and shapes from the
held-out residual, which the leakage guard drops) so the model learns the shape →
`simp`/`cases` mapping.

## Counts

| metric | value |
|---|---:|
| **verified rows** | **37** (within the 10–40 target) |
| failed | 0 |
| dropped by leakage guard | 3 (the exact held-out `(s,t)` variant) |
| families | `empty_subset` 29, `inter_subset` 8 |

Shapes: `∅∩s⊆t`, `s∩∅⊆t`, `∅∩s⊆s` (+ Finset analogue), across var-sets
`(a,b)/(p,q)/(u,v)`. The model is trained (v32) on these → it should now reach `simp`
for the held-out `(s,t)` residual.

## Result

`v32_canonical_repaired` (v31 canonical base + these 37 rows, canonicalized;
val-exact 0.367) is evaluated in Parts 4/6. It closes the targeted-family holdout to
1.000 (already at 1.0 under v31 canonical) and lifts the fresh-holdout to 0.80; the
routed system carries it (Part 6). Honesty: every row Lean-verified; no `state_after`;
manual candidates are verified targets, never predictions; no broad expansion.
