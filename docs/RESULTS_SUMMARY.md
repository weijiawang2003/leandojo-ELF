# Results Summary

Concise tables only. Full narrative: [`PROJECT_REPORT.md`](PROJECT_REPORT.md).
All numbers come from generated `metrics.json` / `summary.json` /
`training_config.json` files; if prose ever disagrees, trust those files.

> Scope: **theorem-level** lean-cli verification only. `state_after_is_real=false`
> for the whole corpus — this is tactic prediction, **not** next-state modeling.

## Corpus counts

| Quantity | Value |
| --- | --- |
| Theorems | 134 |
| Pattern families | 21 (≥5 variants each) |
| Candidate attempts | 616 |
| Verified (lean-cli) | 329 |
| Failed | 287 (0 timeouts) |
| Dataset rows (verified) | 329 |
| Unique tactics | 60 |
| Theorem split (train/val/test) | 102 / 16 / 16 |
| Row split (train/val/test) | 254 / 37 / 38 |

## Baseline metrics (lean-cli pass@k)

| baseline | split | n_rows | top1_exact | top5_any_verified | pass@1 | pass@3 | pass@5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| majority | val | 37 | 0.03 | 0.16 | 0.08 | 0.16 | 0.16 |
| retrieval | val | 37 | 0.08 | 0.22 | 0.22 | 0.22 | 0.22 |
| log-linear | val | 37 | 0.19 | 0.65 | 0.46 | 0.59 | 0.65 |
| AR seq2seq | val | 37 | **0.30** | 0.78 | **0.70** | 0.70 | 0.78 |
| Mini-ELF v0 (decoder) | val | 37 | 0.22 | 0.84 | 0.51 | 0.84 | **0.84** |
| Mini-ELF v0 (nn) | val | 37 | 0.27 | 0.89 | 0.65 | 0.89 | 0.89 |
| majority | test | 38 | 0.05 | 0.16 | 0.16 | 0.16 | 0.16 |
| retrieval | test | 38 | 0.05 | 0.32 | 0.16 | 0.16 | 0.32 |
| log-linear | test | 38 | 0.21 | 0.76 | 0.55 | 0.71 | 0.76 |
| AR seq2seq | test | 38 | **0.32** | 0.82 | **0.76** | 0.82 | 0.82 |
| Mini-ELF v0 (decoder) | test | 38 | 0.24 | 0.90 | 0.61 | 0.82 | **0.90** |
| Mini-ELF v0 (nn) | test | 38 | 0.32 | 1.00 | 0.76 | 0.92 | **1.00** |

- **log-linear**: pure-Python softmax char-n-gram classifier; 55 classes, 254
  train rows, 80 epochs, lr 1.0, seed 0, ~28 s, train top-1 0.40.
- **AR seq2seq**: char-level bi-GRU + additive attention + GRU decoder (PyTorch
  `2.12.0+cpu`); 410,309 params, 60 epochs, lr 0.003, seed 0, ~110 s, beam 5.
- **Mini-ELF v0**: tactic-AE latent (dim 48) + conditional rectified-flow MLP;
  342,965 params (ae 120,597 / cond 172,912 / flow 49,456), AE val recon 0.89,
  flow best epoch 60, 60+300 epochs, ~104 s, seed 0, 32 noise samples, 10 Euler
  steps; ranks dedup'd candidates by sample frequency. `decoder` = AE decode
  (generative); `nn` = snap to nearest train tactic (retrieval ablation).
- All trained models `uses_state_after=false`. (16 eval theorems/split →
  diagnostic, not statistically powered.)

**Two complementary winners (v0).** AR has the best **precision** (`pass@1`);
Mini-ELF v0 has the best **recall** (`pass@5`, beating AR on both splits) thanks
to ~20 distinct stochastic candidates/row. The nn-decode ablation tops `pass@k`
(test `pass@5` 1.00) but is latent-space retrieval, **not** open-vocabulary
generation. **Mini-ELF v1 (below) closes the precision gap** — a learned
verifier-aware reranker lifts the *generative* decoder to `pass@1` 0.89 on both
splits while keeping `pass@5` ≥ 0.95.

