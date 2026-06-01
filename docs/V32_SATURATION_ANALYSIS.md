# V32 — Part 7: Saturation / Next-State Analysis

_`scripts/analyze_v32_saturation.py` → `data/baselines/v32_saturation/report.json`.
No Lean run._

## Robustness measured

| benchmark | v30 (raw) | v31 canonical | v32 repaired |
|---|---:|---:|---:|
| adversarial identifier-stress (46) | 0.261 | 0.891 | **0.891** |
| fresh-shape micro-holdout (25) | 0.760 | 0.760 | **0.800** |
| routed broad-core p@5/p@10 | — | 0.9375/0.9583 | **0.9375/0.9583** |
| routed tier-C pass@10 (202) | — | — | **0.950** |

## Remaining failures (best v32 model, across stress + fresh + tier-C)

**11 residuals**, by class: **api_vocabulary 9, token_or_shape 1,
sparse_shape_single_tactic 1; multi_step 0.** By category: set 5, order 4, finset 2.
By bench: identifier-stress 5, fresh-shape 5, tier-C 1.

Every residual is **single-tactic**: the adversarial-identifier misses are the hardest
Greek/subscript forms (`proof₁`, `hα`) where the canonical decode occasionally desyncs
*and* the raw fallback can't bind; the fresh misses are unseen **shapes**
(`min_comm`/`inf_comm`, `inter_assoc`, `le_of_lt`). **0 multi-step.**

## Decisions

- **Is single-tactic coverage saturated? Not quite.** Canonicalization made the tier
  **robust** (token coverage solved in general: 0.26 → 0.89 on never-seen identifiers),
  and broad-core/standard held-outs are all at the bar/1.000 — but the adversarial
  stress (0.89 < 0.95) and fresh-shape holdout (0.80 < 0.85) show **residual
  single-tactic headroom** on the two hardest axes (extreme identifier forms; unseen
  shapes).
- **Is LeanDojo next-state relevant? No** (`leandojo_next_state_relevant: false`).
  **0 of 11** residuals are multi-step / proof-state — they all have a single verifying
  tactic the model simply didn't reach. Starting LeanDojo now would be premature, and
  the v32 constraint forbids it unless the residual is proven multi-step (it is not).

## v33 recommendation

**Continue single-tactic coverage / robustness — defer both LeanDojo and final
packaging by one more pass.** Concretely:
1. **Harden the canonical decode** for extreme identifiers (Greek/subscript) so the
   2.8–8.5 % unresolved rate on adversarial input drops further (e.g. normalize element
   tokens too, or widen the canonical alphabet) — this lifts adversarial-stress toward
   the 0.95 bar.
2. **Add fresh-shape density** for the order/set shapes the fresh holdout exposed
   (`min/max/inf_comm`, `inter_assoc`, `le_of_lt`) — this lifts fresh-holdout toward
   0.85.
3. **Then package** (paper-style report / git recovery) once stress ≥ 0.95 and fresh
   ≥ 0.85. **LeanDojo next-state stays deferred** until a genuinely multi-step Mathlib
   benchmark exists (none of the current residuals is multi-step).
