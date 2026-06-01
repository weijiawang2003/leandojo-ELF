# V33 — Part 8: Final Single-Tactic Saturation Analysis

_`scripts/analyze_v33_single_tactic_saturation.py` →
`data/baselines/v33_saturation/report.json`. No Lean run._

## The single-tactic Mathlib tier is SATURATED

| benchmark | v31 canonical | v32 repaired | **v33 general_residual** |
|---|---:|---:|---:|
| v25 / v28 / v29 held-outs | 1.00 | 1.00 | **1.00** |
| token-diversity (13) | 0.92 | 1.00 | **1.00** |
| **adversarial identifier-stress (46)** | 1.00 (hardened) | 1.00 | **1.00** |
| **fresh robustness (42)** | 1.00 | 1.00 | **1.00** |
| routed broad-core p@5/p@10 | — | — | **0.9375 / 0.9583** |
| **routed tier-C pass@10** | — | 0.950 | **0.992 (244)** |

**Remaining residuals on the v33 eval benches: 0.** Adversarial stress v31→v33: 1.0→1.0
(the v33 parser-hardening lifted *every* canonical model's stress 0.891→1.00). The only
misses anywhere are ~2/244 in the broad routed set (fresh list/set shapes) — single-tactic.

## How it was closed (two clean, honest levers)

1. **Hardened canonical decode** — a parser fix so subscript/Greek identifiers
   (`proof₁`, `h₂`, `hα`) are recognized as binders. This *alone* closed the 5
   adversarial-identifier residuals for **every** canonical model (the v32 0.891 was a
   parser-coverage bug, not a model limit). Additive; all v31/v32 module tests still pass.
2. **Residual-coverage corpus** — 83 verified `inter_assoc`/`le_trans`-chain/
   `min·max·inf_comm`/`∅∩` siblings closed the fresh-shape gaps (order 0.89→1.00).

## Decision

- **Are any residuals multi-step? No** — `leandojo_next_state_relevant: false`, 0
  multi-step across every benchmark (the eval benches are all single-tactic and v33
  solves them).
- **Is the tier saturated? Yes** — adversarial stress 1.00, fresh 1.00, 0 eval-bench
  residuals, routed tier-C 0.992; broad-core preserved bit-for-bit.

> **v34 = PACKAGING / paper-style report / git recovery.** The single-tactic Mathlib
> tier (including adversarial identifiers and fresh shapes) is saturated; further
> single-tactic modeling has diminishing returns. **LeanDojo next-state stays deferred**
> — it is justified only by a genuinely multi-step benchmark, and none of the current
> failures is multi-step. The recommended next phase is **reporting + git recovery**
> (resolve the stale `.git/rebase-merge/`), not more modeling.
