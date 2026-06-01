# V33 — Part 6: Specialist Evaluation Report

_`scripts/evaluate_v33_mathlib_specialists.py` →
`data/baselines/v33_specialist_eval/`. 5 models × 6 benches; **5952 unique pairs**
verified (TrustedMathlibVerifier, 409 s). All canonical models use the v31 canonical-
aware pool **with the v33-hardened decode** (subscript/Greek identifiers now parse) +
raw v30 fallback._

## pass@10 — single-tactic tier is now saturated

| model | v25 | v28 | v29 | token-div | **stress (46)** | **fresh (42)** |
|---|---:|---:|---:|---:|---:|---:|
| v31_canonical_general (hardened decode) | 1.00 | 1.00 | 1.00 | 0.92 | **1.00** | **1.00** |
| v32_canonical_repaired (hardened decode) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| **v33_general_residual** | **1.00** | **1.00** | **1.00** | **1.00** | **1.00** | **1.00** |
| v33_general_residual_stress | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| v33_residual_only (ablation) | 1.00 | 0.90 | 0.80 | 0.54 | 0.80 | 0.55 |

**`v33_general_residual` = 1.00 on every bench, 0 no-verified** (stress 46/46,
fresh 42/42, token-diversity 13/13). The residual-only ablation stays weak — confirming
the residual rows must augment, not replace, the base.

## What closed the residuals (two clean levers)

1. **Hardened canonical decode** (a parser fix: subscript/Greek identifiers now parse).
   This *alone* lifted adversarial-stress for **every canonical model** — `v31_canonical_general`
   re-evaluated with the hardened decode jumps **0.891 → 1.00** on the 46 adversarial
   theorems (it was always able to bind `proof₁` once canonicalization recognized it;
   the v32 0.891 was a parser-coverage bug, not a model limit). The v19 guard still drops
   the residual ~2.8 % unresolvable canonical candidates safely (raw fallback covers).
2. **Residual-coverage corpus** (83 verified `inter_assoc`/`le_trans`-chain/`min·max·inf_comm`/
   `∅∩` siblings) — closed the fresh-shape gaps (token-diversity 0.92→1.00 already at
   v32; fresh-robustness 1.00).

## Headline

The combination drives **all six single-tactic benches to 1.00, 0 residuals** — the
single-tactic Mathlib tier (including adversarial identifiers and fresh shapes) is
**saturated**. Real `import Mathlib`; TrustedMathlibVerifier only; not v19 placeholders;
no `state_after`; no manual oracle; v24 untouched.
