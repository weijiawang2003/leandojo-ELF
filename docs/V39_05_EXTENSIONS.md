# V39 Phase 5 — Exploratory extensions

All reuse the trained Track-A headline snapshots (no new training except where noted).

## E1 — Sampling-compute frontier (H4)  → **SUPPORTED (with a twist)**
Headline FLOW: ODE steps ∈ {1,2,4,8,16,32} × CFG ∈ {1,1.5,2}; dev exact-seq.

| steps (NFE) | best-cfg dev exact-seq |
|------|------|
| 1  | **0.278** |
| 2  | 0.230 |
| 4  | 0.163 |
| 8  | 0.113 |
| 16 | 0.104 |
| 32 | 0.095 |

**Quality DECREASES with more ODE steps.** 8-step retention vs 32-step = **1.19** (8 steps is
*better* than 32) ⇒ H4 ("≥90% of 32-step quality at ≤8 steps") is **SUPPORTED**, but the real
finding is the opposite of the usual diffusion story: **flow is best at 1 step.** The single
x-prediction from noise lands closest to a decodable embedding; Euler-integrating the ODE drifts
*away* from decodable points (accumulated error in a space where only lattice points decode).
CFG helps monotonically (cfg=2 > 1) at every step count.
AR reference: mean NFE ≈ 10 (one forward/token), dev exact 0.79.
**Consequence:** the Phase-4 flow eval used 16 steps and therefore *undersold* flow — re-verified
at steps {1,2,4,8}; see V39_FINAL for flow's honest-best verified pass@k. Plot: `ext_nfe.png`.

## E2 — AR-drafts + flow-repair hybrid (H5, flagship)  → **REFUTED**
AR drafts K=16/theorem; AR solves **21/24**, fails 3 (`v26w_inter_subset_left_union`,
`v28_ord_min_le_right_0`, `v29_fs_subset_inter_0`). For each failed draft, embed → partial noise
at t0 ∈ {0.3,0.5} → denoise with the trained flow (conditioned on the same theorem) → decode →
verify. Flow produced 28 unique repaired candidates; **0 verified**.
**H5 = REFUTED: embedding-space flow-repair rescued 0/3 (0%) of AR failures.** Seeding the flow
near a near-correct draft does not buy coherence — the denoiser still emits salad. Clean negative
for the hybrid-repair idea at this scale. (`ext_repair.json`)

## E3 — Block-size ablation  → **NOT RUN (out of scope)**
Block/semi-AR decoding (BD3-LM) is scaffolded in the family docstrings but **not implemented** in
`FlowModel.generate` (consistent with v38's own "D2 block … scaffolded, skipped:scope"). Running it
would require implementing block decoding; deferred rather than faked. The continuous-vs-discrete
interpolation question is partly answered by MDLM (block=full diffusion) ≫ flow already.

## H3 — Distinct-verified diversity  → **REFUTED**
AR temperature ladder {0.7,1.0,1.3} vs FLOW CFG {1,1.5,2}, K=32 each, distinct-*verified*/theorem:
| | distinct-verified / theorem |
|--|--|
| AR   | **2.92** |
| FLOW | 0.625 |
**H3 = REFUTED.** Flow emits many more *distinct* candidates (distinct ≈ 26–32 vs AR ≈ 4–11) but
far fewer distinct *verified* ones. Diversity without validity: flow's variety is incoherent.

## E4 — Throughput (tactics/s, batch 256, bf16, RTX 4080)
| sampler | tactics/s |
|--|--|
| AR (full decode) | **420** |
| flow @ 8 steps (cfg=2) | 177 |
| flow @ 16 steps (cfg=2) | 88 |
flow@16 is ~5× slower than AR; flow@8 ~2.4× slower. The CFG pass doubles flow's cost, and AR's
tactics are short (~10 tokens) so AR's per-tactic cost is already low. **Only at 1 step** (flow's
*best* quality per E1) would flow approach/exceed AR throughput (~1.0–1.4k/s extrapolated) — the
sole regime where ELF's few-step promise materializes here, and exactly where flow is most accurate.

## Net
Of the exploratory hypotheses: **H4 supported** (flow is a 1-step model, not a many-step one),
**H5 and H3 refuted** (repair and verified-diversity both fail), E3 out of scope. The consistent
thread: continuous embedding-space flow lacks an inter-token coherence mechanism, and neither more
steps, draft-seeding, nor diversity recovers it.