## Mini-ELF v1 (lean-cli pass@k)

v1 keeps the v0 latent + flow generator and adds four modules: a **structure-aware
condition encoder**, a **denoising** tactic-AE, a **verifier-aware reranker**
(trained on previous Lean outcomes — verified=positive, failed=negative — plus
*self-training* hard negatives: v1's own flow candidates on train theorems,
Lean-labelled), and a symbolic **witness-copy** augmenter for `∃` goals. All
numbers from generated `metrics.json`.

| model | split | pass@1 | pass@3 | pass@5 | invalid@1 | novel_verified |
| --- | --- | --- | --- | --- | --- | --- |
| AR seq2seq | val | 0.70 | 0.70 | 0.78 | — | 0 |
| AR seq2seq | test | 0.76 | 0.82 | 0.82 | — | 2 |
| Mini-ELF v0 (decoder) | val | 0.51 | 0.84 | 0.84 | 0.70 | 0 |
| Mini-ELF v0 (decoder) | test | 0.61 | 0.82 | 0.89 | 0.67 | 0 |
| Mini-ELF v0 (nn) | val | 0.65 | 0.89 | 0.89 | 0.54 | 0 |
| Mini-ELF v0 (nn) | test | 0.76 | 0.92 | 1.00 | 0.56 | 0 |
| Mini-ELF v1 (decoder, no rerank) | val | 0.38 | 0.78 | 0.89 | 0.62 | 2 |
| Mini-ELF v1 (decoder, no rerank) | test | 0.66 | 0.89 | 0.89 | 0.34 | 2 |
| **Mini-ELF v1 (rerank)** | val | **0.89** | 0.89 | 0.89 | **0.11** | 2 |
| **Mini-ELF v1 (rerank)** | test | **0.89** | 0.89 | 0.89 | **0.11** | 0 |
| **Mini-ELF v1 (rerank+witness)** | val | **0.89** | **1.00** | **1.00** | **0.11** | **10** |
| **Mini-ELF v1 (rerank+witness)** | test | **0.89** | **0.95** | **0.95** | **0.11** | **2** |
| Mini-ELF v1 (nn) | val | 0.59 | 0.89 | 0.89 | 0.41 | 0 |
| Mini-ELF v1 (nn) | test | 0.84 | 0.95 | 0.95 | 0.16 | 0 |

- **Reranker effect (precision).** Without it, the v1 decoder's frequency-ranked
  top-1 is *noisier* than v0 (more samples → noisier mode): `pass@1` 0.38/0.66.
  The reranker lifts `pass@1` to **0.89/0.89** and cuts **invalid@1 from 0.62→0.11
  (val) / 0.34→0.11 (test)** — it filters decoder garble out of rank 1 without
  hurting `pass@5` (it reranks only a top-frequency shortlist + witnesses, then
  keeps the frequency tail). On held-out candidates the reranker scores
  Lean-verified ones **0.97–1.0** vs failed **0.21–0.30**.
- **Witness-copy effect (recall + novelty).** `exists_witness` `pass@5` goes
  **0.0 → 1.0** on *both* splits (it copies `5`/`7`/`0` out of `∃ n, n = 5` into
  `exact ⟨5, rfl⟩`), and `novel_verified` rises to **10 (val) / 2 (test)** vs v0's
  **0** — verifiable, open-vocabulary generation a fixed-class model cannot do.
  Every witness candidate that surfaced verified (val 8/8, test 2/2).
- **Structure-aware effect (siblings).** `and_elim` and `or_intro` top-1 *family*
  accuracy goes **0.00 → 1.00** (val) — the relational sibling wall that was
  **0.00 for every prior model, including AR**. The reranker's conjunct/disjunct
  consistency features pick `h.left` vs `h.right` and `Or.inl` vs `Or.inr` by
  matching the goal against the hypothesis structure.
- v1 `rerank+witness` is the first **generative** model to match the v0 *nn
  retrieval* ablation on `pass@5` (test 0.95) while emitting open-vocabulary,
  Lean-verified novel tactics. **16–17 eval theorems/split → directional.**

### Targets vs achieved

