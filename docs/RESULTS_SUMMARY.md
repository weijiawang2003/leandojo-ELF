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

**Two complementary winners.** AR has the best **precision** (`pass@1`); Mini-ELF
v0 has the best **recall** (`pass@5`, beating AR on both splits) thanks to ~20
distinct stochastic candidates/row. The nn-decode ablation tops `pass@k` (test
`pass@5` 1.00) but is latent-space retrieval, **not** open-vocabulary generation.

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

| sibling group | log-linear val/test | AR seq2seq val/test | Mini-ELF v0 (decoder) val/test |
| --- | --- | --- | --- |
| `eq` (refl/symm/trans) | 1.00 / 1.00 | 1.00 / 1.00 | 0.50 / 0.50 |
| `imp` (identity/compose/modus_ponens) | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| `iff` (mp/mpr/intro) | 0.00 / 0.75 | **1.00 / 1.00** | 0.50 / 1.00 |
| `or_intro` (left/right) | 0.00 / 0.00 | 0.50 / 0.50 | 0.50 / 0.25 |
| `and_elim` (left/right) | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |

AR has the cleanest top-1 family accuracy. Mini-ELF v0's top-1 (most-frequent
sample) is noisier — its strength is `pass@5`, not top-1 precision. Purely
*relational* `and_elim` (goal = first vs second conjunct) stays at 0.00 for
**every** model.

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
| No real next-state supervision | theorem-level only; `state_after_is_real=false` (AR + Mini-ELF included) |
| LeanDojo `run_tac` blocked | Lean elaboration-stdin EOF; documented `xfail` |
| Small corpus / eval splits | 134 theorems; 16 eval theorems per split → directional |
| AR + Mini-ELF are tactic generators, not sequence-to-state models | scored at theorem level; open-vocab partial |
| Mini-ELF v0 ≠ full ELF method | tactic-AE + conditional rectified-flow; trails AR on `pass@1`; `novel_verified=0`; not real proof-state flow |
| Synthetic candidates | template-generated; no real LLM proposals collected yet |
| Relational `and_elim` + out-of-range numeric witnesses unsolved | needs structure-aware modeling |
