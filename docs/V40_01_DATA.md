# V40 Phase 1 — Whole-proof corpus + two real-Mathlib tiers

All from LeanDojo Benchmark 4 random split (theorem-disjoint train/val/test). Generation object is now
a **whole proof** (`statement → example-binders+goal → newline-joined tactic block`), not a mid-proof
single tactic.

## Whole-proof training corpus (`data/v40/corpora/wholeproof/`)
From the **train** split; dev from **val**. `state_to_example(first state_before)` → statement;
`whole_proof` = newline-join of traced tactics (linear only). Length-filtered (cond ≤256, proof ≤46
content tokens), deduped by (statement, proof), train-only freq-capped vocab (min_count 2).
| field | value |
|-------|-------|
| n_train | **45,820** |
| n_dev (val, full-set eval) | **614** (no sampling shortcut) |
| vocab | 23,987 (OOV train 0.39% / dev 0.85%) |
| mean tactics / proof | **1.66** |
| **multi-tactic fraction (≥2)** | **44.6%** |
| max_cond_len / max_tgt_len | 256 / 48 |
| train drops | proof_long 26,808 · cond_long 1,917 · unconvertible 1,672 · contam 1 |
| U-ladder | {8k, 32k, 45,820} |

44.6% of training proofs are genuinely multi-tactic — so the object change is real, and H6 is
meaningfully testable. (Dev is 614 not the briefed 1,500 — the val split yields only 614 convertible
in-length pairs; full-set evaluated, disclosed.)

## Two disjoint real-Mathlib verified tiers (`data/v40/tiers/`)
From the **test** split (never trained). Harvested by compiling each reconstructed gold whole-proof;
kept only those that compile; stratified by proof length; 50/50 split.
| | value |
|--|--|
| convertible test theorems verified | 652 |
| **gold-compile-rate** | **13.7% (89)** |
| compiled by length | 1-tac 64 · 2-3 tac 24 · 4+ tac 1 |
| **tier-dev** | **45** (1-tac 32, 2-3 tac 12, 4+ 1) — sweeps allowed |
| **tier-final** | **44** (1-tac 32, 2-3 tac 12) — touched **once**, Phase 7 |

The verified tiers skew single-tactic (72%) because multi-tactic golds rarely compile under version
skew; ~27% are genuine 2-3-tactic whole-proofs. n=44–45 per tier ≫ v39's n=24.

## Decontamination
Every training row dropped if its `full_name` OR statement matches any of the **113** decontam keys
(tier-dev 45 + tier-final 44 + v39 24-tier). Only 1 train row hit (test split is disjoint Mathlib).

## Fingerprints (`fingerprints.json`, `tiers/manifest.json`)
corpus train sha256 in `data/v40/corpora/wholeproof/fingerprints.json`; tier gold-compile-rate +
bucket counts in `data/v40/tiers/manifest.json`. Corpus jsonl/vocab gitignored (large); manifests +
fingerprints + the two small tier jsonls committed.
