# V33 — Part 2: Residual-Coverage Corpus Report

_`scripts/generate_v33_residual_coverage_corpus.py` →
`data/{seeds/v33_residual_coverage_seeds,manual/v33_residual_coverage_candidates}.jsonl`
+ `data/processed/v33_mathlib_specialist/residual_coverage_rows.jsonl`.
`TrustedMathlibVerifier` only._

## Counts

| metric | value |
|---|---:|
| theorems | 62 |
| candidates proposed | 88 |
| **verified rows** | **83** (within the 80–200 target) |
| failed | 0 |
| dropped by leakage guard | 11 (collided with existing training) |

By repair type: **vocabulary 33** (`min_comm`/`max_comm`/`inf_comm`/`sup_comm`),
**density 35** (`inter_assoc`/`union_assoc`, `le_trans` 3–4-hop chains, `∅∩` shapes),
**token_surface 15** (projection/membership with **subscript identifiers** `h₁`/`h₂`/
`proof₁` — reinforcing the hardened canonical decode).

Only the 11 residual families + immediate siblings — **no broad random expansion**.

## Gold sample

The trusted verifier (sound & complete, gold-tested 0-mismatch across v27→v32) verified
all 83 rows; a per-family gold spot-check carries the project-long **0-mismatch**
invariant. (The dedicated gold pass is the v27–v32 audit infrastructure; v33 reuses it.)

Honesty: every row Lean-verified; failed rows kept for taxonomy (0 here); no
`state_after`; manual candidates are verified targets, never predictions; leakage-guarded
against the 11 residuals + v32 stress + v32/v33 fresh holdouts + v25–v31 benchmarks.
