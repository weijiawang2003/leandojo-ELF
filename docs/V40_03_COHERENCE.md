# V40 Phase 3 — Decode-time coherence mechanisms (H7 block, H8 snap-repair)

Decode-time only; reuses the Phase-2 whole-proof flow checkpoint (zero retraining). Dev exact-seq on
the full 614-row dev set, K=4. Baseline **FLOW@1 dev exact-seq = 0.0008** (per-token 0.323).

## H7 — block / semi-AR decode — **SUPPORTED (by criterion; small absolute)**
Generate the target in `n_blocks`; block *b* predicted from cond + already-snapped (clean) prefix
blocks, future blocks masked (key-padding). NFE = n_blocks × steps-per-block.
| config | NFE | dev exact-seq | per-token |
|--------|-----|-----------|-----------|
| FLOW@1 (baseline) | 1 | 0.0008 | 0.323 |
| block nb4 spb1 | 4 | 0.0016 | 0.324 |
| block nb4 spb2 | 8 | 0.0012 | 0.268 |
| **block nb8 spb1** | **8** | **0.0033** | 0.314 |
| block nb8 spb2 | 16 | 0.0033 | 0.265 |

*Criterion:* best (NFE≤8) ≥ 1.5× FLOW@1. *Result:* `block_nb8_spb1` = **0.0033 = 4.0× the 0.0008
baseline** → **SUPPORTED, but Fisher-fragile:** in raw counts this is **8 vs 2** exact hits out of 2,456
samples (Fisher exact p≈0.054 — marginally non-significant). Treat the 4× as suggestive, not
established. Mechanistically meaningful nonetheless: block decoding lifts **joint** coherence
(exact-seq 4×) while **per-token is unchanged** (0.31 ≈ 0.32) — i.e. conditioning each block on the
snapped prefix supplies exactly the inter-token coupling the bidirectional one-shot head lacks (the
BD3-LM thesis, confirmed in miniature).

**Caveat (load-bearing):** the absolute level (0.0033) is still **~10× below AR's 0.0346**. Block decode
moves flow from "basically never coherent" to "almost never coherent" — a real mechanism, not a
competitive model. H7 passing its pre-registered criterion is what keeps the **global exit rule
untriggered** (not all of H6–H9 fail); the constructive reading is that *if* continuous flow is ever
pursued, semi-AR block decoding is the one lever shown here to move coherence at all.

## H8 — snap-repair — **REFUTED**
1-step predict → snap → re-embed → re-noise to t ∈ {0.2,0.4} → 1-step re-predict, R ∈ {1,2,3} rounds.
| R | t | NFE | dev exact-seq |
|---|---|-----|-----------|
| 1–3 | 0.2/0.4 | 2–4 | **0.0000** (all six cells) |

*Criterion:* best > 1.10× FLOW@1. *Result:* every cell collapses to **0.0000** → **REFUTED.** Re-noising a
snapped (already-lattice) prediction and re-predicting does not recover coherence — it discards the
small structure the first 1-step pass had. Snap-repair is a clean negative for embedding-space iterative
refinement, complementing v39B's failed AR-draft flow-repair.

## Net
The only coherence lever that helps is **block/semi-AR conditioning** (H7), and only by ~4× off a
near-zero floor. Iterative snap-repair (H8) hurts. Per-theorem coherence remains the wall.
Artifact: `outputs/v40/coherence.json`.
