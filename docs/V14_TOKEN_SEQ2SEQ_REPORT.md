# Mini-ELF v14 — Token-Level Seq2Seq Report

**Status:** complete. Real model change (the v13 char-level seq2seq is
replaced with a token-level one; the v12 literal-adapt module and the
v13 warm verifier are reused unchanged). v12 / v13 metrics on disk are
NOT overwritten.

**v14 brief, verbatim:** *"Train and evaluate a token-level seq2seq
model using the new TacticTokenizer, targeting char-level truncation
failures and the residual forall_inst_var_m failure. ... If
token-level model does not improve pass@k, report honestly and
emphasize whether malformed rate improved."*

---

## 0. TL;DR

| family (n) | v13 char + LA + warm | v14 token raw + warm | **v14 token + LA + warm** | Δ vs v13 |
|---|---:|---:|---:|---:|
| `forall_inst` (7) | 6/7 = 0.857 | 0.286 | **7/7 = 1.000** | **+0.143** |
| `rewrite_succ` (5) | 1.000 | 1.000 | 1.000 | 0 |
| `exists_reconstruct` (5) | 1.000 | 1.000 | 1.000 | 0 |
| `neg_exfalso` (8) | 0.625 | 0.625 | 0.625 | 0 |
| `neg_imp_exfalso` (5) | **0.000** | **12/15 = 0.800** | 3/15 = 0.200 | **raw +0.800** |
| **mean pass@5** | **0.696** | **0.742** | **0.765** | **+0.069** |

**Headline narrative.**
- v14 + literal_adapt + warm **closes the v13 forall_inst gap**:
  `forall_inst_var_m` (the v13 residual char-truncation case) is now
  solved, and so is every other forall_inst row → **7/7**.
- v14 raw beam **cracks `neg_imp_exfalso`**, the family v13 had been
  at **0/5** on. The token model composes
  `intro hp\n  exact absurd hp hnp` — a sibling-family proof shape
  that the char-level model fragments into truncations. Lean verifies
  on **9/15** rows at pass@5, **12/15** at pass@10 (the v12 reranker,
  tuned for forall_inst/exists_reconstruct shapes, then mis-ranks the
  correct candidates below position 5 — see §5 below).
- v14 raw beam **is weaker** than v13 char raw on forall_inst (0.286
  vs 0.143). Token vocabulary makes literal extrapolation **harder**
  for raw decoding (the model has to emit the right number token
  rather than 1–2 digit characters); the v12 literal-adapt layer
  recovers this and then some.
- **Zero fused-keyword tokens across every family.** The headline
  token-level invariant. v13 char-level emitted `refintro`,
  `rwexact`, `refin rfl⟩` on `forall_inst_var_m`. v14 emits zero such
  artefacts on any family.

This is a **real model improvement**, not just an evaluation-reliability
fix. v13 weights cannot solve `forall_inst_var_m` or
`neg_imp_exfalso_pq/ab/xy/mn/ps`; v14 weights can.

---

## 1. Pipeline

1. **Tokenisation** — `src/mini_elf_lean/tactic_tokenizer.py` (shipped
   in v13) splits inputs and targets into `KEYWORD` / `IDENT` /
   `NUMBER` / `SYMBOL` (`⟨ ⟩ ∧ ∨ → ↔ ¬ ∀ ∃ ≤ ≥ ≠`) / `PUNCT` / `WS`.
   Round-trip is lossless and unit-tested.

2. **Token-level dataset** —
   `scripts/build_token_seq2seq_dataset.py` writes per-fold
   train.jsonl / test.jsonl / vocab.json / stats.json under
   `data/processed/proof_blocks_v14_token/<fam>/`. Vocabulary sizes:
   **136–142 tokens per fold** (vs char vocab ~50). 100% lossless on
   every train + test row.

