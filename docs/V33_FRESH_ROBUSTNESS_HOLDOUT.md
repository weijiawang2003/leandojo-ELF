# V33 — Part 3: Fresh Robustness Holdout

_`scripts/generate_v33_fresh_robustness_holdout.py` →
`data/{seeds/v33_fresh_robustness_holdout_seeds,manual/v33_fresh_robustness_holdout_candidates}.jsonl`.
EVAL ONLY — never trained. `TrustedMathlibVerifier` only._

## Counts

| metric | value |
|---|---:|
| theorems proposed | 44 |
| **solvable, novel (kept)** | **42** (within the 30–60 target) |
| verified gold candidates | 73 |
| zero-success | 0 |
| dropped: leaked | 2 |

By category: set 16, order 9, nat 6, finset 4, logic 4, list 2, function 1.

## Design

Stresses **both** axes at once: adversarial identifiers (`h_left`, `h_right`, `h₁`,
`h_mem`, `A B C`/`U V W`, Greek `φ ψ χ`) **and** single-tactic shape coverage
(projection, subset, `le_trans`/`le_refl`/`antisymm`, comp, `add_comm`/`add_zero`,
`append_nil`, `or_symm`/`and_symm` with `cases`). Statement-level leakage-guarded against
all training (v30/v31 base + v33 residual coverage); the gold proof only confirms
provability and is never fed to a model. No `state_after`.
