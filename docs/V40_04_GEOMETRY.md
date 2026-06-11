# V40 Phase 4 — Embedding geometry (H9)

Does the embedding **geometry** explain flow's 1-step coherence failure? Test: train a flow with
**unit-norm frozen embeddings** (rows on the unit sphere → the tied nearest-embedding readout becomes a
pure cosine, ‖E‖² constant → maximal, magnitude-invariant separation → in principle the cleanest 1-step
snap) vs the Phase-2 **scratch** flow (default N(0,0.02) frozen init), **same** corpus/budget/seed.

(Fallback (b) per the brief: a frozen *pretrained* embedding table was not downloaded — the unit-norm
ablation tests the geometry mechanism directly without pretrained-tokenizer integration risk, and is a
cleaner probe of the "lattice points too close to snap" hypothesis.)

## Result — **REFUTED**
| geometry | dev exact-seq | dev per-token |
|----------|-----------|-----------|
| scratch (N(0,0.02), frozen) | 0.0008 | 0.323 |
| **unit-norm (frozen)** | **0.0008** | 0.329 |
| ratio | **1.00** | 1.02 |

*Criterion:* unit-norm/scratch ≥ 1.5×. *Result:* **ratio 1.00 → REFUTED.** Max-separation geometry makes
**no difference** — neither exact-seq nor per-token moves. So flow's coherence failure is **not** a
lattice-spacing / snap-ambiguity problem: even with embeddings maximally and uniformly separated on the
sphere, the single-shot bidirectional x-prediction still cannot assemble a jointly-valid sequence. This
**rules geometry out** as the explanation and points the finger squarely at the **absence of inter-token
coupling at decode time** — consistent with H7 (block conditioning is the only thing that helped) and H9
(geometry didn't). Artifact: `outputs/v40/geometry/h9_geometry.json`.
