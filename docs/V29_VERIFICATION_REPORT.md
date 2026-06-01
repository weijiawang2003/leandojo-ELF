# V29 — Part 4: Verification & Gold-Sampling Report

_`scripts/verify_v29_mathlib_density_corpus.py` →
`data/baselines/v29_corpus_integrity/report.json`. Independent integrity gate over the
Part-3 corpus, re-run with `TrustedMathlibVerifier`; gold spot-check with
`GoldMathlibVerifier` (one declaration per file)._

## Re-verification (trusted, sound & complete)

| metric | value |
|---|---:|
| candidates proposed | 589 |
| **verified rows** | **492** |
| failed rows | 0 |
| timeouts | 0 |
| **verified rows that still pass on re-verify** | **492 / 492** |
| verified→regressed | **0** |
| failed→now-pass | 0 |
| **zero-success theorems (coverage gaps)** | **0** |
| re-verify Lean wall | 82.1 s (generation 80.3 s) |

Verified by category: **set 143, finset 114, order 72, function 61, nat 44,
logic 40, list 18** across **38 families**. No common API failures (the failed set is
empty — every proposed candidate style was a real Mathlib proof).

## Gold sampling (ground-truth, one declaration per file)

| metric | value |
|---|---:|
| gold sample size | **32** (≥ 30 required) |
| categories covered | **7 / 7** (set 7, nat 6, order 6, finset 5, logic 5, function 2, list 1) |
| trusted-vs-gold mismatches | **0** |
| trusted false positives | **0** |
| `integrity_ok` | **True** |

The gold verifier elaborates each sampled candidate in complete isolation
(`batch_size=1`), so no cross-candidate parser interaction is possible. **Zero
mismatches and zero false positives** confirm the batched trusted verifier remains
sound on the v29 corpus — the v29 training positives are genuine Lean theorems. This
maintains the project-long invariant of **0 trusted-verifier gold mismatches** across
v27 → v28 → v29.

## Honesty

`TrustedMathlibVerifier` only (`confirm=False` raises `UnsafeVerifierError`); the
naive batched verifier is never used for any reported number; real `import Mathlib`
typecheck; no `state_after`; manual targets are corpus references, never model
predictions.