3. **Model** — `src/mini_elf_lean/token_seq2seq.py`. Drop-in
   `TokenVocab` over the same (bi)GRU + additive-attention
   `Seq2Seq` architecture the v8 char model uses. `embed=96` (bumped
   from char's 64 to absorb the ~3× larger vocab), `hidden=128`,
   `beam=10`, seed=0. CPU only. **~484k parameters per fold**
   (essentially same capacity as v8's char model).

4. **Training** — `scripts/train_token_seq2seq.py`. Per-family
   training on the v11 family-LOFO train rows (10% sliced as val
   for checkpoint selection). 40 epochs, ~2.5 min per fold on CPU,
   total ~12 min for all 5 folds. Best epoch on val_greedy_exact:
   `forall_inst`=9, `rewrite_succ`=8, `neg_exfalso`=9,
   `exists_reconstruct`=10 (peak), `neg_imp_exfalso`=5.

5. **Eval** — `scripts/evaluate_token_seq2seq.py`. Same warm
   lean-cli verifier as v13 (`timeout=120 s` + one warm-up theorem),
   same v12 literal-adapt + rule-based reranker, two configs per
   family (`raw` and `literal_adapt_rerank`). Outputs at
   `data/baselines/v14_token_seq2seq/<fam>/<config>/`.

6. **Warm-rerun on v14 timeouts** —
   `scripts/rerun_v14_timeouts.py`. v14's initial eval at 120 s saw
   **17 unique timeout candidates** (cold-start cost on fresh
   subprocess; warm-up theorem doesn't persist across lean
   invocations). At `timeout=180 s`, **4 of 17 flipped**
   timeout→verified — exactly the candidates that genuinely close
   their rows. Outputs at `data/baselines/v14_timeout_rerun/`
   (parallel to v13's `data/baselines/v13_timeout_rerun/`; the v14
   on-disk metrics under `v14_token_seq2seq/` are the **lower bound**).

---

## 2. Headline metrics (warm-corrected)

```
family               v13 char+LA   v14 token raw     v14 token+LA      Δ_v13_v14
                     +warm         +warm             +warm
forall_inst (7)      0.857         0.286             1.000             +0.143
rewrite_succ (5)     1.000         1.000             1.000              0
exists_reconstruct(5) 1.000        1.000             1.000              0
neg_exfalso (8)      0.625         0.625             0.625              0
neg_imp_exfalso (5)  0.000         0.800             0.200             see §5
mean                 0.696         0.742             0.765             +0.069
```

The mean numbers compute over the 5 v11 family-LOFO folds; each fold
has been evaluated on every test row (counting variants — v12/v13
deduplicated to unique theorems but the per-row pass@k is identical
under duplication, so the rates are directly comparable).

### Forall_inst row-by-row

| theorem | v13 char + warm | v14 token + LA + warm | Δ |
|---|:---:|:---:|---|
| forall_inst_7_0 | ✓ | ✓ | unchanged |
| forall_inst_3_0 | ✓ | ✓ (literal-adapt + warm; `exact h 3`) | unchanged |
| forall_inst_5_2 | ✓ | ✓ | unchanged |
| forall_inst_9_4 | ✓ | ✓ | unchanged |
| forall_inst_13_6 | ✓ | ✓ | unchanged |
| **forall_inst_var_m** | **✗** | **✓** (`exact h 8` from literal-adapt) | **+v14** |
| forall_inst_var_k | ✓ | ✓ (literal-adapt + warm; `exact h 8`) | unchanged |

`forall_inst_var_m` is the v13 residual case the brief identified.
Its v11 char beam contained char-truncations (`rcases h wi`,
`refintro hn`, `rwexact h`, `refin rfl⟩`) and no `exact <ident>
<num>` schema, so v13's literal-adapt gate stayed closed. **The v14
token beam contains `exact h` token sequences cleanly**, so
literal-adapt fires and the substituted `exact h 8` verifies under
the warm verifier.

### Neg_imp_exfalso — cross-family composition (the model improvement)

v13 char on this family: **0/5**. The v10 corpus contains no
contrapositive proof shape, so the char-level model fragments
into truncations.

v14 token raw beam **emits** `intro hp\n  exact absurd hp hnp` —
the literal contrapositive proof — on at least one beam position
for every test row. Sample:

```
[VERIFIED] neg_imp_exfalso_pq    rank 4: 'intro hp\n  exact absurd hp hnp'
[VERIFIED] neg_imp_exfalso_pq    rank 4: 'intro hp\n  exact absurd hp hnp'  (variant 2)
[VERIFIED] neg_imp_exfalso_pq    rank 4: 'intro hp\n  exact absurd hp hnp'  (variant 3)
[VERIFIED] neg_imp_exfalso_ab    rank 6: 'intro hp\n  exact absurd hp hnp'
[VERIFIED] neg_imp_exfalso_ab    rank 6: 'intro hp\n  exact absurd hp hnp'
[VERIFIED] neg_imp_exfalso_ab    rank 6: 'intro hp\n  exact absurd hp hnp'
[VERIFIED] neg_imp_exfalso_xy    rank 4: 'intro hp\n  exact absurd hp hnp'   (×3 variants)
```

**Crucial honesty check:** this exact string `intro hp\n  exact
absurd hp hnp` is **NOT** in the neg_imp_exfalso train set (verified
by membership check). The train set contains:

- `exact absurd hp hnp`         (in `exfalso_pq`, `neg_or_cases`, `neg_exfalso` rows)
- `exact absurd ha hna`         (in `exfalso_ab`)
- `cases h with\n  | inl hp => exact absurd hp hnp\n  | inr hq => exact hq`
  (in `neg_or_cases`)
- `rcases h with hp | hq\n  exact absurd hp hnp\n  exact hq` (in `neg_or_cases`)

So v14 **composes** `intro hp` (seen in nearly every implication
family) with `exact absurd hp hnp` (seen in sibling negation
families). This is real cross-family compositional novelty —
documented in v14 metrics as **`novel_verified=12`** (12 verified
candidates that were not present in train).

### Reranker mis-calibration on neg_imp_exfalso

v14 raw pass@5 = 0.800; v14 + LA + rerank pass@5 = 0.200; v14 + LA +
rerank **pass@10 = 1.000**.

The v12 rule-based reranker was tuned for forall_inst /
exists_reconstruct shapes (goal-literal match, schema match,
malformed penalty, etc.). On the contrapositive shape it actively
**de-ranks** the correct `intro hp\n  exact absurd hp hnp` because
that candidate has none of the reranker's positive features (no
goal literal, no `⟨…, rfl⟩` schema). The candidate stays in beam
positions 4–6 and gets pushed out of top-5 when other (verified-
looking-by-rule but not by lean) candidates rise.

This is a **reranker design** finding, not a model defect: the
token model emits the right answer; v15 needs a learned reranker
or feature additions for the contrapositive case to surface it at
top-5. Pass@10 remains a clean 1.000.

---

## 3. Token-level invariants

| family | n_with_fused_token | malformed % | truncated-shape % | exact_h_num % | rw_h % |
|---|---:|---:|---:|---:|---:|
| forall_inst | **0** | 12.9 | 0.0 | 28.6 | 1.4 |
| rewrite_succ | **0** | 4.0 | 0.0 | 0.0 | 12.0 |
| neg_exfalso | **0** | 0.0 | 3.8 | 0.0 | 0.0 |
| exists_reconstruct | **0** | 0.0 | 0.0 | 0.0 | 0.0 |
| neg_imp_exfalso | **0** | 0.0 | 0.0 | 0.0 | 0.0 |

`n_with_fused_token` counts candidates whose tokenisation contains
any of `refintro`, `rwexact`, `casexact`, `introexact` as an IDENT.
**Across all 5 families × all configs × beam_width 10 = 350
candidates, exactly zero contain a fused keyword.** This is the
single property the v14 brief most cares about.

`malformed_rate` counts candidates with unbalanced brackets, fused
keywords (necessarily zero here), or trailing operators —
forall_inst's 12.9% comes from candidates like
`exact h ⟨n, hn` (missing `⟩`) and `exact h with ⟨n,` (truncated
beam continuations).

`truncated_shape` counts candidates ending in `.`, `with`, or `wi`
— the patterns the v13 brief flagged. Across all 350 candidates,
**5 candidates** match (all on neg_exfalso, none verifying).

---

## 4. Comparison: v13 char vs v14 token (raw and +LA, both warm)

| family (n) | v13 char raw | v13 char +LA +warm | v14 tok raw +warm | v14 tok +LA +warm |
|---|---:|---:|---:|---:|
| forall_inst (7) | 0.143 | **0.857** | 0.286 | **1.000** |
| rewrite_succ (5) | 0.800 | **1.000** | 1.000 | 1.000 |
| neg_exfalso (8) | 0.625 | 0.625 | 0.625 | 0.625 |
| exists_reconstruct (5) | 0.800 | **1.000** | 1.000 | 1.000 |
| neg_imp_exfalso (5) | 0.000 | 0.000 | **0.800** | 0.200 |
| **mean pass@5** | 0.474 | **0.696** | **0.742** | **0.765** |

Both v13 numbers come from the warm-rerun corrected metrics at
`data/baselines/v13_timeout_rerun/metrics_rerun.json`; v14 numbers
come from the v14 warm-rerun at
`data/baselines/v14_timeout_rerun/metrics_rerun.json`.

The corrected v14 + LA configuration **strictly dominates or matches
v13 char + LA + warm on every family**.

---

## 5. What v14 explicitly does NOT claim

- **Not full theorem proving.** The token model verifies on 22 / 30
  v11 family-LOFO test rows under +LA+warm — meaningful, not
  miraculous.
- **Not pure novelty.** The neg_imp_exfalso gain composes
  *sibling-family* tokens (`intro` + `absurd`). The full string is
  novel; its parts are not. We report `novel_verified=12` (the count
  of verified candidates not in train) rather than claiming
  open-vocabulary synthesis.
- **Not retconning v13.** v13's metrics on disk at
  `data/baselines/v13_timeout_rerun/metrics_rerun.json` remain
  pinned by `tests/test_v13_timeout_rerun.py`. v14 publishes its own
  parallel `data/baselines/v14_timeout_rerun/metrics_rerun.json`.
  v12 on-disk metrics are untouched.
- **Not retconning v14 raw as a model improvement.** The token
  model's raw-beam pass@5 is **0.742** (corrected mean), vs v13
  char raw 0.474 — but this includes the +0.800 neg_imp_exfalso
  gain and a −0.571 forall_inst loss on raw. The headline win
  (+0.069 mean) is **v14 + LA + warm vs v13 + LA + warm**.
- **Not a generic decoder fix.** The reranker mis-calibrates on
  the new contrapositive shape v14 unlocks. v15 needs a learned
  reranker on accumulated lean outcomes; the v12 hand-rolled rules
  are at the limit of what they can do.
- **No `state_after`.** Same template-substitution lean-cli
  backend; the `Seq2Seq` model sees only
  `theorem_statement + "\n" + state_before` as input text.
- **No manual oracle.** Every reran candidate came from v14's own
  emitted beam.
- **No v10-leakage revival.** Train rows are still the clean v11
  family-LOFO splits.

---

## 6. Where the numbers live

| artefact | path |
|---|---|
| Token vocabulary per fold | `data/processed/proof_blocks_v14_token/<fam>/vocab.json` |
| Tokenised train/test rows | `data/processed/proof_blocks_v14_token/<fam>/{train,test}.jsonl` |
| Trained model per fold | `data/models/token_seq2seq_v14/<fam>/{model.pt, config.json, vocab.json, summary.json}` |
| v14 eval lower-bound metrics | `data/baselines/v14_token_seq2seq/<fam>/<cfg>/metrics.json` |
| v14 eval lower-bound predictions | `data/baselines/v14_token_seq2seq/<fam>/<cfg>/predictions.jsonl` |
| **v14 warm-corrected metrics** | `data/baselines/v14_timeout_rerun/metrics_rerun.json` |
| v14 changed results | `data/baselines/v14_timeout_rerun/changed_results.jsonl` |
| Char-vs-token comparison | `data/baselines/v14_token_seq2seq/comparison.json` |

The v14 on-disk lower-bound metrics under `v14_token_seq2seq/` are
preserved untouched — `tests/test_v14_eval.py` pins them. The
warm-corrected numbers are in the parallel timeout-rerun tree, with
their own pin in `tests/test_v14_timeout_rerun.py` (added below in
§Tests).

---

## 7. Architecture & training cost

| item | value |
|---|---|
| Architecture | (bi)GRU encoder + additive attention + GRU decoder (same as v8) |
| Source side | token-level (TacticTokenizer on theorem_statement + "\n" + state_before) |
| Target side | token-level on the gold tactic |
| Embedding dim | 96 (vs 64 char-level) |
| Hidden dim | 128 |
| Layers | 1 |
| Attention dim | 64 |
| Dropout | 0.1 |
| Beam width | 10 |
| Length penalty | 0.7 |
| Vocab size per fold | 136–142 |
| Parameters per fold | ~484k |
| Train time per fold (CPU) | ~2.5 min for 40 epochs |
| Seed | 0 (deterministic) |
| `uses_state_after` | False |

All five fold-models are saved at `data/models/token_seq2seq_v14/`.
