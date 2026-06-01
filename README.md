# mini-elf-lean: verifier-filtered Lean tactic trace collector

A small, modular **data factory** for Lean 4 tactic traces. It turns candidate
tactics (from a mock, a hand-written/agent JSONL file, or a real LLM) into a
clean, Lean-verified dataset of `(state_before, tactic)` records, and benchmarks
tactic-prediction baselines against a real Lean verifier. The principle
throughout: **candidate generators propose, Lean verifies** — a raw candidate is
never a positive label until Lean accepts it.

> **Scope honesty.** Verification here is **theorem-level** (lean-cli typechecks
> the whole proof file): the dataset is for *tactic prediction*, **not** true
> `state_before → tactic → state_after` modeling — every row is flagged
> `state_after_is_real=false`. The Mini-ELF v0/v1 models are small **prototypes
> of the generation loop** (tactic-string latents + flow + reranker), **not** the
> full ELF method over proof states.

📄 **Read more:** [Project report](docs/PROJECT_REPORT.md) ·
[Results summary](docs/RESULTS_SUMMARY.md) ·
[Next steps](docs/NEXT_STEPS.md) · [Résumé bullets](docs/RESUME_BULLETS.md)

## Current status

- [x] Verifier-filtered pipeline (propose → sanitize → Lean-verify → trace)
- [x] Backends: `mock`, `manual-file`, **`lean-cli` (real, theorem-level)**
- [x] LeanDojo: tracing + initial `TacticState` work; **`run_tac` blocked
      (`xfail`)** — Lean elaboration-stdin EOF, [documented](docs/LEANDOJO_SETUP.md) not hidden
- [x] Dataset builder with honest `verification_quality` / `state_after_is_real`
- [x] Basic corpus: **134 theorems, 21 pattern families, 329 verified / 287 failed**
- [x] Baselines: majority, retrieval, **trained log-linear classifier**
- [x] **Generative AR model**: char-level GRU+attention seq2seq (PyTorch CPU) —
      beats the classifier and generates *novel* (open-vocabulary) tactics
- [x] **Mini-ELF v0**: tactic-autoencoder latent + conditional rectified-flow
      generator — beats AR on `pass@5` (recall) via stochastic candidate diversity
- [x] **Mini-ELF v1**: structure-aware encoder + denoising AE + **verifier-aware
      reranker** + **witness-copy** — test `pass@1` 0.89, `pass@5` 0.95 on the
      *basic* corpus, the first model to crack `and_elim`
- [x] **Mini-ELF v2 (generalization study)**: a harder 94-theorem corpus +
      adversarial/family/difficulty splits show v1's basic numbers **do not
      transfer** (`pass@5` 0.95 → 0.00–0.23 under shift); retraining on
      combined data recovers in-distribution-hard (`pass@5` 1.00) but **not**
      compositional holdout — [`docs/V2_GENERALIZATION_REPORT.md`](docs/V2_GENERALIZATION_REPORT.md)
- [x] **Mini-ELF v3 (structured proof-block planner)**: a symbolic planner that
      *constructs* proofs (chains / projections / case splits / iff·eq
      composition) fused with the v2 model — takes the compositional
      `difficulty_holdout` `pass@5` **0.06 → 1.00** (ablation: planner off =
      0.08) and recovers basic to 1.00. **Engineered symbolic coverage, not
      learned generalization** — [`docs/V3_PROOF_PLANNER_REPORT.md`](docs/V3_PROOF_PLANNER_REPORT.md)
- [x] **Mini-ELF v4 (planner-blind benchmark)**: a 61-theorem corpus of proof
      shapes the planner cannot construct (negation, contrapositive, ∃-elim,
      ∀-inst, rewrite). Unchanged v3 **collapses** to `pass@5` 0.096; a
      controlled template-addition ablation recovers only the *targeted* families
      (whack-a-mole), leaving `forall_inst`/`rewrite_succ` at 0.00 —
      [`docs/V4_PLANNER_BLIND_REPORT.md`](docs/V4_PLANNER_BLIND_REPORT.md)
- [x] **Mini-ELF v5 (data-driven candidate proposers)**: a common proposer
      interface + a **retrieval** proof-block proposer (example reuse + numeric
      adaptation, no per-shape template) takes the two families *no* v4 template
      recovered — `forall_inst` and `rewrite_succ` — to **pass@5 1.00** on a
      within-family split, the first escape from whack-a-mole. Honest limit: it
      is example reuse, not reasoning, and char-similarity still confuses negation
      siblings; LLM pilot gated on a key — [`docs/V5_RESULTS_SUMMARY.md`](docs/V5_RESULTS_SUMMARY.md)
- [x] **Mini-ELF v6 (structure-aware retrieval)**: re-ranks the same retrieval
      candidates by heuristic **structural** features (goal/hypothesis shape,
      required-operation guess, conjunct position) + an adapted-candidate
      preference — fixes all four v5 ranking failures. Retrieval-alone reaches
      planner-blind-split `pass@1 = pass@5 = 1.00` (`forall_inst` pass@1
      **0.00 → 1.00**, `neg_exfalso`/`exists_elim_conj` 0.00 → 1.00) — ranking, not
      reasoning — [`docs/V6_STRUCTURE_AWARE_RETRIEVAL_REPORT.md`](docs/V6_STRUCTURE_AWARE_RETRIEVAL_REPORT.md)
- [x] **Mini-ELF v7 (retrieval under donor scarcity)**: a graded donor-scarcity
      benchmark (interpolation → k-shot → literal-holdout → family-holdout →
      operation-holdout → 0-shot) + a template-free operation-**abstraction**
      re-ranker. Shows v6's 1.00 was **same-family interpolation** (forbid
      same-family → 0.00) and that genuine family/operation holdout collapses
      *every* config to **0.00** (`cross_family_verified = 0`): the determinant is
      donor *presence vs. absence*, not quantity. Abstraction helps only the scarce
      1-shot regime (pass@1 0.832 → 0.924). The wall is donor coverage, not ranking
      — [`docs/V7_RETRIEVAL_HOLDOUT_REPORT.md`](docs/V7_RETRIEVAL_HOLDOUT_REPORT.md)
- [x] **Mini-ELF v8 (generative donorless proposer)**: CPU char-seq2seq
      trained on a 690-row pooled corpus (basic + hard + planner-blind) under
      `interpolation` / `family_holdout` × 10 / `operation_holdout` × 7 /
      `donorless_eval` regimes (18 models). **5 non-zero donorless cells,
      15 verified candidates, 13 novel** — `family_holdout/neg_exfalso`
      pass@5 **0.625** (9 novel; the project's first non-zero
      `cross_family_verified` on a v7 holdout) and
      `operation_holdout/intro_negation` pass@5 **0.125**
      (`cross_operation_verified = 3`). Negative control `forall_inst` stays
      0/7 — the mechanism is sibling-family token composition, not abstract
      synthesis — [`docs/V8_GENERATIVE_PROPOSER_REPORT.md`](docs/V8_GENERATIVE_PROPOSER_REPORT.md) ·
      matrix [`docs/V8_FULL_EVAL_MATRIX.md`](docs/V8_FULL_EVAL_MATRIX.md)
- [x] **Mini-ELF v9 (data-scaling plan, no new pass@k)**: matrix
      consolidation + LLM pilot SKIPPED honestly + a 10-cell
      proof-of-concept redundancy corpus (2 operations × 5 sibling
      families; all 10 lean-cli verified before commit) staging the v10
      experiment — [`docs/V9_DATA_SCALING_PLAN.md`](docs/V9_DATA_SCALING_PLAN.md)
- [x] **Mini-ELF v10 (operation×surface-family redundancy corpus + scaling)**:
      a **40-cell** verified corpus over 8 proof operations × 5 sibling
      surface families (`scripts/generate_redundancy_corpus.py`; the 8 cells
      previously refused as WSL cold-start timeouts all verified at a
      longer timeout cap, leaving `redundancy_lean_cli_failed.jsonl`
      empty). Found and **corrected a major leakage bug**: the legacy
      `combined_v10` (interpolation-trained) had 36 of 40 holdout test
      theorems in its train pool; the prior "5/8 op-holdout wins"
      headline was in-distribution memorisation, not generalisation. The
      correction: 8 per-operation LOFO models
      (`scripts/build_combined_v10_per_op.py` + train script; inline +
      `tests/test_v10_no_leakage.py` invariants enforce zero leakage),
      evaluated cleanly at `data/baselines/v10_eval_clean/per_op/<op>/`.
      **Honest clean signal (16/16 cells)**: mean pass@5 **0.600** vs
      baseline_v8 zero-shot 0.575 (Δ +0.025); per-fold 2 wins / 1 loss
      / 5 ties; total `cross_operation_verified` 39 vs 34 (+5). Small,
      mixed, occasionally useful — not the dramatic uniform lift the
      leaked draft claimed. **Data scaling only**: same architecture, no
      `state_after`, no Mathlib, no manual oracle counted — [`docs/V10_REDUNDANCY_CORPUS_REPORT.md`](docs/V10_REDUNDANCY_CORPUS_REPORT.md) ·
      [`docs/V10_SEQ2SEQ_SCALING_REPORT.md`](docs/V10_SEQ2SEQ_SCALING_REPORT.md)
