# V31 — Part 4: Projection Rename-Augmentation Report

_`scripts/generate_v31_projection_rename_aug.py` →
`data/manual/v31_projection_rename_aug_candidates.jsonl` +
`data/processed/v31_canonical_mathlib/projection_rename_aug_rows.jsonl`.
`TrustedMathlibVerifier` only — data augmentation, NOT placeholder decoding._

## What it does

Approach B brings the **missing identifiers** (Part 1: `hw`, `hm`, `g`/`hg`, `h3`,
`hmem`) in-distribution by generating **verified** projection/membership siblings that
*use* them, with set names that differ from the held-out statements.

## Counts

| metric | value |
|---|---:|
| **verified rows** | **140** (within the 50–150 target) |
| failed | 0 |
| dropped by leakage guard | 0 |
| Lean wall | 26.2 s |

| breakdown | |
|---|---|
| by family | `mem_inter_proj` 80, `mem_union_intro` 60 |
| by renamed identifier | `hw` 28, `hm` 28, `hg` 28, `h3` 28, `hmem` 28 |

Each of the previously-missing identifier surfaces is now covered 28× across the
projection families. Projection families only — **no broad random expansion**.

## Result (Part 6)

The `v31_raw_plus_projection_aug` model lifts the token-diversity holdout
**0.00 → 0.77** while keeping every standard held-out at **1.000** — a safe, purely
verified-data fix. It is beaten only by canonicalization (A, 0.92), which needs no new
data. Adopt A as primary; B is the low-risk alternative (raw model, no inference-time
machinery).

Honesty: every row Lean-verified by the trusted verifier; metadata records
`original_identifier`/`renamed_identifier`/`projection_kind`; no `state_after`; manual
candidates are verified targets, never model predictions.
