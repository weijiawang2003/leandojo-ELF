# V33 — Part 4: Dataset Report

_`scripts/build_v33_mathlib_dataset.py` → `data/processed/v33_mathlib_specialist/`._

Built on the **v32 canonical base** (942 rows = v31 canonical + 37 `∅∩` repair). The 83
residual-coverage rows are **canonicalized** (0 round-trip failures) and combined.

## Configs

| config | rows | role |
|---|---:|---|
| **`v33_general_residual`** | **1025** | v32 canonical base + 83 canonicalized residual rows — **recommended** (= the unweighted "general" config) |
| `v33_general_residual_stress` | 1040 | A + token-surface (subscript-identifier) rows upsampled 2× |
| `v33_residual_only` | 83 | residual rows only — **ablation** |
| val | 207 | v32 canonical val |

**No category-balanced config** (confirmed harmful since v29). Added by repair type:
vocabulary 33, density 35, token_surface 15.

## Leakage guards (asserted, passed)

No name/statement overlap train↔(11 residuals + v32 stress + v32/v33 fresh holdouts +
v25–v31 benchmarks); no `state_after`; **0 unresolved canonical identifiers** in any
training target (every residual tactic round-trips); not v19 placeholders; v24 untouched.