- [x] **Mini-ELF v11 (clean per-family LOFO with v10 redundancy)**: directly
      tests whether v10 redundancy unblocks the v8/v9 negative-control
      families `forall_inst` and `rewrite_succ`. Train per held family =
      v8 family-LOFO train + 40 v10 cells minus any held-test
      `(theorem_name, state_before, tactic)` duplicate. 5 per-family
      seq2seq models trained (`scripts/build_v11_family_lofo.py`,
      `scripts/train_v11_family_lofo.sh`); 5 leakage-guard tests
      ([`tests/test_v11_family_lofo_no_leakage.py`](tests/test_v11_family_lofo_no_leakage.py)).
      Headline (vs the same-test-row v8 LOFO baseline): **`rewrite_succ` 0/5 → 4/5 pass@5 (+0.800)**,
      **`forall_inst` 0/7 → 1/7 (+0.143)**, `exists_reconstruct` 2/5 → 4/5 (+0.400),
      `neg_exfalso` precision lift (pass@1 0.125 → 0.625) with unchanged
      recall, `neg_imp_exfalso` unmoved (v10 has no contrapositive shape).
      `novel_verified = 0` on every win — v11 copies the right tactic
      from v10 siblings, it does not synthesise novel strings.
      **The 5th `rewrite_succ` row also emitted `rw [h]` at rank 0 but the
      lean-cli verifier timed out**; reported honestly as 0.800 (not
      retconned). Same architecture, no `state_after`, no manual oracle,
      no Mathlib — [`docs/V11_FAMILY_LOFO_REDUNDANCY_REPORT.md`](docs/V11_FAMILY_LOFO_REDUNDANCY_REPORT.md) ·
      [`docs/V11_FAILURE_EXAMPLES.md`](docs/V11_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v12 (literal-aware decode + rule-based reranker)**:
      post-generation processing on the v11 model's beam output — no new
      training, no model changes, no `state_after` access. The literal-
      adapt module ([`src/mini_elf_lean/literal_aware_decode.py`](src/mini_elf_lean/literal_aware_decode.py))
      detects `exact <h> <num>` / `exact ⟨<num>, rfl⟩` schemas and
      substitutes the first goal literal in. The rule-based reranker
      ([`src/mini_elf_lean/proof_block_reranker.py`](src/mini_elf_lean/proof_block_reranker.py))
      scores candidates on goal-literal match, stale-literal penalty,
      malformed penalty, schema match, and source priority. Clean v11
      family-LOFO eval reused. Headline: **`forall_inst` 1/7 → 3/7
      pass@5 (+0.286)** via literal-adapt+rerank combined (one v12 win is
      `novel_verified` against the LOFO train pool); **`exists_reconstruct`
      4/5 → 5/5 (+0.200)** via the ⟨N, rfl⟩ witness shape;
      **`rewrite_succ` preserved at 0.800** (brief floor); `neg_exfalso`,
      `neg_imp_exfalso` unchanged. **3 of the 4 remaining `forall_inst`
      failures emit the correct adapted candidate at rank 0 but the
      lean-cli cold-start timed out** — reported as FAIL, honest lower
      bound. Char-level truncation deferred to v13 (see
      [`docs/V12_TOKENIZATION_NOTE.md`](docs/V12_TOKENIZATION_NOTE.md)) —
      [`docs/V12_LITERAL_RERANK_REPORT.md`](docs/V12_LITERAL_RERANK_REPORT.md) ·
      [`docs/V12_FAILURE_EXAMPLES.md`](docs/V12_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v13 (warm-verifier rerun + tactic-token tokenizer prototype)**:
      no model retraining and no v12 metric overwrites — the v12 weights, the
      v12 literal-adapt module and the v12 reranker are byte-for-byte
      unchanged. v13 (a) reruns every v12 timeout candidate with a 120-second
      lean-cli timeout and a one-shot warm-up theorem, removing the 20-s
      cold-start noise floor; and (b) ships a token-level Lean-tactic
      tokenizer ([`src/mini_elf_lean/tactic_tokenizer.py`](src/mini_elf_lean/tactic_tokenizer.py))
      + unit tests so a future v14 trainer cannot produce the mid-token
      truncations (`rcases h wi`, `refintro hn`, `rwexact h`) the v12
      char-level decoder still emits. The token-level seq2seq retrain
      itself is deferred to v14. Warm-verifier headline: **`forall_inst`
      3/7 → 6/7 pass@5 (+0.428)** as `exact h 5` / `exact h 13` / `exact h 8`
      flip from `timeout` to verified; **`rewrite_succ` 4/5 → 5/5 (+0.200)**
      as `rw [h]` on `rewrite_succ_ij` flips; everything else unchanged. This
      is an **evaluation-reliability gain, not a model improvement** — v12
      lower-bound metrics on disk are untouched, the corrected numbers live
      at `data/baselines/v13_timeout_rerun/metrics_rerun.json`, and a single
      residual `forall_inst_var_m` failure remains as a char-truncation +
      schema-gate case targeted at v14 —
      [`docs/V13_TIMEOUT_RERUN_REPORT.md`](docs/V13_TIMEOUT_RERUN_REPORT.md) ·
      [`docs/V13_TOKENIZATION_DECISION.md`](docs/V13_TOKENIZATION_DECISION.md)
- [x] **Mini-ELF v14 (token-level seq2seq)**: a real model change —
      the v13 char-level seq2seq is replaced by a token-level one
      trained on the v13 `tactic_tokenizer`. Same (bi)GRU+attention
      architecture (~484k params), same v11 family-LOFO folds, same
      v12 literal-adapt + reranker, same v13 warm verifier
      (`timeout=120 s` initial + `180 s` rerun for v14 timeouts). The
      headline target (`forall_inst_var_m` — v13's char-truncation
      residual) is **solved**, taking forall_inst to **7/7 = 1.000**
      pass@5 (+0.143 vs v13). Bigger surprise: the token model
      **cracks `neg_imp_exfalso`** — v13's 0/5 contrapositive floor
      — at **raw pass@5 = 12/15 = 0.800** by composing
      `intro hp\n  exact absurd hp hnp` from sibling-family training
      tokens (`novel_verified=12`). The headline +LA configuration's
      pass@5 drops to 0.200 there because the v12 reranker
      mis-calibrates on the contrapositive shape, but **pass@10 =
      1.000** — the candidate is in the beam, the reranker just
      doesn't promote it. Token-level invariant: **zero fused-keyword
      tokens** (`refintro`/`rwexact`/`refin rfl⟩`) across all 5
      families × beam=10. v12 and v13 metrics on disk untouched;
      corrected v14 numbers live at
      `data/baselines/v14_timeout_rerun/metrics_rerun.json`; 124 new
      tests pin the structure —
      [`docs/V14_TOKEN_SEQ2SEQ_REPORT.md`](docs/V14_TOKEN_SEQ2SEQ_REPORT.md) ·
      [`docs/V14_CHAR_VS_TOKEN_REPORT.md`](docs/V14_CHAR_VS_TOKEN_REPORT.md) ·
      [`docs/V14_FAILURE_EXAMPLES.md`](docs/V14_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v15 (learned reranker + operation-aware policy)**:
      ranker-only change — no new candidates, no generation work, no
      new proof templates. A pure-Python logistic regression
      ([`src/mini_elf_lean/learned_reranker.py`](src/mini_elf_lean/learned_reranker.py))
      is trained per-family-LOFO on 1779 candidate rows
      (155 verified positives = 8.7%) drawn from v11/v12/v13/v14
      predictions + warm-rerun corrections. Features = 33 named
      pattern bits (intro / absurd / rw / cases / ⟨ / etc) +
      hashed char-3-grams + tactic-head one-hots + source bucket.
      The v15 audit shows that **rule and learned win disjoint
      operations** (rule dominates pass@1 on `instantiate_forall`/
      `rewrite`; learned dominates on `intro_negation` /
      exists-reconstruct's `unknown`). The v15 *policy*
      ([`src/mini_elf_lean/v15_rerank_policy.py`](src/mini_elf_lean/v15_rerank_policy.py))
      is an operation-aware router (with a learned-confidence
      fallback) that picks the right sub-scorer per row:
      **`neg_imp_exfalso` pass@5 0.200 → 0.800 (+0.600)** by
      routing `intro_negation` to the learned reranker; mean
      pass@5 lifts **0.765 → 0.885 (+0.120)**, mean pass@1
      **0.514 → 0.725 (+0.211)**, pass@10 preserved at the v14
      generator's ceiling 0.925. The residual
      `neg_imp_exfalso_ab` row stays at rank 6 — generator-bound,
      not reranker-bound. v12/v13/v14 metrics on disk untouched —
      [`docs/V15_LEARNED_RERANKER_REPORT.md`](docs/V15_LEARNED_RERANKER_REPORT.md) ·
      [`docs/V15_NEG_IMP_EXFALSO_RERANK_ANALYSIS.md`](docs/V15_NEG_IMP_EXFALSO_RERANK_ANALYSIS.md) ·
      [`docs/V15_FAILURE_EXAMPLES.md`](docs/V15_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v16 (contrapositive corpus augmentation + token
      seq2seq retrain)**: generator-side change — the v14 token
      architecture is retrained on +287 lean-cli-verified
      contrapositive examples (3 surface families:
      `contrapositive_classic`, `contrapositive_neg_imp`,
      `contrapositive_false_target`), produced by
      [`scripts/generate_v16_contrapositive_corpus.py`](scripts/generate_v16_contrapositive_corpus.py)
      with disjoint variable names and per-fold leakage guards.
      The v15 reranker / policy / learned model are unchanged.
      **Headline target hit:** `neg_imp_exfalso_ab` first-verified
      rank **6 → 0** (three verified candidates in top-5), taking
      `neg_imp_exfalso` pass@5 **0.200 → 1.000** (+0.800). Collateral
      gain on `neg_exfalso` pass@5 **0.625 → 0.875** as the model
      generalised the `(h hp).elim` form from the contrapositive
      corpus to a neighbouring shape. **Mean pass@5 0.765 → 0.975
      (+0.210); mean pass@1 0.514 → 0.875 (+0.361); mean pass@10
      0.925 → 0.975 (+0.050)** — the pass@10 lift is the strongest
      evidence v16 is a real generator change. All v15 wins
      preserved (forall_inst / rewrite_succ / exists_reconstruct
      stay at 1.000). v12 / v13 / v14 / v15 metrics on disk
      untouched; v16 publishes at parallel paths under
      `data/baselines/v16_token_seq2seq/` and
      `data/baselines/v16_policy_eval/` —
      [`docs/V16_GENERATOR_BOUND_FAILURE_AUDIT.md`](docs/V16_GENERATOR_BOUND_FAILURE_AUDIT.md) ·
      [`docs/V16_CONTRAPOSITIVE_AUGMENTATION_REPORT.md`](docs/V16_CONTRAPOSITIVE_AUGMENTATION_REPORT.md) ·
      [`docs/V16_FAILURE_EXAMPLES.md`](docs/V16_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v17 (arrow_false_elim corpus + policy edit)**:
      two targeted changes closing the final v16 pass@5 gap.
      (1) One-line policy edit moves `contradiction` from
      `USE_DEFAULT_RULE` to `USE_LEARNED` in
      [`src/mini_elf_lean/v15_rerank_policy.py`](src/mini_elf_lean/v15_rerank_policy.py) —
      under the v16 candidate distribution the learned reranker
      beats rule on `neg_exfalso` (the v15 tie broke), and under
      v17 candidates the gap widens further. (2) 137-row
      lean-cli-verified `arrow_false_elim` corpus
      ([`scripts/generate_v17_arrow_false_elim_corpus.py`](scripts/generate_v17_arrow_false_elim_corpus.py))
      teaches the `(h hp).elim` False-elimination shape, retrained
      v17 token model for `neg_exfalso` only (other folds use v16
      token model unchanged). **Headline result on the templated
      v11 family-LOFO benchmark**: `neg_exfalso_arrow_pq` first
      verified rank **— (no top-10) → 1** (verified candidate
      `exact absurd hp h` at rank 1; v17 corpus also taught the
      canonical `exact (h hp).elim` at rank 2). `neg_exfalso` pass@5
      **0.875 → 1.000**; mean pass@1 **0.875 → 0.950 (+0.075)**;
      **mean pass@5 0.975 → 1.000** and **mean pass@10 0.975 →
      1.000** on the templated benchmark. All v16 wins preserved.
      v12-v16 on-disk metrics untouched (v15/v16 policy-eval
      regenerated with the v17 routing; pass@5 pinned values
      unchanged). 96 new tests pin the headline +
      no-regression —
      [`docs/V17_RESIDUAL_FAILURE_AUDIT.md`](docs/V17_RESIDUAL_FAILURE_AUDIT.md) ·
      [`docs/V17_ARROW_FALSE_ELIM_REPORT.md`](docs/V17_ARROW_FALSE_ELIM_REPORT.md) ·
      [`docs/V17_FAILURE_EXAMPLES.md`](docs/V17_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v18 (broad-core transfer test)**: deliberately
      moves off the templated v11 LOFO corpus to measure how much
      of v17 transfers. 48-theorem hand-authored core-Lean
      benchmark spanning **10 categories** (implication /
      conjunction / disjunction / negation / equality_rewrite /
      exists / forall / nat_succ / bool / list); 109/115
      candidates lean-cli verified; Mathlib tier skipped honestly
      (env doesn't have Mathlib). **Honest headline: ~half of v17
      transfers.** v17 5-family panel + v17 policy reaches
      **pass@5 = 0.500**, **pass@10 = 0.583** on v18 (vs 1.000 on
      v17 templated). A single broad-synthetic token seq2seq
      (trained on the union of v11+v16+v17 corpora, 1151 rows)
      **beats the v17 panel** at every metric: **pass@1
      0.292→0.500**, **pass@5 0.500→0.583**, **pass@10
      0.583→0.604** — the v17 family-LOFO specialists were
      over-fit; broader training generalises better even on the
      same data. The wall is **categorical, not gradient**:
      `equality_rewrite` 1.000 / `conjunction` 0.833 / `negation`
      0.800 transfer cleanly; `implication` 0.000 and `bool` 0.000
      are **total misses** (no synthetic training for those
      shapes). Dominant failure class: **`unknown_identifier`**
      (~28 % of all candidates) — v17 references names that aren't
      bound in v18's diverse local contexts. v12–v17 metrics on
      disk untouched. **Not retconning v17**: v17 still closed the
      *templated* benchmark; v18 is the next wall —
      [`docs/V18_BENCHMARK_DESIGN.md`](docs/V18_BENCHMARK_DESIGN.md) ·
      [`docs/V18_BROAD_CORE_REPORT.md`](docs/V18_BROAD_CORE_REPORT.md) ·
      [`docs/V18_ZERO_SHOT_TRANSFER_REPORT.md`](docs/V18_ZERO_SHOT_TRANSFER_REPORT.md) ·
      [`docs/V18_FAILURE_EXAMPLES.md`](docs/V18_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v19 (state-aware identifier abstraction — honest
      negative result)**: hypothesised that replacing local
      identifier names with placeholders (`<HYP_IMP_0>`,
      `<HYP_PROP_0>`, etc.) would reduce v18's dominant
      `unknown_identifier` failure class. Implemented the full
      pipeline ([`src/mini_elf_lean/local_context.py`](src/mini_elf_lean/local_context.py)
      parser, [`src/mini_elf_lean/identifier_abstraction.py`](src/mini_elf_lean/identifier_abstraction.py)
      abstract/concretise with word-boundary + keyword protection,
      v19 abstract dataset from v11+v16+v17 corpora with 0
      round-trip failures, abstract token seq2seq trained to
      val_exact=0.26 vs v18 broad's 0.15). **Result: pass@k drops
      on v18.** v18 broad-synthetic+policy pass@5 = 0.583;
      v19 abstract-only+policy pass@5 = **0.208**;
      v19+broad ensemble pass@5 = **0.312**. The
      `unknown_identifier` class dropped (127 → ~30 slots), but a
      new `unresolved_placeholder` class arose at **210 / 480
      slots (44 %)** — worse exchange. Conjunction (0.83→0.17) and
      list (0.80→0.20) regressed sharply. Three root causes:
      (a) placeholder dropout against v18's local-context shapes,
      (b) dedup over-aggressive (3984 → 1111 rows), (c)
      abstraction is state-only, can't track tactic-introduced
      binders (`intro h` collapses with pre-existing `h`). v17 /
      v18 metrics on disk untouched. **Honest negative finding
      logged per the v19 brief's escape hatch.** Infrastructure is
      reusable for v20 (ranker-time abstraction) —
      [`docs/V19_IDENTIFIER_ABSTRACTION_REPORT.md`](docs/V19_IDENTIFIER_ABSTRACTION_REPORT.md) ·
      [`docs/V19_IMPLICATION_IDENTIFIER_ANALYSIS.md`](docs/V19_IMPLICATION_IDENTIFIER_ANALYSIS.md) ·
      [`docs/V19_BOOL_GAP_NOTE.md`](docs/V19_BOOL_GAP_NOTE.md) ·
      [`docs/V19_FAILURE_EXAMPLES.md`](docs/V19_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v20 (data-shape-gap closure + ranker-time
      abstraction)**: closed the two confirmed v18 data-shape gaps
      without v19's generation-time placeholder cliff. A shape-gap
      audit ([`scripts/audit_v20_shape_gaps.py`](scripts/audit_v20_shape_gaps.py))
      confirmed `bool` has **zero** training support (0 rows with
      `cases b`/`Bool`/`decide` across v11+v16+v17) and `implication`
      fails on **rank** not shape (the v17 contradiction pattern
      `exact (hpfalse hp).elim` displaces the bare `exact hp`). Two
      lean-cli-verified core-Lean corpora — **759/760** implication
      candidates (7 families) and **189/239** bool candidates (7
      families incl. `cases b <;> simp`) — feed a single **raw-name**
      broad-plus token seq2seq (same v14/v18 arch, 2099 rows, no
      placeholders). A **ranker-time** abstract-pattern reranker
      ([`src/mini_elf_lean/abstract_pattern_reranker.py`](src/mini_elf_lean/abstract_pattern_reranker.py))
      scores raw candidates by abstract-pattern frequency and
      penalises unbound identifiers — **never emitting placeholders**.
      **Result (timeout-corrected best config): implication
      0.000 → 1.000, bool 0.000 → 1.000, mean pass@1 0.500 → 0.625,
      pass@5 0.583 → 0.729, pass@10 0.604 → 0.729.** The pass@10 lift
      proves a real generator change; the abstract reranker is the
      single best config (pass@1 0.500 → 0.625) with **0
      unresolved-placeholder errors** (vs v19's 44 %). Honest negative:
      **forall regressed 0.667 → 0.000** (single-model capacity
      tradeoff from the implication-heavy corpus). A warm timeout-rerun
      ([`scripts/rerun_v20_timeouts.py`](scripts/rerun_v20_timeouts.py),
      v13/v14 precedent) flipped 9 spurious WSL timeouts to success;
      original metrics on disk untouched, corrected metrics in
      parallel. v18/v19 metrics unchanged. No state_after, no manual
      oracle, no Mathlib —
      [`docs/V20_SHAPE_GAP_AUDIT.md`](docs/V20_SHAPE_GAP_AUDIT.md) ·
      [`docs/V20_IMPLICATION_BOOL_CORPUS_REPORT.md`](docs/V20_IMPLICATION_BOOL_CORPUS_REPORT.md) ·
      [`docs/V20_BROAD_TRANSFER_REPORT.md`](docs/V20_BROAD_TRANSFER_REPORT.md) ·
      [`docs/V20_RANKER_TIME_ABSTRACTION_REPORT.md`](docs/V20_RANKER_TIME_ABSTRACTION_REPORT.md) ·
      [`docs/V20_FAILURE_EXAMPLES.md`](docs/V20_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v21 (forall-regression recovery via model routing)**:
      recovered the v20 forall regression (0.667 → 0.000 → **1.000**)
      while preserving every v20 gain. A regression audit
      ([`scripts/audit_v21_forall_regression.py`](scripts/audit_v21_forall_regression.py))
      proved the cause was a **single-model capacity tradeoff**: the
      948 implication+bool rows (45 % of the v20 pool) crowded the
      `exact h <arg>` instantiation schema **out of generation** (it
      was absent from the beam, not merely demoted — so no reranker
      could recover it). Built a 677/680 lean-cli-verified forall
      corpus (5 families) and compared four fixes: **A** v20 baseline,
      **B** single-retrain on v20+forall, **C** category **routing**
      (v20 broad-plus + a forall specialist via
      [`src/mini_elf_lean/v21_model_router.py`](src/mini_elf_lean/v21_model_router.py)),
      **D** higher-capacity (embed 128 / hidden 192). **All three fixes
      recover forall to 1.000 and keep implication/bool at 1.000**, but
      only **routing has zero collateral**: B relocated the tradeoff
      (disjunction 0.60→0.40, negation 0.80→0.60, exists 0.25→0.00),
      D mitigated it but still lost exists (→0.00). **Routing (C) is
      the winner: mean pass@1 0.625 → 0.688, pass@5 0.729 → 0.792,
      pass@10 0.729 → 0.792, every non-forall category identical to
      v20.** Conclusion: **routing > capacity > single-retrain**.
      Honest caveat: routing is composition-of-specialists (an
      engineering win on a category-separable benchmark), not a single
      model that generalizes across shapes. A safe non-destructive repo
      checkpoint was taken first (the repo is mid-paused-rebase;
      untouched). v18/v20 metrics unchanged; no state_after, no manual
      oracle, no Mathlib —
      [`docs/V21_REPO_CHECKPOINT.md`](docs/V21_REPO_CHECKPOINT.md) ·
      [`docs/V21_FORALL_REGRESSION_AUDIT.md`](docs/V21_FORALL_REGRESSION_AUDIT.md) ·
      [`docs/V21_FORALL_RECOVERY_REPORT.md`](docs/V21_FORALL_RECOVERY_REPORT.md) ·
      [`docs/V21_CAPACITY_TRADEOFF_ANALYSIS.md`](docs/V21_CAPACITY_TRADEOFF_ANALYSIS.md) ·
      [`docs/V21_FAILURE_EXAMPLES.md`](docs/V21_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v22 (single general model vs routing — the
      general-model question)**: answered v21's open question — **can ONE
      model serve all broad-core categories without the tradeoff?**
      **Yes.** Folded a **471/471 lean-cli-verified exists corpus** (6
      shape families) into the v21 pool and trained four single models
      (pool × capacity). The base model
      **`v22_general_plus_exists`** (one decoder, **no router**) **beats
      v21 routed** on every mean metric — pass@5 **0.792 → 0.812**,
      pass@10 **0.792 → 0.833**, MRR 0.728 → 0.774, no_verify 10 → 8 —
      while holding forall=implication=bool=1.000 and recovering **exists
      0.250 → 0.750**. Crucially, **oversampling and larger capacity did
      NOT help** (both regressed minor categories): the residual gap was a
      **data-shape coverage gap** (missing exists/forall shapes), not
      imbalance or capacity, so **routing is no longer necessary** — it
      was a proxy for that missing coverage. Honest residual: `negation`
      0.600 under the `abstract` reranker (0.800 under `raw`; pass@10
      confirms the candidate is in the beam; `v21_single_retrain` has the
      same 0.600 — not caused by exists). No state_after, no manual oracle,
      no Mathlib, no v10-leakage revival; v18/v20/v21 metrics unchanged —
      [`docs/V22_GENERAL_MODEL_REPORT.md`](docs/V22_GENERAL_MODEL_REPORT.md) ·
      [`docs/V22_CATEGORY_INTERFERENCE_ANALYSIS.md`](docs/V22_CATEGORY_INTERFERENCE_ANALYSIS.md) ·
      [`docs/V22_EXISTS_FAILURE_AUDIT.md`](docs/V22_EXISTS_FAILURE_AUDIT.md) ·
      [`docs/V22_FAILURE_EXAMPLES.md`](docs/V22_FAILURE_EXAMPLES.md) ·
      [`docs/V22_REPO_STATUS.md`](docs/V22_REPO_STATUS.md)
- [x] **Mini-ELF v23 (reranker refresh — ranking-only; honest negative
      vs raw)**: refreshed the reranker on a pooled 6,011-row v16–v22
      candidate-outcome dataset (new **grounding** features: unbound-
      identifier penalty + locally-bound-name awareness, abstract-pattern
      feature, category cues), **generator unchanged**, offline on the
      fixed v22 plus_exists pool, leave-one-theorem-out. Result: **no
      reranker beats `raw`** — the v22 generator's beam (pass@1 0.792,
      pass@5 0.833) is already best; the learned LR over-demotes (pass@1
      → 0.688), and the conservative **hybrid** recovers to 0.771 (net
      −1). v23 *does* beat the v22 `abstract` headline (hybrid pass@1
      0.729→0.771, pass@5 0.812→0.833, **negation 0.600→0.800**) — the
      negation regression was purely the abstract reranker, so **retire
      it**. The decisive finding: the residual gap is **generator-bound**
      (39/48 solved@1, **1** ranking-bound & feature-unfixable, **8**
      generator-bound with no verified candidate in the top-10) → **v24 =
      corpus augmentation**, not ranking. Ranker-time abstraction is
      scoring-only (never emits a placeholder); no state_after, no manual
      oracle, no Mathlib, no v10-leakage; v22 metrics unchanged —
      [`docs/V23_LEARNED_RERANKER_REFRESH_REPORT.md`](docs/V23_LEARNED_RERANKER_REFRESH_REPORT.md) ·
      [`docs/V23_NEGATION_RERANK_ANALYSIS.md`](docs/V23_NEGATION_RERANK_ANALYSIS.md) ·
      [`docs/V23_GENERATOR_BOUND_AUDIT.md`](docs/V23_GENERATOR_BOUND_AUDIT.md) ·
      [`docs/V23_RERANKER_DATA_AUDIT.md`](docs/V23_RERANKER_DATA_AUDIT.md) ·
      [`docs/V23_FAILURE_EXAMPLES.md`](docs/V23_FAILURE_EXAMPLES.md) ·
      [`docs/V23_REPO_STATUS.md`](docs/V23_REPO_STATUS.md)
- [x] **Mini-ELF v24 (residual shape augmentation — generator-bound
      fix)**: v23 proved the broad-core residual was generator-bound (8
      theorems with no verified candidate in the top-10). v24 added a
      **163/163 lean-verified core-Lean shape corpus** (8 families, one
      per failure) to the v22 pool and retrained the broad generator
      (no ranking work, no Mathlib). **Closed 5 of 8 generator-bound
      failures**: pass@10 **0.833 → 0.938** (no_verify **8 → 3**),
      pass@5 (abstract) **0.812 → 0.917**, pass@1 0.729 → **0.792**.
      Per-category (abstract): **negation 0.600 → 1.000, exists 0.750 →
      1.000, list 0.800 → 1.000, nat_succ 0.600 → 0.800**;
      forall/implication/bool/equality_rewrite stay 1.000; **zero category
      regressions**. The `abstract` reranker — *harmful* in v22 — is now
      v24's *best* config and recovers `neg_not_intro` (v23's
      ranking-unfixable theorem), because v24's candidates are grounded.
      3 disjunction/conjunction shapes remain (insufficient shape
      diversity → v25). core Lean only, no state_after, no manual oracle,
      no v10-leakage; v18/v22/v23 metrics unchanged —
      [`docs/V24_BROAD_GENERATOR_REPORT.md`](docs/V24_BROAD_GENERATOR_REPORT.md) ·
      [`docs/V24_RESIDUAL_ROW_RESULTS.md`](docs/V24_RESIDUAL_ROW_RESULTS.md) ·
      [`docs/V24_REGRESSION_ANALYSIS.md`](docs/V24_REGRESSION_ANALYSIS.md) ·
      [`docs/V24_RESIDUAL_CORPUS_REPORT.md`](docs/V24_RESIDUAL_CORPUS_REPORT.md) ·
      [`docs/V24_GENERATOR_BOUND_ROWS.md`](docs/V24_GENERATOR_BOUND_ROWS.md) ·
      [`docs/V24_FAILURE_EXAMPLES.md`](docs/V24_FAILURE_EXAMPLES.md) ·
      [`docs/V24_REPO_STATUS.md`](docs/V24_REPO_STATUS.md)
- [x] **Mini-ELF v25 (first Mathlib tier-C probe)**: Mathlib **v4.30.0**
      installs cleanly (external scratch project + olean cache auto-fetch,
      7.4 G) and imports — **no environment wall** (0 import-class failures).
      Built a **36-theorem / 103-candidate Mathlib-verified** tier-C benchmark
      (`lake env lean`, `import Mathlib`; 0 timeouts, 0 zero-success). **v24
      zero-shot transfer is bimodal**: pass@10 0.556 overall, but **0.812 on
      core-shaped** Mathlib goals vs **0.350 on Mathlib-lemma-needing** ones
      (all 5 Set goals unreachable). Wall = **generator coverage**
      (164 `unknown_identifier` + theorem-shape gaps), not tooling. A **tiny
      68-row verified Mathlib augmentation improves held-out transfer**
      (pass@10 0.571 → **0.786**, +3 theorems, 0 lost) **but regresses v18
      broad-core** (pass@10 0.938 → 0.833, protected `bool` 1.000 → 0.667) →
      **honest tradeoff; v24 stays the broad-core model, augmented model not
      adopted.** No state_after / manual oracle / v10-leakage; no
      full-theorem-proving claim; v24 metrics unchanged —
      [`docs/V25_MATHLIB_ENV_REPORT.md`](docs/V25_MATHLIB_ENV_REPORT.md) ·
      [`docs/V25_TIERC_CORPUS_REPORT.md`](docs/V25_TIERC_CORPUS_REPORT.md) ·
      [`docs/V25_ZERO_SHOT_TIERC_REPORT.md`](docs/V25_ZERO_SHOT_TIERC_REPORT.md) ·
      [`docs/V25_TIERC_AUGMENTATION_REPORT.md`](docs/V25_TIERC_AUGMENTATION_REPORT.md) ·
      [`docs/V25_BROADCORE_REGRESSION_REPORT.md`](docs/V25_BROADCORE_REGRESSION_REPORT.md) ·
      [`docs/V25_FAILURE_EXAMPLES.md`](docs/V25_FAILURE_EXAMPLES.md) ·
      [`docs/V25_REPO_STATUS.md`](docs/V25_REPO_STATUS.md)
- [x] **Mini-ELF v26 (Mathlib specialist + router — no broad-core
      cannibalisation)**: v25 established Mathlib availability + partial transfer
      and showed co-training **regresses broad-core**; v26 fixes this with a
      **separate Mathlib specialist + router**. Built a **237-row Mathlib-verified
      specialist corpus** (93 theorems, 6 categories, **54 Set / 37 order rows**)
      with a new **batched `import Mathlib` verifier** (direct v4.30.0 binary +
      precomputed `LEAN_PATH`, ~60× faster than v25; **gold-tested 0 mismatches
      vs one-example-per-file**). The **Mathlib-only specialist (`v26_base`)**
      lifts v25 held-out tier-C **pass@10 0.786 → 0.929** (fresh holdout 0.909);
      **Set goals (v24 = 0.00) → 0.50–1.00**, mathlib-lemma transfer 0.20 → 0.87.
      `plus_core` was *worse* (adopt pure-Mathlib); `large` unneeded. The
      **router** (`import Mathlib`/flag → specialist, else v24) **preserves
      broad-core** (routed p@5/p@10 = 0.938/0.958, `bool` 1.0) while lifting
      tier-C to 0.917 — vs v25 co-training's regressed 0.833. A **Set-shape
      widening pass** lifted held-out Set **0.50 → 0.75** with no other-category
      regression. Mathlib is real & external; no state_after / manual-oracle /
      v10-leakage; no full-proving claim; v24 model untouched —
      [`docs/V26_REPO_STATUS.md`](docs/V26_REPO_STATUS.md) ·
      [`docs/V26_MATHLIB_FAILURE_AUDIT.md`](docs/V26_MATHLIB_FAILURE_AUDIT.md) ·
      [`docs/V26_MATHLIB_SPECIALIST_CORPUS_REPORT.md`](docs/V26_MATHLIB_SPECIALIST_CORPUS_REPORT.md) ·
      [`docs/V26_MATHLIB_SPECIALIST_DATASET_REPORT.md`](docs/V26_MATHLIB_SPECIALIST_DATASET_REPORT.md) ·
      [`docs/V26_MATHLIB_SPECIALIST_EVAL_REPORT.md`](docs/V26_MATHLIB_SPECIALIST_EVAL_REPORT.md) ·
      [`docs/V26_ROUTED_SYSTEM_REPORT.md`](docs/V26_ROUTED_SYSTEM_REPORT.md) ·
      [`docs/V26_MATHLIB_CATEGORY_ANALYSIS.md`](docs/V26_MATHLIB_CATEGORY_ANALYSIS.md) ·
      [`docs/V26_FAILURE_EXAMPLES.md`](docs/V26_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v27 (scaled Mathlib specialist + hardened verifier)**: made the
      corrected verifier the trusted default and scaled the corpus. The canonical
      `TrustedMathlibVerifier` (sentinel + iterative success-confirmation +
      isolation **rescue**) is **sound *and* complete** vs a gold
      one-declaration-per-file reference — **0 false positives, matches gold
      exactly** (incl. 20 real candidates 14/14) — while a deliberately-unsafe
      **naive batched verifier shows 3 false positives** (reproduced with an
      unterminated block comment that makes the lexer skip a declaration). A
      corrected-metric re-audit showed every reported v25/v26 number reproduces
      **exactly**, and that the naive path *would have inflated* a weak baseline
      (v25_aug v26-holdout **0.636 → 0.727** via 8 gold-confirmed garbage proofs —
      gold agrees with trusted 8/8, naive 0/8). Added **181 verified rows** (87
      theorems; **Set 53, order 40 now first-class**); the
      **`v27_set_heavy`** specialist takes v25 held-out tier-C **pass@10 →
      1.000**, v26 holdout → **0.955**, **closes the Set residual 0.75 → 1.00**,
      order **1.00** (with training) / **0.90** (pure transfer). **Category
      balancing is harmful** for the gap category (Set → 0.50). The routed system
      keeps broad-core **bit-identical** (0.9375/0.9583, `bool` 1.0; v24 untouched)
      with tier-C **0.907** over 43 combined held-out theorems. Residuals are
      data-coverage-bound (lemma-vocabulary / API-arity), not architecture- or
      planning-bound. Mathlib real & external; no state_after / manual-oracle /
      v10-leakage; no full-proving claim; v24 model untouched; old naive verifier
      never used for headline metrics —
      [`docs/V27_REPO_STATUS.md`](docs/V27_REPO_STATUS.md) ·
      [`docs/V27_VERIFIER_SOUNDNESS_AUDIT.md`](docs/V27_VERIFIER_SOUNDNESS_AUDIT.md) ·
      [`docs/V27_CORRECTED_METRICS_AUDIT.md`](docs/V27_CORRECTED_METRICS_AUDIT.md) ·
      [`docs/V27_MATHLIB_CATEGORY_GAP_AUDIT.md`](docs/V27_MATHLIB_CATEGORY_GAP_AUDIT.md) ·
      [`docs/V27_MATHLIB_EXPANDED_CORPUS_REPORT.md`](docs/V27_MATHLIB_EXPANDED_CORPUS_REPORT.md) ·
      [`docs/V27_MATHLIB_SPECIALIST_DATASET_REPORT.md`](docs/V27_MATHLIB_SPECIALIST_DATASET_REPORT.md) ·
      [`docs/V27_MATHLIB_SPECIALIST_EVAL_REPORT.md`](docs/V27_MATHLIB_SPECIALIST_EVAL_REPORT.md) ·
      [`docs/V27_ROUTED_SYSTEM_REPORT.md`](docs/V27_ROUTED_SYSTEM_REPORT.md) ·
      [`docs/V27_DATA_SCALING_ANALYSIS.md`](docs/V27_DATA_SCALING_ANALYSIS.md) ·
      [`docs/V27_FAILURE_EXAMPLES.md`](docs/V27_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v28 (data-scaling breaks the fresh-holdout plateau + new Finset
      category)**: tested whether the v27 plateau (fresh-holdout pass@10 **0.714**)
      was data-volume bound — and broke it. The Part-1 audit diagnosed the v27
      residuals (`mem_inter_iff`, `union_subset`, …) as **sparse-sibling underfit**
      (the model lands in the right neighbourhood but mis-binds the identifier/shape
      when a family has 1–3 siblings), **not** an architecture wall. v28 densified
      each residual family with alpha-renamed siblings and added **new categories**:
      **Finset** (`[DecidableEq α]`), polymorphic order over
      `[Preorder]`/`[LinearOrder]`/`[Lattice]` (the v27 order skill was Nat-locked),
      function/logic. Corpus: **158 theorems → 350 verified rows, 0 true coverage
      gaps**, all trusted-verified; integrity re-check **350/350**, gold sample 24
      across all 7 categories **0 mismatches / 0 false positives**. The
      **`v28_general`** specialist preserves v25 held-out **pass@10 1.000** and v26
      **0.955**, and lifts the **fresh v27 holdout 0.714 → 0.857** (best v28 config
      **1.000**) and a **new 30-theorem v28 holdout to 0.867** (vs 0.667 for the best
      v27 model). The v27 residual `mem_inter_iff` is now solved **@ rank 0** via
      `simp [Set.mem_inter]`. New **Finset** category reaches **0.833** on held-out
      members. Routed broad-core stays **bit-identical** (0.9375/0.9583, v24
      untouched) with routed Mathlib tier **0.918** over 73 combined held-out
      theorems → router adoptable. **Category balancing again harmful** (v28 holdout
      0.700 vs general 0.867). Residuals remain **data/coverage-bound** (Finset
      projection direction, `le_antisymm`, renamed `comp_assoc`) — LeanDojo
      next-state supervision still premature. Mathlib real & external; no state_after
      / manual-oracle / v10-leakage; no full-proving claim; v24 untouched; naive
      verifier never used for headline metrics —
      [`docs/V28_REPO_STATUS.md`](docs/V28_REPO_STATUS.md) ·
      [`docs/V28_MATHLIB_RESIDUAL_AUDIT.md`](docs/V28_MATHLIB_RESIDUAL_AUDIT.md) ·
      [`docs/V28_EXPANDED_CORPUS_REPORT.md`](docs/V28_EXPANDED_CORPUS_REPORT.md) ·
      [`docs/V28_VERIFICATION_REPORT.md`](docs/V28_VERIFICATION_REPORT.md) ·
      [`docs/V28_DATASET_REPORT.md`](docs/V28_DATASET_REPORT.md) ·
      [`docs/V28_SPECIALIST_EVAL_REPORT.md`](docs/V28_SPECIALIST_EVAL_REPORT.md) ·
      [`docs/V28_ROUTED_SYSTEM_REPORT.md`](docs/V28_ROUTED_SYSTEM_REPORT.md) ·
      [`docs/V28_SCALING_PLATEAU_ANALYSIS.md`](docs/V28_SCALING_PLATEAU_ANALYSIS.md) ·
      [`docs/V28_FAILURE_EXAMPLES.md`](docs/V28_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v29 (sibling-density scaling + the density law)**: tested the v28
      hypothesis that improvement is driven by **within-family sibling density**, not
      generic category transfer — and quantified it. **The density law:** held-out
      pass@10 rises **0.68 → 0.83 → 0.94** with 0 → 1–3 → 4–6 training siblings
      (507 held-out evaluations); causally, the *same hard lemma-binding families*
      (set/finset projection·subset·membership) go from **0.16–0.26 at density 0**
      (whole-category transfer) to **0.70 at density ~6** (family-density holdout) —
      a 3–4× lift with family difficulty held fixed. v29 densified every sparse
      residual family to 7–16 verified siblings (var-set × proof-head menus): corpus
      **229 theorems → 492 verified rows, 0 coverage gaps**, all trusted-verified;
      integrity **492/492**, gold sample **32 across all 7 categories, 0 mismatches /
      0 false positives**. **`v29_general`** lifts the **fresh v28 holdout 0.867 →
      0.933** (`v29_set_finset_order_heavy` **0.967**), takes the **new v29 holdout to
      1.000** and **v26 to 1.000**, and **fixes** the v28 residuals `comp_assoc` and
      `antisymm`. **Routed broad-core preserved bit-for-bit (0.9375/0.9583, v24
      untouched → router adopted); routed Mathlib tier-C 0.921 over 140 held-outs**
      (up from v28's 0.918 on a larger, harder set). Honest trade: a **recoverable
      2/14 v25 micro-benchmark regression** (correct tactics fall out of the beam as
      the distribution shifts). **Whole-category transfer did not improve** (set/finset
      stay weak) → density is **within-family, not cross-category**; **balancing again
      unhelpful** (capping ≤ general; targeted *upsampling* helps). Residuals remain
      **single-tactic data-bound** (8 residuals, 0 multi-step) → LeanDojo next-state
      still premature. Mathlib real & external; trusted verifier only; no state_after /
      manual-oracle / v10-leakage; no full-proving claim; v24 untouched —
      [`docs/V29_REPO_STATUS.md`](docs/V29_REPO_STATUS.md) ·
      [`docs/V29_FAMILY_DENSITY_AUDIT.md`](docs/V29_FAMILY_DENSITY_AUDIT.md) ·
      [`docs/V29_SPARSE_RESIDUAL_AUDIT.md`](docs/V29_SPARSE_RESIDUAL_AUDIT.md) ·
      [`docs/V29_EXPANDED_CORPUS_REPORT.md`](docs/V29_EXPANDED_CORPUS_REPORT.md) ·
      [`docs/V29_VERIFICATION_REPORT.md`](docs/V29_VERIFICATION_REPORT.md) ·
      [`docs/V29_DATASET_REPORT.md`](docs/V29_DATASET_REPORT.md) ·
      [`docs/V29_SPECIALIST_EVAL_REPORT.md`](docs/V29_SPECIALIST_EVAL_REPORT.md) ·
      [`docs/V29_ROUTED_SYSTEM_REPORT.md`](docs/V29_ROUTED_SYSTEM_REPORT.md) ·
      [`docs/V29_DENSITY_LAW_ANALYSIS.md`](docs/V29_DENSITY_LAW_ANALYSIS.md) ·
      [`docs/V29_FAILURE_EXAMPLES.md`](docs/V29_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v30 (targeted density repair — recovered the v25 regression)**: used
      the v29 density law as an *actionable* construction rule for a **surgical** fix
      (no broad expansion). The Part-1 audit diagnosed the v29 v25 micro-regression
      (`nat_add_assoc`, `set_empty_subset`, pass@10 1.000→0.857) as
      **beam-absence + sparse-sibling** (correct tactic absent from the beam, family
      density 0). v30 densified only the 10 flagged low-density / residual families to
      4–6 siblings: corpus **69 theorems → 155 verified rows, 0 coverage gaps**, all
      trusted-verified; integrity **155/155**, gold sample **24 across 11 families, 0
      mismatches / 0 false positives** (0-mismatch invariant now holds v27→v30). The
      **`v30_general_targeted`** specialist **recovers v25 to 1.000** (both regressed
      theorems solved) **with zero regression** — and the repaired general model now
      *also* matches the heavy config (v26 1.000, v27 1.000, v28 0.967, v29 1.000).
      **Routed broad-core preserved bit-for-bit (0.9375/0.9583, v24 untouched → router
      adopted); routed tier-C pass@10 held at 0.921 over a larger, harder 165-theorem
      set.** Honest non-result: the `_3` projection **token-diversity** residuals did
      **not** repair (0.85→0.82) — held-out members use identifiers (`w`,`hw`) no
      sibling carries, a **coverage** limit refining the law (density helps only when
      the held-out member's surface tokens are in-distribution). Remaining failures
      still **single-tactic** (13, 0 multi-step) → LeanDojo next-state still premature.
      Upsampling/`targeted_only` ablations confirm **unweighted addition is best**; no
      category-balancing; no capacity probe; v24 audited-not-retrained. Trusted verifier
      only; no state_after / manual-oracle / v10-leakage; no full-proving claim —
      [`docs/V30_REPO_STATUS.md`](docs/V30_REPO_STATUS.md) ·
      [`docs/V30_V25_REGRESSION_AUDIT.md`](docs/V30_V25_REGRESSION_AUDIT.md) ·
      [`docs/V30_LOW_DENSITY_RESIDUAL_AUDIT.md`](docs/V30_LOW_DENSITY_RESIDUAL_AUDIT.md) ·
      [`docs/V30_TARGETED_DENSITY_CORPUS_REPORT.md`](docs/V30_TARGETED_DENSITY_CORPUS_REPORT.md) ·
      [`docs/V30_VERIFICATION_REPORT.md`](docs/V30_VERIFICATION_REPORT.md) ·
      [`docs/V30_DATASET_REPORT.md`](docs/V30_DATASET_REPORT.md) ·
      [`docs/V30_SPECIALIST_EVAL_REPORT.md`](docs/V30_SPECIALIST_EVAL_REPORT.md) ·
      [`docs/V30_ROUTED_SYSTEM_REPORT.md`](docs/V30_ROUTED_SYSTEM_REPORT.md) ·
      [`docs/V30_DENSITY_LAW_UPDATE.md`](docs/V30_DENSITY_LAW_UPDATE.md) ·
      [`docs/V30_FAILURE_EXAMPLES.md`](docs/V30_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v31 (token-coverage ceiling — safe identifier canonicalization)**:
      attacked the v30 token-coverage ceiling (held-out members using identifiers like
      `hw`/`hm`/`g` that no training sibling carried). The Part-1 audit showed **all 13
      v30 residuals are surface-token OOD** (the proof shape is in training; only the
      identifier differs) — raw memorization, not an API/shape gap. v31 built a **safe
      identifier-canonicalization** module that — unlike the documented v19 placeholder
      failure (which replaced `unknown_identifier` with a dominant
      `unresolved_placeholder` and dropped pass@k) — uses **valid Lean canonical names**
      (`c0,c1,…`), **unions concretized candidates with the raw v30 pool** (raw fallback,
      never replacement), and **rejects unmapped slots before the verifier**. Result:
      **`v31_canonical_general` lifts the 13-residual token-diversity holdout 0.00 →
      0.92** and the v30 targeted-family holdout 0.60 → 1.00, **with every standard
      held-out at 1.000** (v25/v26/v27/v29) and v28 lifted 0.967 → 1.000 — adding **zero
      new theorems** (the v30 base re-encoded). **Routed broad-core preserved bit-for-bit
      (0.9375/0.9583, v24 untouched → adopted); routed tier-C pass@10 jumps 0.921 →
      0.985** over 131 held-outs. The v19 failure mode did **not** recur: 0 unresolved on
      the main eval, 11/1267 (0.9 %) safely dropped in routing. Residuals **13 → 1** (the
      lone miss is a sparse *shape* `∅∩s⊆t`, a density gap, not token-coverage; 0
      multi-step → LeanDojo still premature). A verified **rename-augmentation** fallback
      (140 rows) independently reached 0.77. **Refined two-axis law: single-tactic
      success needs family density AND surface-token coverage.** Trusted verifier only;
      **not v19 placeholders**; no state_after / manual-oracle / v10-leakage; no
      full-proving claim; v24 untouched —
      [`docs/V31_REPO_STATUS.md`](docs/V31_REPO_STATUS.md) ·
      [`docs/V31_TOKEN_COVERAGE_AUDIT.md`](docs/V31_TOKEN_COVERAGE_AUDIT.md) ·
      [`docs/V31_IDENTIFIER_NORMALIZATION_DESIGN.md`](docs/V31_IDENTIFIER_NORMALIZATION_DESIGN.md) ·
      [`docs/V31_CANONICAL_DATASET_REPORT.md`](docs/V31_CANONICAL_DATASET_REPORT.md) ·
      [`docs/V31_PROJECTION_RENAME_AUG_REPORT.md`](docs/V31_PROJECTION_RENAME_AUG_REPORT.md) ·
      [`docs/V31_NORMALIZED_SPECIALIST_EVAL_REPORT.md`](docs/V31_NORMALIZED_SPECIALIST_EVAL_REPORT.md) ·
      [`docs/V31_ROUTED_SYSTEM_REPORT.md`](docs/V31_ROUTED_SYSTEM_REPORT.md) ·
      [`docs/V31_DENSITY_VS_TOKEN_COVERAGE.md`](docs/V31_DENSITY_VS_TOKEN_COVERAGE.md) ·
      [`docs/V31_FAILURE_EXAMPLES.md`](docs/V31_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v32 (robustness stress-test + saturation decision)**: stress-tested
      v31's canonicalization, closed/characterized the final residual, and decided
      whether the single-tactic Mathlib tier is saturated. **The decisive finding:
      canonicalization GENERALIZES, augmentation does not** — on a **46-theorem
      adversarial identifier benchmark** (never-seen names `h_mem`/`proof₁`/`hα`/
      `φψχ`/`A,B,obj`), raw v30 = **0.261**, rename-augmentation = 0.283 (it only
      memorized the specific v30 residual identifiers), but **canonicalization = 0.891**
      — a 3.4× lift proving real identifier-invariance, not a patch. The final residual
      (`∅∩s⊆t`) was Lean-probed as **single-tactic** (`simp` closes it) and repaired with
      **37 verified `∅∩` siblings**. A **25-theorem fresh-shape micro-holdout** scored
      0.76–0.80 (the remaining axis is shape/density, not token coverage). **Routed
      broad-core preserved bit-for-bit (0.9375/0.9583, v24 untouched → adopted); routed
      tier-C 0.950 over the hardest 202-theorem benchmark to date** (adds the adversarial
      + fresh theorems). The v19 guard handled adversarial input safely (2.8–8.5 %
      unresolved, all dropped before the verifier). **Saturation verdict: robust but not
      fully saturated** (adversarial 0.89 < 0.95, fresh 0.80 < 0.85); **11 residuals, all
      single-tactic, 0 multi-step → LeanDojo next-state still premature** (and forbidden
      by constraint absent a multi-step failure). **v33 = one more single-tactic
      coverage/robustness pass** (harden canonical decode for Greek/subscript; add fresh
      order/set shapes), then package. Trusted verifier only; not v19 placeholders; no
      state_after / manual-oracle / v10-leakage; no full-proving claim; v24 untouched —
      [`docs/V32_REPO_STATUS.md`](docs/V32_REPO_STATUS.md) ·
      [`docs/V32_FINAL_RESIDUAL_AUDIT.md`](docs/V32_FINAL_RESIDUAL_AUDIT.md) ·
      [`docs/V32_FINAL_RESIDUAL_REPAIR_REPORT.md`](docs/V32_FINAL_RESIDUAL_REPAIR_REPORT.md) ·
      [`docs/V32_IDENTIFIER_STRESS_BENCHMARK.md`](docs/V32_IDENTIFIER_STRESS_BENCHMARK.md) ·
      [`docs/V32_IDENTIFIER_STRESS_EVAL_REPORT.md`](docs/V32_IDENTIFIER_STRESS_EVAL_REPORT.md) ·
      [`docs/V32_FRESH_MATHLIB_HOLDOUT.md`](docs/V32_FRESH_MATHLIB_HOLDOUT.md) ·
      [`docs/V32_ROUTED_SYSTEM_REPORT.md`](docs/V32_ROUTED_SYSTEM_REPORT.md) ·
      [`docs/V32_SATURATION_ANALYSIS.md`](docs/V32_SATURATION_ANALYSIS.md) ·
      [`docs/V32_FAILURE_EXAMPLES.md`](docs/V32_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v33 (final single-tactic robustness pass — tier SATURATED)**: ran the
      last targeted coverage/robustness pass over the 11 v32 residuals and decided the
      single-tactic Mathlib tier is saturated. The audit found **all 11 residuals
      single-tactic, 0 multi-step**: 5 were a **parser-coverage bug** (the subscript
      identifier `proof₁` wasn't recognized as a binder, so the canonical decode rejected
      it), 6 were fresh shape/vocabulary gaps. v33 (a) **hardened the canonical decode**
      (subscript/Greek identifiers `proof₁`/`h₂`/`hα`/`f¹` now parse — additive, all
      v31/v32 tests still pass) and (b) added an **83-row residual-coverage corpus**
      (`inter_assoc`/`le_trans`-chains/`min·max·inf_comm`/`∅∩`). **Result: every
      single-tactic bench hits pass@10 1.00** — v25/v28/v29 1.00, token-diversity 1.00,
      **adversarial identifier-stress 1.00** (the parser fix alone lifted *every*
      canonical model 0.891→1.00, proving the v32 0.89 was a parser bug not a model
      limit), **fresh-robustness (42 new theorems) 1.00**, **0 residuals**. **Routed
      broad-core preserved bit-for-bit (0.9375/0.9583, v24 untouched → adopted); routed
      tier-C pass@10 0.992 over the hardest 244-theorem set** (order 0.89→1.00). v19
      guard safe (2.7 % unresolved dropped). **Saturation verdict: the single-tactic
      Mathlib tier is saturated; 0 multi-step → LeanDojo next-state stays deferred; v34 =
      packaging / paper-style report / git recovery.** Trusted verifier only; not v19
      placeholders; no state_after / manual-oracle / v10-leakage; no full-proving claim;
      v24 untouched —
      [`docs/V33_REPO_STATUS.md`](docs/V33_REPO_STATUS.md) ·
      [`docs/V33_REMAINING_RESIDUAL_AUDIT.md`](docs/V33_REMAINING_RESIDUAL_AUDIT.md) ·
      [`docs/V33_RESIDUAL_COVERAGE_CORPUS_REPORT.md`](docs/V33_RESIDUAL_COVERAGE_CORPUS_REPORT.md) ·
      [`docs/V33_FRESH_ROBUSTNESS_HOLDOUT.md`](docs/V33_FRESH_ROBUSTNESS_HOLDOUT.md) ·
      [`docs/V33_DATASET_REPORT.md`](docs/V33_DATASET_REPORT.md) ·
      [`docs/V33_SPECIALIST_EVAL_REPORT.md`](docs/V33_SPECIALIST_EVAL_REPORT.md) ·
      [`docs/V33_ROUTED_SYSTEM_REPORT.md`](docs/V33_ROUTED_SYSTEM_REPORT.md) ·
      [`docs/V33_SINGLE_TACTIC_SATURATION_ANALYSIS.md`](docs/V33_SINGLE_TACTIC_SATURATION_ANALYSIS.md) ·
      [`docs/V33_FAILURE_EXAMPLES.md`](docs/V33_FAILURE_EXAMPLES.md)
- [x] **Mini-ELF v34 (packaging + git recovery — COMPLETE)**: stopped modeling and
      packaged the project. **Git recovery**: a stale `.git/rebase-merge/` from 2026-05-28
      (orphaned `git pull --rebase` stopped on conflicts; work then continued on another
      branch) was cleared with **`git rebase --quit`** (not abort/reset) after a full `.git`
      backup — `HEAD` (`b4fcd6c`) and `main` (`a691b63`) unchanged, all v25–v33 artifacts
      intact. Wrote a consolidated **paper-style final report**, an **artifact inventory**
      (v24→v33), a **reproducibility** doc, and a **commit plan** (not committed). Framing
      held: theorem-level (single-tactic) verification, **trusted verifier + router**, **no**
      full-proving claim, **no** state_after, **no** LeanDojo next-state (0 multi-step
      residuals) —
      [`docs/MINI_ELF_MATHLIB_FINAL_REPORT.md`](docs/MINI_ELF_MATHLIB_FINAL_REPORT.md) ·
      [`docs/V34_GIT_RECOVERY_PLAN.md`](docs/V34_GIT_RECOVERY_PLAN.md) ·
      [`docs/V34_ARTIFACT_INVENTORY.md`](docs/V34_ARTIFACT_INVENTORY.md) ·
      [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md) ·
      [`docs/V34_CONSISTENCY_AUDIT.md`](docs/V34_CONSISTENCY_AUDIT.md) ·
      [`docs/V34_COMMIT_PLAN.md`](docs/V34_COMMIT_PLAN.md)
- [ ] Real next-state supervision (needs LeanDojo `run_tac` unblock; deferred — 0 multi-step residuals)
- [ ] Full ELF embedded-flow research target (v0/v1 are small prototypes, not the method)

## Headline result

**Mini-ELF v1 (rerank+witness) reaches test `pass@1` 0.89 and `pass@5` 0.95 — a
*generative* model that beats AR (0.76 / 0.82) on precision *and* recall.** A
learned **verifier-aware reranker** (trained on past Lean outcomes + v1's own
flow candidates self-labelled by Lean) lifts the decoder's top-1 from 0.66→0.89
and cuts the top-1 invalid rate from 0.34→0.11; a symbolic **witness-copy**
augmenter solves `∃`-witness goals (`exact ⟨5, rfl⟩`) for **`novel_verified`
10 (val) / 2 (test)** vs v0's 0; and the reranker's structure features make v1
the **first model to crack the relational siblings** `and_elim` / `or_intro`
(top-1 family accuracy 0.00 → 1.00).

Tactic prediction on the 134-theorem corpus, theorem-level split (val/test ≈ 16
theorems each), scored by **lean-cli pass@k**:

| model | val pass@1 | test pass@1 | val pass@5 | test pass@5 |
| --- | --- | --- | --- | --- |
| majority | 0.08 | 0.16 | 0.16 | 0.16 |
| retrieval (char-n-gram) | 0.22 | 0.16 | 0.22 | 0.32 |
| log-linear classifier | 0.46 | 0.55 | 0.65 | 0.76 |
| AR seq2seq (generative) | 0.70 | 0.76 | 0.78 | 0.82 |
| Mini-ELF v0 (flow, decoder) | 0.51 | 0.61 | 0.84 | 0.89 |
| Mini-ELF v0 (flow, nn-decode) | 0.65 | 0.76 | 0.89 | **1.00** |
| **Mini-ELF v1 (rerank)** | **0.89** | **0.89** | 0.89 | 0.89 |
| **Mini-ELF v1 (rerank+witness)** | **0.89** | **0.89** | **1.00** | **0.95** |

Mini-ELF v1 closes v0's precision gap: the **reranker** supplies top-1 precision
(the raw flow decoder's frequency-ranked top-1 is *noisier* than v0; the reranker
is what delivers `pass@1` 0.89), while **witness-copy** restores recall on `∃`
goals and adds verifiable novelty. The v0 `nn-decode` row still tops `pass@5`
(test 1.00) but is latent-space *retrieval*, not generation; v1 `rerank+witness`
matches it (test 0.95) while generating open-vocabulary tactics. Honesty:
witness-copy is **symbolic** augmentation (copying literals into a template),
`exists_witness` is solved at `pass@5` not `pass@1`, and 16–17 eval
theorems/split makes this directional, not statistically powered — see the
[project report](docs/PROJECT_REPORT.md).

> **Mini-ELF v2 reality check (generalization).** Those v1 numbers are on a small,
> **templated** corpus. v2 builds a harder 94-theorem corpus + adversarial /
> family / difficulty splits and finds v1 **does not transfer**: under
> distribution shift the learned generator+reranker collapse to `pass@5`
> 0.00–0.23 (only the *symbolic* witness-copy survives). Retraining on the
> combined corpus (v2) recovers in-distribution-hard (`pass@5` 0.23 → **1.00**)
> and partially recovers adversarial siblings (0.11 → 0.53), but achieves **no**
> compositional generalization (difficulty-holdout stuck at 0.06) and **regresses**
> the basic corpus (0.95 → 0.82). Full study:
> [`docs/V2_GENERALIZATION_REPORT.md`](docs/V2_GENERALIZATION_REPORT.md).

> **Mini-ELF v3 (structured proof-block planner).** v3 adds a deterministic
> *symbolic* planner that parses the goal and **constructs** proof blocks
> (implication chains `h3 (h2 (h1 h))`, nested conjunction projection `h.2.2`,
> `cases`/`rcases` splits, iff `.mp/.mpr` and equality `.trans/.symm` chains),
> fused above the v2 flow generator + reranker + witness-copy. It moves the
> compositional `difficulty_holdout` `pass@5` **0.06 → 1.00**, recovers
> adversarial siblings (0.53 → **1.00**), keeps hash at 1.00, and **recovers the
> basic regression** (0.82 → **1.00**) — a uniform win. A `--no-planner`
> ablation on the same split/model stays at **0.083**, attributing the entire
> lift to the planner. **Honesty:** this is *engineered symbolic coverage* of
> the corpus's proof shapes, **not** learned generalization — on a proof shape
> with no matching template the planner would fail like v1/v2; every planner
> candidate that reached the top-5 verified. Full report:
> [`docs/V3_PROOF_PLANNER_REPORT.md`](docs/V3_PROOF_PLANNER_REPORT.md).
>
> | split | v1-transfer | v2 | **v3** pass@5 |
> | --- | --- | --- | --- |
> | hard difficulty_holdout (compositional) | 0.06 | 0.06 | **1.00** |
> | hard adversarial_sibling | 0.11 | 0.53 | **1.00** |
> | hard hash | 0.23 | 1.00 | **1.00** |
> | basic test | 0.95 | 0.82 | **1.00** |

> **Mini-ELF v4 (planner-blind benchmark) — the saturation is not robustness.**
> v3's wins are *engineered symbolic coverage*, so v4 builds a 61-theorem corpus
> of proof shapes the planner provably cannot construct (negation/contradiction,
> contrapositive, ∃-elimination, ∀-instantiation, rewrite). On it, **every
> unchanged system collapses**: AR `pass@5` 0.00, v1/v2/v3 all **0.096** (the v3
> planner verifies *0* candidates; only the witness-copy shortcut survives, on
> one family). A controlled, explicitly-labelled template-addition ablation then
> shows pure **whack-a-mole**: adding negation templates → those 5 families jump
> to 1.00 (global 0.61), adding ∃-elim → those 2 jump to 1.00 (global 0.31), both
> → 0.83 — but `forall_inst` and `rewrite_succ`, for which **no** template was
> added, stay at **0.00**. Symbolic coverage is per-shape and never complete.
> Full report: [`docs/V4_PLANNER_BLIND_REPORT.md`](docs/V4_PLANNER_BLIND_REPORT.md).

> **Mini-ELF v5 (data-driven proposers) — off whack-a-mole, on the targets.**
> v4 left `forall_inst` / `rewrite_succ` at 0.00 even with both hand-written
> template sets. v5 adds a common candidate-**proposer** interface and a
> train-free **retrieval** proposer (retrieve verified blocks by char-n-gram
> similarity, then *lightly adapt* — numeric-literal substitution for
> ∀-instantiation, verbatim reuse for the rest). On a within-family split
> (`family_interpolation`: each family has held-out test theorems + same-family
> donors, no leakage), retrieval takes **`forall_inst` and `rewrite_succ` to
> pass@5 1.00 with no template** — the exact families templates could not reach —
> while v3 stays at 0.107 and v4-templates at 0.821 (still 0.00 on the targets).
> Combining them (`v3 + v4-tmpl ⊕ retrieval`) reaches **pass@5 1.00** overall:
> the template and the proposer are *complementary*. **Honesty:** retrieval is
> example reuse + adaptation, **not** reasoning; it needs same-family donors, and
> char-similarity still confuses the negation siblings (`neg_exfalso` 0.00) — the
> v1 sibling-confusion problem at the retrieval layer. The **LLM** pilot is
> implemented but **gated on an API key** (skipped here, not faked); a learned
> seq2seq proposer is deferred to v6. Full report:
> [`docs/V5_RESULTS_SUMMARY.md`](docs/V5_RESULTS_SUMMARY.md) ·
> [`docs/V5_TARGET_FAMILIES.md`](docs/V5_TARGET_FAMILIES.md) ·
> [`docs/V5_FAILURE_EXAMPLES.md`](docs/V5_FAILURE_EXAMPLES.md).
>
> | config (split test, n=32) | pass@5 | forall_inst@5 | rewrite_succ@5 |
> | --- | --- | --- | --- |
> | v3 (unchanged) | 0.107 | 0.00 | 0.00 |
> | v4 templates (both, labelled) | 0.821 | **0.00** | **0.00** |
> | **retrieval (alone, no template)** | 0.595 | **1.00** | **1.00** |
> | v3 + v4-tmpl ⊕ retrieval | **1.00** | 1.00 | 1.00 |

> **Mini-ELF v6 (structure-aware retrieval) — fixing v5's ranking, not its
> reasoning.** v5 retrieval solved the targets at `pass@5` but ranked by
> char-similarity alone, mis-ranking siblings (`forall_inst` pass@1 0.00,
> `neg_exfalso` 0.00, `exists_elim_conj` 0.25). v6 adds heuristic **structural**
> features (`retrieval_features.py`: goal shape, hypothesis shapes, a guessed
> `required_operation`, left/right conjunct position, connective overlap) and
> re-scores the *same* retrieved candidates — plus an adapted-candidate
> preference (rank `exact h 13` above the stale verbatim `exact h 3`, goal-LHS
> first). On the same split, **retrieval-alone goes from pass@1 0.357 → 1.000 and
> pass@5 0.595 → 1.000**, fixing all four v5 failures (`forall_inst` pass@1
> **0.00 → 1.00**; `exists_elim_conj` `pass@5` 0.25 → 1.00; `neg_exfalso` /
> `neg_imp_exfalso` 0.00 → 1.00). A `no-structural` ablation collapses back to
> ~v5, isolating the structural terms as the cause. **Honesty:** v6 changes
> *ranking only* — no proof templates, no `state_after`, no LLM; it is still
> example reuse, and in *fusion* v3's unfixed `∃, ∧` planner mis-parse still drags
> `exists_elim_conj` top-1 (retrieval-alone is the cleaner source). Report:
> [`docs/V6_STRUCTURE_AWARE_RETRIEVAL_REPORT.md`](docs/V6_STRUCTURE_AWARE_RETRIEVAL_REPORT.md) ·
> [`docs/V6_RETRIEVAL_FAILURE_ANALYSIS.md`](docs/V6_RETRIEVAL_FAILURE_ANALYSIS.md) ·
> [`docs/V6_FAILURE_EXAMPLES.md`](docs/V6_FAILURE_EXAMPLES.md).
>
> | config (split test, n=32) | pass@1 | pass@5 | forall_inst@1 | neg_exfalso@5 |
> | --- | --- | --- | --- | --- |
> | v5 retrieval (char-sim) | 0.357 | 0.595 | 0.00 | 0.00 |
> | **v6 retrieval (structure-aware)** | **1.000** | **1.000** | **1.00** | **1.00** |
> | v6 retrieval — no structural (ablation) | 0.393 | 0.595 | 1.00 | 0.00 |

> **Mini-ELF v7 (retrieval under donor scarcity) — what v6's 1.00 actually
> measured.** v6's split is `family_interpolation`: every test family also has
> members in train, so retrieval reuses a *same-family* donor. v7 builds a graded
> donor-scarcity benchmark and re-measures with real lean-cli. ⚠️ **These holdout
> numbers are not comparable to v6's interpolation 1.00 — a harder regime by
> design.** Findings: (1) v6's rank-0 donor is same-family **100%** of the time and
> forbidding same-family donors on the *same* split drops pass@5 **1.00 → 0.00**;
> (2) genuine `family_holdout` and `operation_holdout` collapse **every** config
> (v5, v6, and a template-free abstraction re-ranker) to **0.00**, with
> `cross_family_verified = 0` everywhere — the wall is **donor coverage**, not
> ranking; (3) the determinant is the *presence vs. absence* of a same-family
> donor, not its quantity (1-shot `kshot_1` ≈ 0.91; 0-shot = 0.00); (4) role-based
> **re-concretisation** (abstract a donor tactic to hypothesis roles, re-bind to
> the target) helps only the scarce regime (`kshot_1` pass@1 0.832 → **0.924**),
> all *same-family*. Tiny learned scorer **skipped** (no learnable headroom).
> Report: [`docs/V7_RETRIEVAL_HOLDOUT_REPORT.md`](docs/V7_RETRIEVAL_HOLDOUT_REPORT.md) ·
> audit [`docs/V7_DONOR_AVAILABILITY_AUDIT.md`](docs/V7_DONOR_AVAILABILITY_AUDIT.md) ·
> examples [`docs/V7_FAILURE_EXAMPLES.md`](docs/V7_FAILURE_EXAMPLES.md).
>
> | split (lean-cli pass@5) | donor condition | v5 | v6 | v7_abstract |
> | --- | --- | --- | --- | --- |
> | `current` (interpolation) | abundant same-family | 0.595 | **1.000** | 1.000 |
> | `kshot_1` | 1 same-family donor | — | 0.908 | **0.939** |
> | `family_holdout` | **no same-family donor** | 0.000 | **0.000** | 0.000 |
> | `operation_holdout` | **no same-operation donor** | 0.000 | **0.000** | 0.000 |

> **Mini-ELF v8 (generative donorless proposer) — first non-zero on the v7 wall.**
> v7 showed retrieval *cannot* clear donorless rows. v8 trains a CPU-only
> char-level seq2seq proposer on a pooled basic + hard + planner_blind corpus
> (690 verified rows, theorem-level lean-cli only, no `state_after`) and
> re-measures on the v7 donorless target sets. **On `family_holdout/neg_exfalso`
> the seq2seq verifies 5 of 8 held theorems** (pass@5 = **0.625** vs v7's 0.00),
> emitting **9 novel verified tactic strings** (e.g. `exact absurd hp hnp`,
> `exact (hnp hp).elim`) that are *not* in the train tactic pool — the model
> composes the token `absurd` and the hypothesis names `hp` / `hnp` from
> sibling negation families in train. **This is the project's first non-zero
> `cross_family_verified` on a v7 holdout regime — v7's wall is broken when
> sibling families share tokens in train.** Negative control:
> `family_holdout/forall_inst`, whose flat tactic `exact h N` is unique to its
> family with no shape-compatible cousin in train, stays at **0/7** — the
> mechanism is *composing tokens learned from sibling families*, not abstract
> generalisation. On the harder `donorless_eval` regime (no PB families in train
> at all) the model verifies 3 of 61 via training-distribution slot fill in
> `exists_reconstruct` (the only family whose `⟨N, rfl⟩` shape overlaps the
> basic-corpus `exists_witness` set). The **LLM** pilot is implemented but
> **skipped honestly** (no `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in env) —
> written up in `docs/V8_LLM_DONORLESS_PILOT_SKIPPED.md`, not faked as a zero.
> Full details: [`docs/V8_GENERATIVE_PROPOSER_REPORT.md`](docs/V8_GENERATIVE_PROPOSER_REPORT.md) ·
> targets [`docs/V8_DONORLESS_TARGETS.md`](docs/V8_DONORLESS_TARGETS.md) ·
> failure examples [`docs/V8_FAILURE_EXAMPLES.md`](docs/V8_FAILURE_EXAMPLES.md).
>
> | regime (lean-cli pass@5) | donor / sibling condition | v7 retrieval | **v8 seq2seq** | novel | xfam | xop |
> | --- | --- | ---: | ---: | ---: | ---: | ---: |
> | `family_holdout/neg_exfalso` | siblings (other neg_*) in train | 0.00 | **0.625** | **9** | **9** | 0 |
> | `family_holdout/exists_reconstruct` | basic exists_witness in train | 0.00 | 0.400 | 0 | 2 | 0 |
> | `operation_holdout/intro_negation` | *operation* absent, sibling-op tokens present | 0.00 | **0.125** (pass@10 = 0.188) | **3** | 3 | **3** |
> | `operation_holdout/contradiction` | operation absent, sibling-op tokens present | 0.00 | 0.000 (pass@10 = 0.071) | 1 | 1 | 1 |
> | `family_holdout/forall_inst` | no shape-compatible sibling | 0.00 | 0.000 | 0 | 0 | 0 |
> | `donorless_eval` (basic+hard only) | no PB family in train | (n/a) | 0.033 | 0 | 3 | 0 |
>
> Final v8 eval matrix: 5 regimes verified at least one cross-family/cross-operation candidate
> (15 verified candidates total, 13 novel); 10 regimes confirmed at 0/n where the held shape
> has no token-compatible cousin in train. `operation_holdout/project_conjunction` (84 test rows)
> hit the 15-min per-fold timeout and is marked `—` in the matrix doc, not faked as `0.000`.

## Backend status

| Lean backend | status |
| --- | --- |
| `mock` | **working** (no Lean needed; pipeline tests only — not real verification) |
| `lean-cli` | **working on Windows** and Unix; real whole-file Lean verification (theorem-level, no intermediate states) |
| `leandojo` | **partially working** under WSL2: tracing + `runner.start()` return a real initial `TacticState`; **`Dojo.run_tac` is `xfail`** because of a Lean-toolchain elaboration-stdin limitation — see [`docs/LEANDOJO_SETUP.md`](docs/LEANDOJO_SETUP.md) §8 |

### LeanDojo live-run blocker (2026-05-27)

On Lean 4.20.0 *and* 4.30.0 in WSL2 Ubuntu, `lake env lean file.lean` runs
theorem-body elaboration with an empty/EOF stdin (the same documented
limitation as `#eval`), so LeanDojo's `lean_dojo_repl` elab tactic crashes on
its first `IO.getStdin.getLine` with `[fatal] failed to parse JSON offset 0:
unexpected end of input`. The Python `Dojo._read_next_line` still scrapes the
init `REPL>` line, so `runner.start()` returns a real `TacticState`; the first
`runner.run_tactic(state0, tactic)` then surfaces `DojoCrashError: Unexpected
EOF` with a hint that points back at the doc. Disabling `Elab.async` does not
help. Five reproducers live in `scripts/` and a full walk-through is in
`docs/LEANDOJO_SETUP.md` §8.

The `LeanDojoRunner` API contract is correct (`Dojo.run_tac(state, tactic)`
signature confirmed via `inspect`; mocked tests in
`tests/test_leandojo_runner_real_api.py` pin the real attribute names —
including `ProofFinished.tactic_state_id`). `tests/test_leandojo_smoke_real.py`
is marked `xfail(strict=True)` so a future Lean release that restores
elaboration-time stdin will XPASS loudly and we'll flip it back to a hard
assertion.

Candidate sources: `mock` and `manual-file` work everywhere with no key;
`anthropic` / `openai` are optional real LLMs.

**On native Windows?** `mock`, `manual-file`, and `lean-cli` all work directly.
For a real `leandojo` run, use WSL2 — the turnkey steps live in
[`docs/LEANDOJO_SETUP.md`](docs/LEANDOJO_SETUP.md) §1a. Quickest path:

```bash
# inside Ubuntu (WSL2), project copied into the Linux filesystem (~/code/ELFMath):
python3 -m venv .venv && source .venv/bin/activate && pip install -e .[dev]
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh -s -- -y
pip install lean-dojo && export GITHUB_ACCESS_TOKEN=ghp_xxx
# publish examples/leandojo_mini_repo, fill its commit into data/seeds/leandojo_seeds.jsonl, then:
MINI_ELF_LEANDOJO_SMOKE=1 pytest tests/test_leandojo_smoke_real.py -q
```

A manual GitHub Actions workflow (`.github/workflows/leandojo-smoke.yml`,
`workflow_dispatch` only) can run the same smoke test on `ubuntu-latest`.

## 1. Motivation

The eventual research goal is to test whether ELF-style *continuous embedded
flow* generation ([Mini-ELF](https://openreview.net/pdf?id=tnx1VvrcAn)) can
generate Lean tactics or tactic blocks. **This stage is not modeling.** Before
any model exists, we need a robust verifier-filtered dataset pipeline — training
before having a clean dataset is the most common way these projects fail.

> No Mini-ELF model, diffusion, or flow training is implemented here, on purpose.

## 2. Core principle

**Candidate generators propose. Lean verifies.** (LLM proposes. Lean verifies.)

A raw candidate is *never* a positive label, no matter where it came from. A
tactic becomes a positive training transition only if Lean accepts it
(`success=True`). Failed attempts are kept in a separate file for analysis and
never mixed into the verified set.

## 3. Data flow

```
seed theorem / proof state
        │
        ▼
candidate generator        (mock | manual-file | anthropic | openai)
        │  proposes raw candidates
        ▼
tactic sanitizer           (strip fences/bullets/quotes, dedupe, drop sorry/admit/unsafe,
        │                   flag automation tactics)
        ▼
Lean runner                (mock | lean-cli | leandojo)
        │  verifies
   ┌────┴─────┐
   ▼          ▼
verified    failed
traces      attempts        (two separate JSONL files)
   │
   ▼
evaluator                  (success rate, automation/duplicate ratios, coverage,
                            distributions, honesty warnings)
```

## 4. Candidate sources (behind `LLMClient`)

| source        | needs key | what it does |
| ------------- | --------- | ------------ |
| `mock`        | no  | deterministic toy tactics; tests + smoke runs |
| `manual-file` | no  | reads candidates you (or the `tactic-proposer` agent) wrote into a JSONL under `data/manual/` |
| `anthropic`   | yes | real Claude proposals (lazy import, disk-cached) |
| `openai`      | yes | OpenAI-compatible proposals (lazy import, disk-cached) |

Future: LeanDojo / human Mathlib trace extraction.

## 5. Lean verification backends (behind `LeanRunner`)

| backend    | needs Lean | intermediate `state_after` | proof completion | notes |
| ---------- | ---------- | -------------------------- | ---------------- | ----- |
| `mock`     | no  | synthesized (heuristic) | heuristic | **not real verification** — pipeline tests only |
| `lean-cli` | yes | **no** — whole-file only | yes | real Lean subprocess; success ⇔ template file typechecks |
| `leandojo` | yes + traced repo | **yes** — real per-step states | yes | implemented behind the interface; needs `lean-dojo` installed + a traced repo |

### `lean-cli` vs `leandojo` — the key difference

- **`lean-cli`** substitutes the candidate into `seed.template` (replacing
  `seed.placeholder`), writes a temp `.lean` file, and runs `lean` (or
  `lake env lean`). A tactic is accepted iff the *whole file* typechecks, so
  `state_after` is the placeholder `<verified by lean-cli>` — there is **no real
  intermediate proof state**. Great for a first Lean-validated dataset.
- **`leandojo`** opens an interactive `Dojo` session for a theorem and runs each
  candidate against a live `TacticState`, returning the **actual resulting proof
  state** and goal count. This is the backend for true
  `state_before → tactic → state_after` transition collection (next-tactic
  datasets).

`LeanDojoRunner` keeps Lean execution fully behind the `LeanRunner` interface.
Because the protocol passes proof states as strings, the runner maintains a
registry mapping each state's pretty-printed string back to its live
`TacticState`, so the collector's per-state fan-out (multiple candidates from one
state) and multi-step search both work unchanged. Result mapping is duck-typed
(`.pp` ⇒ ongoing state; `ProofFinished` ⇒ done; anything else ⇒ error) to
tolerate LeanDojo version differences, and the runner reports the true
`num_goals_before` via record metadata.

> **Status here:** the leandojo backend was exercised against a real LeanDojo
> install in WSL2 Ubuntu. Tracing the published mini repo and
> `runner.start(seed)` both work — `start()` returns a real `TacticState`
> (e.g. `p : Prop\nh : p\n⊢ p`, id=0, num_goals=1). The first
> `runner.run_tactic` then fails with `DojoCrashError: Unexpected EOF`
> because Lean's batch frontend provides an empty stdin to elaboration-time
> IO (verified on Lean 4.20.0 and 4.30.0). Full diagnosis + reproducers:
> **[`docs/LEANDOJO_SETUP.md`](docs/LEANDOJO_SETUP.md) §8**.

Quick version (on a supported OS): install `lean-dojo` + a Lean toolchain, set
`GITHUB_ACCESS_TOKEN`, push `examples/leandojo_mini_repo` and fill its commit
into `data/seeds/leandojo_seeds.jsonl`, then:

```bash
python scripts/collect_traces.py \
    --seeds data/seeds/leandojo_seeds.jsonl \
    --out data/traces/leandojo_verified.jsonl \
    --failed-out data/traces/leandojo_failed.jsonl \
    --llm-backend manual-file \
    --manual-candidates data/manual/leandojo_candidates.jsonl \
    --lean-backend leandojo --max-seeds 1
```

Seeds need a LeanDojo locator (`repo_url`, `commit`, `file_path`, optionally
`full_name`). There is also an opt-in pytest harness:
`MINI_ELF_LEANDOJO_SMOKE=1 pytest tests/test_leandojo_smoke_real.py` (auto-skips
without LeanDojo + a real seed).

## 6. Setup

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -e .[dev]

cp .env.example .env               # only needed for real API / Lean config
```

The package installs cleanly with no Lean toolchain and no API keys; both
backends default to mocks.

- **lean-cli** needs a Lean 4 toolchain on `PATH` (install via
  [`elan`](https://lean-lang.org)). Optional extras: `pip install -e .[openai]`.
- **leandojo** is opt-in and not required.

Environment variables (all optional; see `.env.example`):
`MINI_ELF_LLM_BACKEND`, `MINI_ELF_LEAN_BACKEND`, `MINI_ELF_LLM_MODEL`,
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` / `MINI_ELF_OPENAI_API_KEY`,
`OPENAI_BASE_URL`, `MINI_ELF_LEAN_COMMAND`, `MINI_ELF_TACTIC_TIMEOUT`
(default 10s), `MINI_ELF_CACHE_DIR`.

## 7. Commands

### Mock collect + evaluate (no Lean, no key)

```bash
python scripts/collect_traces.py \
    --seeds data/seeds/toy_seeds.jsonl \
    --out data/traces/toy_traces.jsonl \
    --llm-backend mock --lean-backend mock

python scripts/evaluate_traces.py --path data/traces/toy_traces.jsonl
```

### Manual-file candidates, verified by the mock runner

```bash
python scripts/collect_traces.py \
    --seeds data/seeds/toy_lean_cli_seeds.jsonl \
    --out data/traces/manual_mock_verified_traces.jsonl \
    --failed-out data/traces/manual_mock_failed_traces.jsonl \
    --llm-backend manual-file \
    --manual-candidates data/manual/example_manual_candidates.jsonl \
    --lean-backend mock
```

### Manual-file candidates, verified by **real Lean**

```bash
python scripts/collect_traces.py \
    --seeds data/seeds/toy_lean_cli_seeds.jsonl \
    --out data/traces/manual_lean_cli_verified_traces.jsonl \
    --failed-out data/traces/manual_lean_cli_failed_traces.jsonl \
    --llm-backend manual-file \
    --manual-candidates data/manual/example_manual_candidates.jsonl \
    --lean-backend lean-cli
```

`MINI_ELF_LEAN_COMMAND="lean"` forces plain `lean`; otherwise the runner prefers
`lake env lean` when `lake` is on `PATH`. For Mathlib seeds, run from inside a
Lake project that imports Mathlib.

### Real LLM proposals

```bash
MINI_ELF_LLM_BACKEND=anthropic ANTHROPIC_API_KEY=... \
python scripts/collect_traces.py --seeds data/seeds/toy_lean_cli_seeds.jsonl \
    --out data/traces/anthropic.jsonl --lean-backend lean-cli \
    --prompt-style diverse -k 6 -t 0.7
```

Prompt styles: `conservative`, `diverse` (default), `no_automation`,
`tactic_block`. Other flags: `--max-seeds`, `-d/--max-depth`, `--dry-run`, `-v`.

### Generate a manual-candidate skeleton to fill in

```bash
python scripts/generate_manual_candidates.py \
    --seeds data/seeds/toy_lean_cli_seeds.jsonl \
    --out data/manual/my_candidates.jsonl
```

### Basic Lean corpus (theorem-level, lean-cli verified)

**134 tiny core-Lean theorems (no Mathlib) across 21 pattern families**, each
family with ≥5 variants so the proof patterns *repeat across the theorem-level
split* (the property the retrieval baseline needs to transfer). Families:
implication identity/composition, modus ponens, ∧ intro / left-elim /
right-elim / comm, ∨ intro-left/right / comm / self-elim, ↔ intro / mp / mpr,
`Eq.refl` / `Eq.symm` / `Eq.trans`, closed Nat equalities (`rfl`/`decide`),
∃-witnesses, `False`-elim, `True`-intro. Within a family the *hypothesis names
are held constant* (`h`, `hp`, `hq`, `h1`, `h2`) so the correct tactic STRING
is shared across variants — a train theorem's verified tactic is exactly what a
same-family eval theorem needs.

The seed file and matching candidate file are generated from one Python source
of truth (`scripts/generate_basic_corpus.py`) so their `(theorem_name,
state_before)` keys can't drift apart, and each row carries
`metadata.pattern_family` + `metadata.expected_success_tactics`.

```bash
# (1) regenerate the corpus (134 theorems / 616 candidate tactics)
python scripts/generate_basic_corpus.py

# (2) collect lean-cli traces. NOTE: point lean-cli at the toolchain binary
#     directly — the elan `lean` shim resolves "stable" over the network and
#     can stall for 100s+ under WSL2, causing spurious timeouts.
export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
python scripts/collect_traces.py \
    --seeds data/seeds/basic_lean_seeds.jsonl \
    --out  data/traces/basic_lean_cli_verified.jsonl \
    --failed-out data/traces/basic_lean_cli_failed.jsonl \
    --llm-backend manual-file \
    --manual-candidates data/manual/basic_lean_candidates.jsonl \
    --lean-backend lean-cli -k 8        # 616 attempts, ~1m45s, 0 timeouts

# (3) build the modeling-ready dataset (lean-cli only — never mock by accident)
python scripts/build_dataset.py \
    --input data/traces/basic_lean_cli_verified.jsonl \
    --output-dir data/processed/basic_lean_cli \
    --backend lean-cli

# (4) audit + pattern-family coverage (per-family success + split distribution
#     + warnings when a family can't transfer across the split)
python scripts/audit_corpus.py \
    --verified data/traces/basic_lean_cli_verified.jsonl \
    --failed   data/traces/basic_lean_cli_failed.jsonl \
    --seeds    data/seeds/basic_lean_seeds.jsonl \
    --splits   data/processed/basic_lean_cli/theorem_splits.json
```

This yields **329 verified rows / 287 failed (0 timeouts)** over all 134
theorems (every theorem has ≥1 verified tactic; every `expected_success_tactic`
typechecks). All verified rows are `verification_quality="theorem-level"` with
`state_after_is_real=false` — lean-cli only confirms the *whole file*
typechecks, so the `state_after` placeholder is **not** a real intermediate
proof state. The dataset is fine for tactic-only language modeling and for
state-conditional tactic prediction (state_before is real), but **not** for
state→state next-state modeling. That awaits the LeanDojo run_tac unblock
(`docs/LEANDOJO_SETUP.md` §8). The coverage audit confirms every val/test
theorem's pattern family has a train representative (only `eq_refl` and
`or_comm` happened to land train-only — harmless, just unevaluated).

### AR / retrieval baseline (theorem-level Lean verification)

Two tiny tactic-prediction baselines evaluated on the processed dataset, with
real `lean-cli` pass@k as the headline metric. This is **theorem-level**
verification: `lean-cli` typechecks the whole template substituted with the
predicted tactic. `state_after` is the lean-cli placeholder and is **not used
as a target** by anything here.

Baselines (see `src/mini_elf_lean/baselines.py`):

- **MajorityBaseline** — predicts the top-k most frequent training tactics
  regardless of input. Strong floor; anything model-like must beat it.
- **RetrievalBaseline** — k-NN over the training texts (`theorem_statement \n
  state_before`) using `sklearn` TF-IDF + cosine when available, else a pure
  Python char-2..4-gram cosine fallback. Returns deduplicated tactics in
  similarity rank order.
- **Oracle** (diagnostic, not deployable) — per `(theorem_name, state_before)`,
  the set of tactics known to be verified anywhere in the dataset; an
  upper-bound any in-corpus retrieval can reach.

Run all four cells the task brief asked for (`majority`/`retrieval` × `val`/`test`):

```bash
for B in majority retrieval; do
  for S in val test; do
    python scripts/evaluate_baseline.py \
      --dataset data/processed/basic_lean_cli/next_tactic.jsonl \
      --output-dir data/baselines/basic_lean_cli_${B}_${S} \
      --baseline ${B} --split ${S} --top-k 5 \
      --verify-with-lean-cli --cache
  done
done
```

Outputs (per output-dir, always written even on empty splits):

| file | meaning |
| --- | --- |
| `predictions.jsonl` | per-row predictions + provenance + lean results |
| `metrics.json` | aggregate exact-match + lean pass@k + oracle + leakage check |
| `verification_cache.json` | persistent `sha256(theorem_name + tactic)` → verifier result |
| `failures.jsonl` | failed-tactic detail (theorem, tactic, lean error) |

Metrics on the **134-theorem** corpus (split 102/16/16 theorems → 256/37/38
rows). `--verify-with-lean-cli` uses the direct toolchain binary via
`MINI_ELF_LEAN_COMMAND` (see corpus step 2):

| baseline | split | n_rows | top1_exact | top5 any-verified | **lean pass@5** |
| --- | --- | --- | --- | --- | --- |
| majority | val (16 thms) | 37 | 0.03 | 0.16 | 0.16 |
| **retrieval** (char-ngram) | val | 37 | **0.08** | **0.22** | **0.22** |
| majority | test (16 thms) | 38 | 0.05 | 0.16 | 0.16 |
| **retrieval** (char-ngram) | test | 38 | 0.05 | **0.32** | **0.32** |

**Lesson — retrieval needs repeated proof-pattern coverage across the
theorem-level split.** On the old 43-theorem corpus every pattern was
one-of-a-kind, the by-theorem split isolated each into val/test, and *both*
baselines scored **0% pass@k** — not a code bug, a coverage gap. Growing to
21 families × ≥5 variants (so each family straddles train and eval) flips this:
retrieval now **beats majority** on pass@5 (0.22 vs 0.16 val; 0.32 vs 0.16
test) and on top-5 any-verified, because a same-family train theorem supplies
the exact tactic an eval theorem needs.

The remaining gap is informative: retrieval's char-ngram similarity confuses
**structurally-similar sibling families** whose surface text is nearly
identical but whose correct tactic differs — `and_elim_left` vs
`and_elim_right` (goal `⊢ p` vs `⊢ q`), `or_intro_left` vs `or_intro_right`,
`iff_mp` vs `iff_mpr`, `imp_compose`. Those families still sit at 0 pass@5
because the top-5 gets crowded by the wrong sibling's tactic. Separating them
is exactly what a semantic retriever or a trained encoder would buy — i.e. the
motivation for the next (neural) baseline, not something more hand-written data
fixes. Families that *do* pass@5: `nat_rfl`, `false_elim`, `true_intro`,
`eq_symm`, `exists_witness` (their correct tactic is distinctive enough to rank).

### Neural AR baseline (trained tactic classifier)

A small **trained** model that maps `theorem_statement + "\n" + state_before →
tactic`. This is still **theorem-level tactic prediction, not true next-state
modeling** — `state_after` is never a target (the model consumes
`baselines.Example`, which has no `state_after` field, so this is structurally
guaranteed, and `tests/test_neural_baseline.py` enforces it).

Because the env has no numpy/torch/sklearn and the corpus is tiny (~254 train
rows, 55 distinct tactics), the model is the task brief's sanctioned fallback: a
**softmax / log-linear classifier (a 1-layer network) over hashed char-n-gram
features**, trained with seeded SGD — pure Python, CPU, deterministic
(`src/mini_elf_lean/neural_baseline.py`). Features are field-aware: full-text
n-grams *plus* goal-line n-grams hashed into a separate space (the goal line is
what separates sibling families), and L2-normalized for stable training.

```bash
export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
python scripts/evaluate_baseline.py \
    --dataset data/processed/basic_lean_cli/next_tactic.jsonl \
    --output-dir data/baselines/basic_lean_cli_neural_val \
    --baseline neural --split val --top-k 5 \
    --verify-with-lean-cli --cache --seeds data/seeds/basic_lean_seeds.jsonl \
    --epochs 80 --lr 1.0 --seed 0
# repeat with --split test --output-dir .../basic_lean_cli_neural_test
```

The neural run additionally writes `training_config.json` and
`training_log.jsonl`; passing `--seeds` adds `per_family_pass_at_k` and a
`sibling_confusion` table to `metrics.json` (works for all three baselines, so
they're comparable). Training is ~28 s for 80 epochs.

**Majority vs retrieval vs neural** (134-theorem corpus, split 102/16/16 thms;
lean-cli pass@k):

| baseline | split | top1_exact | top5 any-verified | pass@1 | pass@3 | **pass@5** |
| --- | --- | --- | --- | --- | --- | --- |
| majority | val | 0.03 | 0.16 | 0.08 | 0.16 | 0.16 |
| retrieval | val | 0.08 | 0.22 | 0.22 | 0.22 | 0.22 |
| **neural** | val | **0.19** | **0.65** | **0.46** | **0.59** | **0.65** |
| majority | test | 0.05 | 0.16 | 0.16 | 0.16 | 0.16 |
| retrieval | test | 0.05 | 0.32 | 0.16 | 0.16 | 0.32 |
| **neural** | test | **0.21** | **0.76** | **0.55** | **0.71** | **0.76** |

**The neural baseline decisively beats retrieval and majority** on every metric
(pass@5 0.65/0.76 vs retrieval 0.22/0.32 vs majority 0.16). Per-family pass@5
jumps to 1.00 for families retrieval scored 0.00 on — `and_comm`, `eq_trans`,
`iff_mp`, `imp_compose`, `imp_identity`, `and_intro`, `iff_intro`, `iff_mpr`,
`modus_ponens`, `or_intro_right` — because the classifier ranks the family's
shared correct tactic high instead of copying a near-neighbor's tactic.

**Does neural reduce sibling-family confusion? Partly.** Top-1 *family* accuracy
on the sibling groups (was 0.00 for both majority and retrieval everywhere):

| sibling group | neural val | neural test |
| --- | --- | --- |
| `eq` (refl/symm/trans) | **1.00** | **1.00** |
| `imp` (identity/compose/modus_ponens) | **1.00** | **1.00** |
| `iff` (mp/mpr/intro) | 0.00 | **0.75** |
| `and_elim` (left/right) | 0.00 | 0.00 |
| `or_intro` (left/right) | 0.00 | 0.00 |

It **solves** the groups whose correct tactics are lexically distinctive
(`eq`: `rfl` vs `h.symm` vs `h1.trans h2`; `imp`). It **fails** exactly the
groups whose only discriminator is *relational position* — `and_elim_left`
(`⊢ p`, tactic `h.1`) vs `and_elim_right` (`⊢ q`, tactic `h.2`), and `or_intro`
left vs right — where the confusion matrix shows it predicting the wrong
sibling's tactic. A bag-of-n-gram model can't represent "the goal equals the
*first* vs *second* conjunct". Closing that needs a model with positional /
structural awareness (a real sequence encoder or the embedded-flow approach) —
the concrete motivation for the next milestone. Still 0-pass@5 families:
`and_elim_*`, `or_self_elim`, and `exists_witness` on val (the witness number
`⟨5, rfl⟩` is a novel token never seen in train — an open-vocabulary limit a
classifier over a fixed tactic set can't cross).

### Generative AR seq2seq model (PyTorch CPU)

The project's first **true generative** tactic model — it decodes a tactic
**character by character** (a char-level GRU encoder–decoder with additive
attention), so unlike the fixed-class classifier it can emit tactic strings
never seen as a training label. Same honesty constraints: input is
`theorem_statement + "\n" + state_before` only; `state_after` is never read
(`tests/test_ar_data.py` enforces it). Small + CPU-only + deterministic:
emb 64 / hidden 128 / 1-layer bi-GRU, **410K params**, PyTorch `2.12.0+cpu`,
trained in ~110 s for 60 epochs (checkpoint selected by val greedy exact-match).
PyTorch is an **optional** dependency (`pip install -e .[ar]`); the rest of the
project and the torch-gated tests run without it.

```bash
# train (writes config.json / vocab.json / model.pt / train_log.jsonl / val_*.json)
python scripts/train_ar_model.py \
    --dataset data/processed/basic_lean_cli/next_tactic.jsonl \
    --output-dir data/models/basic_lean_cli_ar \
    --epochs 60 --batch-size 32 --lr 0.003 \
    --embedding-dim 64 --hidden-dim 128 --seed 0

# evaluate with real lean-cli pass@k (beam search, top-k dedup) — val and test
export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
python scripts/evaluate_ar_model.py \
    --model-dir data/models/basic_lean_cli_ar \
    --dataset data/processed/basic_lean_cli/next_tactic.jsonl \
    --output-dir data/baselines/basic_lean_cli_ar_val \
    --split val --top-k 5 --beam-width 5 \
    --verify-with-lean-cli --cache --seeds data/seeds/basic_lean_seeds.jsonl
# (scripts/run_ar_eval.sh runs both splits with the right toolchain binary)
```

**AR vs the others** (134-theorem corpus, split 102/16/16 thms; lean-cli pass@k):

| baseline | split | top1_exact | top5 any-verified | pass@1 | pass@3 | **pass@5** |
| --- | --- | --- | --- | --- | --- | --- |
| log-linear | val | 0.19 | 0.65 | 0.46 | 0.59 | 0.65 |
| **AR seq2seq** | val | **0.30** | **0.78** | **0.70** | **0.70** | **0.78** |
| log-linear | test | 0.21 | 0.76 | 0.55 | 0.71 | 0.76 |
| **AR seq2seq** | test | **0.32** | **0.82** | **0.76** | **0.82** | **0.82** |

**The generative model beats the log-linear classifier on every `pass@k`** — the
biggest gain is `pass@1` (test 0.76 vs 0.55). Generation is well-behaved: 0%
empty, avg generated length ~16 chars, no truncation. Top-1 *family* accuracy on
the sibling groups improves over the classifier — it now solves `iff` (1.00 both
splits, vs 0.00/0.75) and reaches **0.50** on `or_intro` (vs 0.00), while `eq`
and `imp` stay at 1.00; only purely *relational* `and_elim` (left vs right) stays
at 0.00 for every baseline.

**Open-vocabulary — partial, and reported honestly.** ~50% of the AR model's
top-5 candidates are *novel* (not a training label), which a fixed-class model
can never produce. It learns the **template** `exact ⟨N, rfl⟩` and varies the
witness over the small numbers `{0,1,2}` seen in train — so on test it solves
`exists_nat_0`, but it still **fails** `exists_nat_5` / `exists_nat_7` (val)
because it never learned to emit `5` or `7`. So the open-vocabulary win is real
but bounded: template generalization, not unbounded numeric extrapolation.
Honest failure modes show up too — e.g. it once generated `exact And.righ`
(a char-level truncation of `And.right`) and incomplete blocks like
`constructor\n  exact hp\n ` — and ~65% of generated candidates fail Lean
(the beam emits 5; typically 1–2 verify). 16 eval theorems/split → directional.

### Mini-ELF v0 (embedded-flow tactic generator, PyTorch CPU)

The first **Mini-ELF prototype** — small and honest, **not** the full ELF
research target and **not** next-state modeling (still theorem-level,
`state_after_is_real=false`). Two stages
(`src/mini_elf_lean/elf_{embed,flow,train,sample}.py`):

1. **Tactic autoencoder** (char-level GRU) maps a tactic string → a continuous
   **latent** (dim 48) → string. This is the embedded space; AE val
   reconstruction is **0.89**.
2. **Conditional rectified flow**: a small MLP learns a velocity field
   transporting `N(0,I)` → the (standardized) tactic latent, conditioned on a
   bi-GRU embedding of `theorem_statement + "\n" + state_before`
   (`z_t = (1-t)·ε + t·x`, target `v = x − ε`). Sampling draws K noise vectors,
   Euler-integrates the flow, decodes each latent (AE **decoder**, or **nn**-snap
   to a train tactic), dedups, and ranks by sample frequency.

342K params total (ae 121K / cond 173K / flow 49K), trained in **~104 s** (AE 60
epochs + flow 300 epochs), deterministic given `--seed`.

```bash
python scripts/train_mini_elf.py \
    --dataset data/processed/basic_lean_cli/next_tactic.jsonl \
    --output-dir data/models/basic_lean_cli_mini_elf \
    --ae-epochs 60 --flow-epochs 300 --latent-dim 48 --cond-dim 128 --seed 0

export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
python scripts/evaluate_mini_elf.py \
    --model-dir data/models/basic_lean_cli_mini_elf \
    --dataset data/processed/basic_lean_cli/next_tactic.jsonl \
    --output-dir data/baselines/basic_lean_cli_mini_elf_val \
    --split val --top-k 5 --n-samples 32 --flow-steps 10 --decode decoder \
    --verify-with-lean-cli --cache --seeds data/seeds/basic_lean_seeds.jsonl
# scripts/run_mini_elf_eval.sh runs val+test in both decode modes
```

**Mini-ELF v0 vs AR** (lean-cli pass@k):

| model | split | top1_exact | pass@1 | pass@3 | **pass@5** | distinct cand/row |
| --- | --- | --- | --- | --- | --- | --- |
| AR seq2seq | val | 0.30 | 0.70 | 0.70 | 0.78 | ≤5 |
| Mini-ELF (decoder) | val | 0.22 | 0.51 | 0.84 | **0.84** | 20.3 |
| Mini-ELF (nn) | val | 0.27 | 0.65 | 0.89 | 0.89 | 8.1 |
| AR seq2seq | test | 0.32 | 0.76 | 0.82 | 0.82 | ≤5 |
| Mini-ELF (decoder) | test | 0.24 | 0.61 | 0.82 | **0.90** | 19.1 |
| Mini-ELF (nn) | test | 0.32 | 0.76 | 0.92 | **1.00** | 7.8 |

**Beats AR on `pass@5` (recall), trails on `pass@1` (precision)** — the expected
profile of a stochastic generator with high candidate diversity (~20 distinct
candidates/row vs AR's ≤5). It generates **valid *alternative* proofs** (e.g. for
an `And.intro` goal whose gold is `exact ⟨hp, hq⟩` it emits the verified
`constructor\n  exact hp\n  exact hq`). Honest gaps: ~40% of candidates are novel
but **none verified** (`novel_verified=0` — char-level garble like
`constructoontroctoo`, witness errors `exact ⟨a, rfl⟩`), and top-1 family accuracy
is noisier than AR. The **nn**-decode variant is strongest on `pass@k` (test
`pass@5` 1.00) but only emits train tactics (novel-rate 0) — latent-space
retrieval, not generation. See [`docs/PROJECT_REPORT.md`](docs/PROJECT_REPORT.md).

### Mini-ELF v1 (reranker + structure + witness-copy, PyTorch CPU)

v1 keeps the v0 generator and adds four modules (new files
`src/mini_elf_lean/elf_{structure,rerank,witness,v1_train,v1_sample}.py`; v0 is
left untouched):

1. **Structure-aware condition encoder** — a heuristic `⊢`-turnstile parser
   (`elf_structure.py`) feeds a goal bi-GRU + goal-shape embedding + numeric
   features alongside the v0 raw-prompt encoder.
2. **Denoising tactic-AE** — input char corruption + latent noise widen the basin
   of latents that decode to *valid* tactics (AE recon held at **0.892**, ~35
   distinct candidates/row).
3. **Verifier-aware reranker** (`elf_rerank.py`) — a small classifier scoring
   `(state, candidate) → P(verifies)`, trained on past Lean accept/reject outcomes
   **plus self-training hard negatives** (v1's own flow candidates on train
   theorems, Lean-labelled). Hand features include hypothesis-binding ratio and
   conjunct/disjunct consistency. Ranks a top-frequency **shortlist** (+ witnesses)
   so precision rises without sacrificing recall.
4. **Witness-copy** (`elf_witness.py`) — symbolic augmentation copying prompt
   literals into `exact ⟨N, rfl⟩` for `∃` goals (tagged `witness_copy`, verified
   by the same Lean verifier).

Generator 399K params (latent 64), reranker is a tiny CPU classifier; one command
trains both and runs all eval modes:

```bash
export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
bash scripts/run_mini_elf_v1_eval.sh        # train v1 (+ self-trained reranker), eval val+test ×4 modes
# or piecewise:
python scripts/train_mini_elf_v1.py --dataset data/processed/basic_lean_cli/next_tactic.jsonl \
    --output-dir data/models/basic_lean_cli_mini_elf_v1 \
    --verified-traces data/traces/basic_lean_cli_verified.jsonl \
    --failed-traces data/traces/basic_lean_cli_failed.jsonl \
    --splits data/processed/basic_lean_cli/theorem_splits.json --seeds data/seeds/basic_lean_seeds.jsonl \
    --ae-epochs 80 --flow-epochs 400 --rerank-epochs 80 --self-train-rerank --latent-dim 64 --seed 0
python scripts/evaluate_mini_elf_v1.py --model-dir data/models/basic_lean_cli_mini_elf_v1 \
    --dataset data/processed/basic_lean_cli/next_tactic.jsonl \
    --output-dir data/baselines/basic_lean_cli_mini_elf_v1_rerank_witness_val \
    --split val --mode decoder_rerank_witness --verify-with-lean-cli --cache \
    --seeds data/seeds/basic_lean_seeds.jsonl
```

**Mini-ELF v1 vs AR / v0** (lean-cli pass@k):

| model | split | pass@1 | pass@3 | pass@5 | invalid@1 | novel_verified |
| --- | --- | --- | --- | --- | --- | --- |
| AR seq2seq | test | 0.76 | 0.82 | 0.82 | — | 2 |
| Mini-ELF v0 (decoder) | test | 0.61 | 0.82 | 0.89 | 0.67 | 0 |
| Mini-ELF v1 (rerank) | test | **0.89** | 0.89 | 0.89 | **0.11** | 0 |
| Mini-ELF v1 (rerank+witness) | test | **0.89** | **0.95** | **0.95** | **0.11** | **2** |

The **reranker** supplies the precision (test pass@1 0.61→0.89, invalid@1
0.34→0.11), **witness-copy** restores recall on `∃` goals and adds verifiable
novelty (`novel_verified` 0→10 val / 2 test), and the structure features make v1
the first model to crack `and_elim`/`or_intro` (top-1 family accuracy 0.00→1.00).
Honest gaps: witness-copy is symbolic; `exists_witness` is solved at `pass@5` not
`pass@1`; the reranker's clean separation partly reflects the small templated
corpus + self-training loop. See [`docs/RESULTS_SUMMARY.md`](docs/RESULTS_SUMMARY.md).

### Build a modeling-ready dataset from verified traces

```bash
python scripts/build_dataset.py \
    --input data/traces/manual_lean_cli_verified_traces.jsonl \
    --output-dir data/processed \
    --backend lean-cli
```

Outputs (always written, even when empty):

| file | shape |
| ---- | ----- |
| `data/processed/next_tactic.jsonl` | one row per included transition with `state_after_is_real`, `verification_quality`, `split` |
| `data/processed/plain_tactics.txt` | deduplicated, sorted distinct tactic strings (one per line; literal `\n` for multi-line) |
| `data/processed/theorem_splits.json` | `{train, val, test}` lists of theorem names + `seed` + `split_fractions` |
| `data/processed/summary.json` | counts + per-reason `excluded` map + filters echo |

Defaults are conservative: `lean-cli`+`leandojo` only, mock excluded, failed
records excluded, dedup on by `(theorem, state_before, tactic)`, splits 80/10/10
by **theorem name** (deterministic; adding new theorems doesn't shift existing
splits). Opt-in flags: `--allow-mock`, `--include-failed`,
`--exclude-proof-finished`, `--max-tactic-len`, `--max-state-len`, `--no-dedup`,
`--backend ... --backend ...`. Each row carries `verification_quality`:

| backend | `verification_quality` | `state_after_is_real` |
| --- | --- | --- |
| `leandojo` (`success=True`, real pp) | `real` | **`true`** |
| `lean-cli` | `theorem-level` | `false` (placeholder) |
| `mock` (only with `--allow-mock`) | `mock` | `false` (heuristic) |

A downstream trainer that wants true state-transition supervision must filter
on `state_after_is_real == true` — the builder never fabricates next states,
even when `--allow-mock` is on.

## 8. JSONL schemas

**TheoremSeed** (`data/seeds/*.jsonl`) — old rows with only
`theorem_name`/`theorem_statement`/`initial_state` still validate:

```json
{"theorem_name": "nat_refl", "theorem_statement": "(n : Nat) : n = n",
 "initial_state": "n : Nat\n⊢ n = n", "imports": [],
 "template": "example (n : Nat) : n = n := by\n  __TACTIC__", "placeholder": "__TACTIC__"}
```

For the **leandojo** backend a seed instead carries a repo locator (all optional,
so other backends and old seeds are unaffected):

```json
{"theorem_name": "and_comm_toy", "theorem_statement": "(p q : Prop) : p ∧ q → q ∧ p",
 "repo_url": "https://github.com/owner/repo", "commit": "<sha>",
 "file_path": "Path/To/File.lean", "full_name": "Namespace.and_comm_toy"}
```

`full_name` falls back to `theorem_name` when omitted; `theorem_pos` and
`dojo_metadata` are also available for advanced use.

**ManualCandidateRecord** (`data/manual/*.jsonl`) — proposals only:

```json
{"theorem_name": "nat_refl", "state_before": "n : Nat\n⊢ n = n",
 "candidates": ["rfl", "exact rfl"], "source": "claude_code_agent",
 "prompt_style": "diverse", "metadata": {}}
```

**TraceRecord** (`data/traces/*.jsonl`) — one verified-or-rejected attempt:

| field | meaning |
| --- | --- |
| `theorem_name`, `theorem_statement` | provenance of the seed |
| `state_before`, `tactic`, `state_after` | the transition (state_after may be the lean-cli placeholder) |
| `success` | **the only field that makes a record a positive label** |
| `proof_finished`, `num_goals_before`, `num_goals_after`, `state_changed` | goal bookkeeping |
| `error`, `timeout` | failure detail |
| `source`, `model`, `backend`, `prompt_style`, `temperature` | run metadata |
| `raw_llm_output`, `timestamp`, `step_index`, `parent_state_hash`, `metadata` | extras |

## 9. Evaluation metrics

`evaluate_traces.py` reports: total / successful / failed records, success rate,
proof_finished count and ratio, unique theorems / states / tactics, top-20
tactics, duplicate `(state_before, tactic)` ratio, automation-tactic ratio,
average goals before/after/reduced, state_changed ratio, and
backend / model / source / prompt_style distributions. It prints **warnings**
when data is all-mock, automation-heavy, duplicate-heavy, or only lean-cli
placeholder states. Use `--json` for machine-readable output.

When you build splits later, split by `theorem_name`, never by transition.

## 10. Tests

```bash
pytest -q
```

The suite uses only mock backends, a monkeypatched subprocess (lean-cli), and a
mocked LeanDojo module (leandojo), so it needs no real Lean, no LeanDojo, and no
API keys.

## 11. Limitations (read before claiming anything)

- `lean-cli` is **template-level** verification: it confirms a whole file
  typechecks, so its `state_after` is a placeholder, not a true intermediate
  proof state.
- The **LeanDojo** backend's API contract is verified against a real install
  in WSL2 Ubuntu (lean-dojo 4.20.0, Lean 4.20.0). Tracing the mini repo and
  `runner.start(seed)` produce a real initial `TacticState`. **`Dojo.run_tac`
  is blocked**: Lean 4.20+/4.30+ batch frontend provides an empty stdin to
  elaboration-time IO, so LeanDojo's `Lean4Repl` tactic crashes on its first
  `getLine` with `[fatal] failed to parse JSON ... unexpected end of input`,
  surfaced to the runner as `DojoCrashError: Unexpected EOF`. The runner is
  API-correct (see `tests/test_leandojo_runner_real_api.py`), and the real
  smoke test is marked `xfail(strict=True)`. Diagnosis + reproducers:
  [`docs/LEANDOJO_SETUP.md`](docs/LEANDOJO_SETUP.md) §8. **No real
  state-transition records exist yet**; until LeanDojo is unblocked, the
  dataset builder writes only `lean-cli` rows (`theorem-level` quality).
- The `mock` backend is **not** real verification; treat mock datasets as
  plumbing tests only.
- LLM / manual candidates may be biased (e.g. toward automation tactics) — the
  evaluator's automation ratio is there to keep you honest.
- The **AR seq2seq and Mini-ELF v0 are tactic-prediction generators**, still
  scored at theorem level (`state_after_is_real=false`) — *not* next-state /
  proof-state-transition models. PyTorch is an optional extra; both are small
  (≤410K params) and CPU-only by design.
- **Mini-ELF v0 is a small prototype, not the full ELF method.** It is a tactic
  autoencoder + conditional rectified-flow generator; it does **not** model real
  proof-state flow. Its generative (decoder) path trails AR on `pass@1` and its
  novel generations don't yet verify (`novel_verified=0`); its nn-decode variant
  is strong on `pass@k` but is latent-space retrieval, not open-vocabulary
  generation. No diffusion. No next-state results.

## 12. Next steps

1. ~~Validate the LeanDojo backend against a real traced repo.~~ **Done in
   WSL2**: tracing + `runner.start()` work; `run_tac` blocked by the
   elaboration-stdin Lean limitation (`docs/LEANDOJO_SETUP.md` §8). Treat as
   experimental/`xfail` until a fix lands upstream.
2. ~~Build a next-tactic dataset (split by `theorem_name`).~~ **Done**:
   `scripts/build_dataset.py` → `data/processed/{next_tactic.jsonl,
   plain_tactics.txt, theorem_splits.json, summary.json}`. Until LeanDojo is
   unblocked the dataset is `lean-cli`-only (`theorem-level` quality, no real
   intermediate states); models that need true `state_after` must filter
   `state_after_is_real == true`.
3. ~~Grow the verified theorem-level corpus.~~ **Done**: 43 core-Lean
   theorems × ~3.5 candidates → 149 attempts → **110 verified, 39 failed
   (success rate 73.8%, zero theorems unverified, no duplicate attempts)**.
   Files: `scripts/generate_basic_corpus.py` (source of truth),
   `data/seeds/basic_lean_seeds.jsonl`, `data/manual/basic_lean_candidates.jsonl`,
   `data/traces/basic_lean_cli_{verified,failed}.jsonl`,
   `data/processed/basic_lean_cli/`. Per-theorem / per-tactic / error audit:
   `scripts/audit_corpus.py`.
4. ~~Autoregressive next-tactic baseline with verifier-aware metrics.~~
   **Done (retrieval-style, not trained AR):** `scripts/evaluate_baseline.py`
   runs `majority` and `retrieval` (TF-IDF or char-ngram cosine fallback)
   baselines against `data/processed/basic_lean_cli/next_tactic.jsonl` and
   reports `top1_exact`, `topk_any_verified`, and **real `lean-cli` pass@k**,
   with a persistent verification cache keyed by `sha256(theorem_name ||
   tactic)`.
5. ~~Grow pattern coverage so baselines have transfer cases.~~ **Done**: the
   corpus is now 134 theorems / 21 pattern families (≥5 variants each). On this
   corpus retrieval beats majority (pass@5 0.22/0.32 vs 0.16) — see the
   "AR / retrieval baseline" section. The leftover 0-pass@5 families are
   sibling-confusable ones (and-left/right, or-inl/inr, iff-mp/mpr), which a
   semantic retriever / trained encoder should separate.
6. ~~A trained neural next-tactic baseline.~~ **Done**: a pure-Python
   softmax/log-linear char-n-gram classifier (`src/mini_elf_lean/neural_baseline.py`,
   `--baseline neural`). Beats retrieval/majority decisively (pass@5 0.65/0.76)
   and solves the lexically-distinctive sibling groups (`eq`, `imp`), but still
   fails the purely *relational* ones (`and_elim` left/right, `or_intro`) — see
   "Neural AR baseline". That residual is what a positionally/structurally aware
   model (real encoder, or the embedded-flow approach) is needed for.
7. ~~A sequence model to crack the relational siblings and the open-vocabulary
   `exists_witness` case.~~ **Done (mostly)**: a char-level GRU encoder–decoder
   with attention (`src/mini_elf_lean/ar_model.py`, PyTorch CPU; train via
   `scripts/train_ar_model.py`, evaluate via `scripts/evaluate_ar_model.py`).
   It **beats the log-linear classifier on every pass@k** (test pass@5
   0.82 vs 0.76, pass@1 0.76 vs 0.55), solves `iff` and partly `or_intro`, and
   generates *novel* verified tactics (partial open-vocabulary: it composes the
   `exact ⟨N, rfl⟩` template but only for witnesses `{0,1,2}` seen in train —
   `exists_nat_5/7` still fail). **Still open**: purely relational `and_elim`
   (left vs right) and out-of-range numeric witnesses.
8. ~~A first Mini-ELF prototype.~~ **Done — Mini-ELF v0**: a tactic-autoencoder
   latent + conditional rectified-flow generator
   (`src/mini_elf_lean/elf_{embed,flow,train,sample}.py`; train
   `scripts/train_mini_elf.py`, eval `scripts/evaluate_mini_elf.py`). Beats AR
   on `pass@5` (test 0.90 vs 0.82) via stochastic candidate diversity (~20/row),
   trails on `pass@1`. **Mini-ELF v1** needs: higher top-1 precision (better
   latent→string fidelity; rank by likelihood not just frequency), novel
   generations that actually verify (currently `novel_verified=0`), and a
   structure-aware condition encoder for `and_elim`.
9. Real LLM proposals at scale (anthropic/openai) with prompt-style comparison
   to grow the verified corpus further.
10. Extract human Mathlib / LeanDojo traces as a candidate source.
11. The **full ELF embedded-flow research target** (real proof-state flow,
    requiring next-state supervision via a LeanDojo unblock). Mini-ELF v0 is a
    small prototype of the *generation* loop, not this method.

## Project layout

```
ELPMath/
  data/{seeds,manual,traces}/      seeds, manual candidates, verified output
  data/processed/                  (created on demand) build_dataset.py outputs
  examples/*.lean                  reference Lean source for the seeds
  data/models/                     (created on demand) trained AR + Mini-ELF artifacts
  scripts/                         collect_traces, evaluate_traces,
                                   generate_manual_candidates,
                                   generate_basic_corpus, build_dataset,
                                   audit_corpus, evaluate_baseline,
                                   train_ar_model, evaluate_ar_model, run_ar_eval.sh,
                                   train_mini_elf, evaluate_mini_elf,
                                   run_mini_elf_eval.sh, debug_leandojo_*, probe_*
  src/mini_elf_lean/               schemas, config, io_utils, prompt_templates,
                                   tactic_sanitizer, llm_client, lean_runner,
                                   collector, evaluate_traces, dataset_builder,
                                   corpus_audit, baselines, baseline_eval,
                                   neural_baseline, ar_model, ar_train, ar_decode,
                                   elf_embed, elf_flow, elf_train, elf_sample
  tests/                           pytest suite (mock backends + a real-API
                                   guard for LeanDojoRunner + xfail real smoke
                                   + dataset_builder + corpus_audit + basic
                                   corpus generator round-trip + baselines +
                                   neural + AR + Mini-ELF flow/embed/sampling,
                                   torch-gated)
  .claude/skills/                  lean-trace-collector, lean-dojo-integration,
                                   tactic-data-quality, mini-elf-modeling (deferred)
  .claude/agents/                  tactic-proposer, trace-auditor
```
