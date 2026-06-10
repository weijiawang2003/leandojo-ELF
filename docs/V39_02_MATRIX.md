# V39 Phase 2 — Three-way matrix at scale (Track A, 30M, matched budget)

The first compute-matched three-way comparison of continuous embedded **flow** (x-pred,
self-cond, CFG-trained), masked-discrete diffusion (**MDLM**), and **AR** on the same
verified single-tactic Mathlib split, shared `V38Trunk` (param-matched: 25.8M AR/MDLM,
26.6M flow), shared tied-embedding readout. Every cell = identical token budget ⇒
identical optimizer-step count (grid 916 steps @ 3e7 tokens; headline 3052 @ 1e8). bf16,
cosine LR, 2% warmup, seed 3407. Dev = the v35 val split (theorem-disjoint, 0 tier overlap).

## Throughput (measured, this run)
AR ~185k tok/s, MDLM ~188k tok/s, FLOW ~131k tok/s (flow's extra self-cond forward).
Grid cell ≈ 146–217 s; headline cell 432–581 s. All 15 cells completed (none hit the cap).

## Grid (matched 3e7 tokens) — final-checkpoint dev metrics
| family | U | epochs | val_loss | **exact-seq** | per-token | distinct |
|--------|---|--------|----------|-----------|-----------|----------|
| AR   | 461  | 458 | 1.747 | 0.574 | 0.519 | 7.0 |
| AR   | 922  | 229 | 0.991 | 0.744 | 0.545 | 3.25 |
| AR   | 1844 | 115 | 0.527 | 0.789 | 0.551 | 4.0 |
| AR   | 3689 | 61  | 0.223 | **0.873** | 0.580 | 4.9 |
| MDLM | 461  | 458 | 1.429 | 0.520 | 0.534 | 3.5 |
| MDLM | 922  | 229 | 0.664 | 0.637 | 0.557 | 4.0 |
| MDLM | 1844 | 115 | 0.291 | 0.561 | 0.534 | 6.1 |
| MDLM | 3689 | 61  | 0.181 | 0.570 | 0.551 | 11.1 |
| FLOW | 461  | 458 | 0.297 | 0.006 | 0.462 | 30.8 |
| FLOW | 922  | 229 | 0.263 | 0.055 | 0.451 | 30.5 |
| FLOW | 1844 | 115 | 0.853 | 0.020 | 0.421 | 32.0 |
| FLOW | 3689 | 61  | 1.399 | 0.041 | 0.442 | 32.0 |

## Headline (matched 1e8 tokens, U=3689, ~212 epochs) — the verified-eval snapshots
| family | val_loss | **exact-seq** | per-token | distinct | params |
|--------|----------|-----------|-----------|----------|--------|
| AR   | 0.283 | **0.885** | 0.582 | 4.25 | 25.8M |
| MDLM | 0.176 | 0.730 | 0.579 | 3.5 | 25.8M |
| FLOW | 0.082 | 0.109 | 0.542 | 26.25 | 26.6M |

## Reading
1. **AR scales cleanly** with data (0.574→0.873 grid; 0.885 headline) — the baseline to beat.
2. **MDLM is a genuine competitor** to AR (0.73 headline vs 0.885), well above flow. Discrete
   diffusion over the *same* vocab/trunk produces coherent tactics; the gap to AR is modest.
3. **Continuous flow collapses on coherence.** Per-token gold recovery is healthy (0.44–0.54
   — the trunk learns local token structure) but exact-seq is ~0.01–0.11: it almost never
   gets the *whole* tactic right. Flow's **distinct ≈ 26–32** (vs AR ≈ 4–11): it emits many
   *different* sequences, almost all incoherent — "token salad" at 30M, exactly the v36
   diagnosis, now quantified against matched baselines.
4. **Flow-MSE is decoupled from decodability.** Flow has the *lowest* val_loss (its x-pred MSE,
   0.08–0.30) yet the *worst* exact-seq — low reconstruction error in embedding space does not
   imply a decodable token sequence. (AR/MDLM val_loss is CE, not comparable in absolute terms;
   the point is the within-flow MSE↓ / exact-seq≈0 decoupling.)
5. **More budget helps flow a little** (grid 0.041 → headline 0.109 at U=3689) but it stays ~8×
   behind AR — a quantitative, not categorical, improvement.

Plots: `outputs/v39/trackA/crossover_trackA.png`, `curves_trackA.png`.
The failure is specific to *continuous embedding-space* flow — MDLM (discrete diffusion) does
not exhibit it. See V39_03 for the crossover reading and H2 verdict.
