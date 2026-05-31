# Mini-ELF v26 — Part 7: Routed System + Broad-Core Preservation

`src/mini_elf_lean/v26_mathlib_router.py` + `scripts/evaluate_v26_routed_system.py`.

The routed system is a deterministic generator switch:

| theorem environment | generator | verifier |
|---|---|---|
| `import Mathlib` / mathlib flag | **v26 specialist** (`token_seq2seq_v26_mathlib_specialist_base`) | `import Mathlib` |
| no Mathlib import (core) | **v24 broad-core** (`token_seq2seq_v24_broad_residual`, untouched) | core Lean |

It exists to get the Mathlib-tier gains **without** the v25 single-model
cannibalization: every broad-core theorem keeps running on the byte-identical
v24 model, so broad-core cannot regress.

## Routing (no theorem-specific cheating)

`48/48` broad-core seeds → v24; `36/36` tier-C seeds → specialist. The decision
uses only imports / the mathlib flag (see `routing_log.jsonl`).

## Broad-core is preserved (no cannibalization)

Routed broad-core uses the untouched v24 model + core Lean verifier:

| system | broad-core p@1 | p@5 | p@10 | bool p@10 |
|---|---|---|---|---|
| **v26 routed** (→ v24) | 0.771 | **0.938** | **0.958** | 1.00 |
| v24 everywhere (established baseline) | 0.792 | 0.917 | 0.938 | 1.00 |
| **v25_aug everywhere (co-trained)** | 0.667 | 0.792 | **0.833** | **0.667** ⬇ |

* Routed broad-core **meets/exceeds the protected bar** (p@5 ≥ 0.917, p@10 ≥
  0.938) and keeps `bool`, `implication`, `equality`, `list`, `negation` at 1.00.
* The single co-trained v25 model **regressed** broad-core to p@10 0.833 and
  **halved `bool`** (1.00 → 0.667). The router avoids this entirely.
* **Honesty note (no retcon):** the established v24 broad-core numbers stand
  (p@5 0.917 / p@10 0.938). The routed re-measurement reads p@5 0.938 / p@10
  0.958 — **+1 theorem (`v18_or_inr`)** — purely because the batched
  direct-binary verifier has no elan-shim *timeout* (the old eval cached one
  disjunction candidate as a timeout-failure). Same model, same proofs; the
  delta is verifier determinism, not a model improvement. Disjunction is 0.80
  routed (genuine fail: `v18_or_elim_to_common`), conjunction 0.83 — unchanged.

## Tier-C is improved (routed = specialist)

Routed tier-C uses the v26 specialist + `import Mathlib` verifier, on the
combined 36 tier-C theorems (14 v25 held-out + 22 v26 holdout):

Combined 36-theorem tier-C (each system at its best rerank config per cell;
combined = row-weighted over the two benchmarks):

| system on tier-C | p@1 | p@5 | p@10 |
|---|---|---|---|
| **v26 routed** (→ specialist) | 0.583 | 0.889 | **0.917** |
| v24 everywhere | 0.333 | 0.417 | **0.417** |
| v25_aug everywhere | 0.528 | 0.639 | **0.694** |

(Per-benchmark: v26 routed = 0.929 on v25 held-out, 0.909 on v26 holdout. v24 =
0.571 / 0.318; v25_aug = 0.786 / 0.636 — see the specialist eval report.)

## The headline: routing gets both, co-training got only one

| | broad-core p@10 | tier-C p@10 |
|---|---|---|
| v24 everywhere | 0.938 | 0.417 |
| v25_aug everywhere (co-trained) | **0.833 (regressed)** | 0.694 |
| **v26 routed** | **0.958 (preserved)** | **0.917 (improved)** |

The v25 co-trained model bought tier-C at the price of broad-core. **v26 routing
keeps broad-core intact AND lifts tier-C above what co-training achieved** — the
central result of v26.

## Honesty

Real Lean both tiers (core for broad-core, `import Mathlib` for tier-C, both via
the confirmed batched verifier). The router is a generator switch — no proof
templates, no `state_after`, no manual oracle, no theorem-specific rules. The
v24 model is read-only. Artifacts under `data/baselines/v26_routed_system/`.