| target (from the v1 brief) | achieved |
| --- | --- |
| test `pass@1` > 0.61 | **0.89** ✓ |
| test `pass@5` ≥ 0.90 | **0.95** ✓ |
| improve `pass@1` while preserving `pass@5` | ✓ (rerank: 0.66→0.89 test `pass@1`, `pass@5` held) |
| `novel_verified` > 0 | **10 / 2** ✓ |

## What each model teaches us

| model | result | what it shows |
| --- | --- | --- |
| majority | pass@5 0.16/0.16 | the floor; corpus is not solvable by frequency alone |
| retrieval | pass@5 0.22/0.32 | needs same-family train coverage; copies one neighbor, confuses siblings |
| log-linear | pass@5 0.65/0.76 | learned global weights beat copying; solves *lexical* siblings (`eq`, `imp`), not relational |
| AR seq2seq | pass@1 **0.70/0.76**, pass@5 0.78/0.82 | char-level generation → best **precision**; cracks `iff`; partial open-vocab (`exact ⟨N, rfl⟩`, witnesses `{0,1,2}`) |
| Mini-ELF (decoder) | pass@5 **0.84/0.90** | embedded latent + flow sampling → best **recall** via ~20 stochastic candidates/row; generates valid *alternative* proofs |
| Mini-ELF (nn) | pass@5 0.89/**1.00** | the latent space + flow place mass near correct tactics — but this variant is **retrieval**, not generation (novel-rate 0) |

Common wall: relational `and_elim` (left vs right) is top-1 family accuracy 0.00
for **every** model, and Mini-ELF's *novel* generations never verified
(`novel_verified=0`). Both are open problems, not solved capabilities.

## AR generation quality (open-vocabulary)

| metric | val | test |
| --- | --- | --- |
| avg generated length (top-1) | 17.9 | 16.3 |
| empty-generation rate | 0.00 | 0.00 |
| novel-candidate rate (not a train label) | 0.47 | 0.50 |
| candidate-invalid rate (fail lean-cli) | 0.65 | 0.65 |
| novel candidates verified | 0 | 2 |
| rows passed via a novel tactic | 0 | 2 |

- ~half of the beam's top-5 candidates are **novel** strings a fixed-class model
  cannot produce; the model learns the template `exact ⟨N, rfl⟩` and varies the
  witness over `{0,1,2}`.
- **Partial open-vocab**: solves `exists_nat_0` (test) but fails `exists_nat_5`
  / `exists_nat_7` (val) — never learned to emit `5`/`7`. Template
  generalization, not unbounded numeric extrapolation.
- Honest failure modes: `exact And.righ` (char-level truncation of `And.right`),
  `constructor\n  exact hp\n ` (incomplete block); ~65% of candidates fail Lean
  (beam emits 5; ~1–2 verify).

## Mini-ELF v0 generation quality (decoder)

| metric | val | test |
| --- | --- | --- |
| avg generated length (top-1) | 13.5 | 14.2 |
| empty-generation rate | 0.00 | 0.00 |
| **avg distinct candidates / row** | **20.3** | **19.1** |
| novel-candidate rate | 0.42 | 0.41 |
| candidate-invalid rate | 0.70 | 0.67 |
| novel candidates verified | 0 | 0 |

- **Candidate diversity is the headline**: ~20 distinct candidates/row from 32
  noise samples (vs AR's ≤5 beam), which is what lifts `pass@5` above AR.
- Generates **valid alternative proofs**: e.g. for an `And.intro` goal whose gold
  is `exact ⟨hp, hq⟩`, it emits the verified `constructor\n  exact hp\n  exact hq`.
- **Open-vocab is weaker than AR**: ~40% of candidates are novel but `novel_verified=0`
  — char-level garble (`constructoontroctoo`) and witness errors (`exact ⟨a, rfl⟩`,
  `exact ⟨1, rfl⟩` for `exists_nat_0`). The nn-decode variant has novel-rate 0.
- AE val reconstruction is 0.89, so in-distribution latents decode faithfully; the
  failures are off-distribution flow samples.

## Sibling-family top-1 *family* accuracy

Majority and retrieval = 0.00 on every group, both splits.

| sibling group | log-linear v/t | AR v/t | Mini-ELF v0 dec v/t | **Mini-ELF v1 rerank v/t** |
| --- | --- | --- | --- | --- |
| `eq` (refl/symm/trans) | 1.00 / 1.00 | 1.00 / 1.00 | 0.50 / 0.50 | 1.00 / 1.00 |
| `imp` (identity/compose/modus_ponens) | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| `iff` (mp/mpr/intro) | 0.00 / 0.75 | 1.00 / 1.00 | 0.50 / 1.00 | 1.00 / 1.00 |
| `or_intro` (left/right) | 0.00 / 0.00 | 0.50 / 0.50 | 0.50 / 0.25 | **1.00 / 1.00** |
| `and_elim` (left/right) | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | **1.00 / 1.00** |

**Mini-ELF v1's reranker is the first model to clear `and_elim`** (left vs right
conjunct), which was top-1 family accuracy **0.00 for every other model including
AR**, and to take `or_intro` to 1.00 on both splits. Its structure-aware features
(conjunct/disjunct consistency from the heuristic parser) pick `h.left` vs
`h.right` and `Or.inl` vs `Or.inr` by matching the goal against the hypothesis
structure — the relational reasoning the v0 roadmap flagged as the clearest gap.
(v1 numbers are the `decoder_rerank` mode; the underlying flow decoder's raw
top-1 is still noisy — the reranker, not the sampler, supplies the precision.)

## Per-family notes

- **Log-linear reaches pass@5 = 1.00** on families where retrieval scored 0.00:
  `and_comm`, `eq_trans`, `iff_mp`, `imp_compose`, `imp_identity` (val) and
  `and_intro`, `iff_intro`, `iff_mpr`, `modus_ponens`, `or_intro_right` (test).
- **AR shrinks the 0-pass@5 set further.** Log-linear was 0-pass@5 on
  `{and_elim_right, exists_witness, or_intro_left, or_self_elim}` (val) and
  `{and_elim_left, or_self_elim}` (test); AR is 0-pass@5 only on
  `{exists_witness, or_self_elim}` (val) and `{and_elim_left}` (test) — it newly
  clears `and_elim_right` (val), `or_self_elim` (test), and `exists_witness`
  (test, via witness `0`).
- **Sibling discriminator stays the wall.** Top-1 *family* accuracy on
  `and_elim` is still 0.00 even for AR (its top-1 picks the wrong conjunct);
  `pass@5` can still succeed when the right tactic lands lower in the beam.
- **Open-vocabulary (AR)**: AR composes the `exact ⟨N, rfl⟩` template and varies
  `N` over `{0,1,2}` — so it solves `exists_nat_0` (test) but not
  `exists_nat_5`/`exists_nat_7` (val). The log-linear classifier cannot generate
  any of these (the witness string is not a fixed class).

## Remaining limitations

| Limitation | Detail |
| --- | --- |
| No real next-state supervision | theorem-level only; `state_after_is_real=false` (AR + Mini-ELF v0/v1 included) |
| LeanDojo `run_tac` blocked | Lean elaboration-stdin EOF; documented `xfail` |
| Small corpus / eval splits | 134 theorems; 16–17 eval theorems per split → directional; v1's clean reranker separation partly reflects the small, templated corpus |
| Mini-ELF v0/v1 are tactic generators, not sequence-to-state models | scored at theorem level; v1 is still **not** full ELF over proof states |
| Witness-copy is symbolic augmentation | explicit template `exact ⟨N, rfl⟩` over copied literals — evaluated honestly by the same Lean verifier, but **not** pure neural generation |
| Reranker self-training uses Lean labels on **train** theorems only | no val/test leakage; but its hard negatives are v1's own flow candidates, a closed loop on a small corpus |
| `exists_witness` solved at `pass@5`, not `pass@1` | the witness lands at rank 2–3, not 1; `or_self_elim` (multi-step case split) still unsolved (`pass@5` 0) |
| `nn` ablation is retrieval | snaps latents to train tactics; novel-rate 0; not open-vocabulary generation |
