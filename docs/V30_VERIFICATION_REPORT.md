# V30 — Part 4: Verification & Gold-Sampling Report

_`scripts/verify_v30_targeted_density_corpus.py` →
`data/baselines/v30_corpus_integrity/report.json`._

## Re-verification (trusted)

| metric | value |
|---|---:|
| verified rows | **155** |
| **re-verify pass** | **155 / 155** |
| verified→regressed | **0** |
| failed→now-pass | 0 |
| coverage gaps | **0** |

## Gold sampling (one declaration per file)

| metric | value |
|---|---:|
| gold sample size | **24** (≥ 20 required) |
| families covered | **11** (one per targeted family) |
| trusted-vs-gold mismatches | **0** |
| trusted false positives | **0** |
| `integrity_ok` | **True** |

**Zero mismatches / zero false positives** — the project-long 0-mismatch invariant now
holds **v27 → v28 → v29 → v30**. The v30 repair siblings are genuine Lean theorems.

## Honesty

`TrustedMathlibVerifier` only (`confirm=False` raises); naive verifier never used for
any reported number; real `import Mathlib`; no `state_after`; manual targets never
predictions.
