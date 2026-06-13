# V44 — Discrete proving system on a hard tier (pre-registered plan)

**Branch:** `v44-discrete-retrieval` off `v43-lpsf-scale` · generate on `.venv-gpu` only · 2026-06-12

## Spine (can't-fail core)
The **gold-premise oracle decomposition**: generate conditioned on (a) no premises, (b) retrieved
premises, (c) gold premises (names from gold proof, never the gold tactic). The **(gold−none) gap =
retrieval-addressable fraction of the wall** — computable from gold proofs, so it holds even if the
trained retriever underwhelms. Everything else (dense retriever, scaling, ensemble) is upside.

## Pre-registered hypotheses
**Spine:** S1 non-simp-closable hard tier n≥100, bisect-compiling gold + closability audit. S2
oracle decomposition AR&MDLM under {none,retrieved,gold}; gold−none = headline. (S2 needs
premise-conditioned generators — cheap training run; gold arm is retriever-independent.)
Falsifier S2: gold≈none ⇒ generation not retrieval is the bound (revisit V43 on hard theorems).
**Retriever (upside):** R1 dense dual-encoder recall@k > BM25. R2 retrieval-aug AR/MDLM − none ≥
margin, closes fraction of S2 gap.
**Scaling/ensemble (upside):** E1 AR∪MDLM∪simp > each alone over simp. E2 data/model scaling lifts
hard pass@k. E3 MDLM closes on AR with scale.
**Breadth (droppable):** D1 retrieval×ensemble; D2 multi-step; D3 retriever ablations.

## Controls
Hard tier = non-simp-closable (15-tactic sweep fails) + bisect-compiling gold, n≥100, report
closability rate. simp+no-retrieval columns in every table. Generate `.venv-gpu`. verify_many_bisect
only, verify_mode+SHA, persist candidates+retrievals+vmaps. ≥3 seeds. Touch hard-test once. Oracle:
premise names only, never gold tactic. No continuous flow.

## Sequencing (spine-first)
P0 S1 hard tier (CPU, can't fail) → P1 S2 oracle decomp (light, HEADLINE) → P2 R1 dense retriever
(GPU long pole, start early) → P3 R2/E1 e2e+ensemble → P4 E2/E3 scaling → P5 D1-D3 breadth.

## Close-out tree
S2 gap large + R2 realizes part → success, V45 = scale retriever + search. S2 gap large + R2≈none →
retrieval-addressable but unreached; V45 = better retriever. S2 gap small → generation-bound, pivot.
E1 union over simp ≈0 → discrete ensemble doesn't beat trivial sweep on hard theorems (state plainly).

## Theory anchors
Premise selection beyond ReProver (LeanSearch v2, graph-aug +25%, REAL-Prover); retrieval-vs-reasoning
ablation; d-LLM scaling (diffusion param-heavy/less-data-heavy); 3D-Prover diversity→pass@k; v40 H10
AR∪MDLM 27/44. Non-simp-closable tier necessary (V43: 42/45 trivially closable).
