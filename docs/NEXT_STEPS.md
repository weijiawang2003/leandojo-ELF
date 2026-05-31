# Next Steps

## Current status: Mini-ELF v27 (scaled Mathlib specialist + hardened verifier)

v27 is complete. The corrected verifier (`TrustedMathlibVerifier`: sentinel +
confirm + rescue) is the trusted default and is **sound and complete** vs a gold
one-per-file reference (0 false positives, matches gold exactly); the old naive
batched verifier is quarantined to the audit/tests. Scaling the Mathlib corpus
(+181 verified rows, Set 53 / order 40) lifted held-out tier-C — **v25 held-out
pass@10 1.000, v26 held-out 0.955, Set residual closed 0.75 → 1.00, order 1.00** —
with routed broad-core **preserved bit-identically** (0.9375/0.9583) on the
untouched v24 model. Recommended specialist: `token_seq2seq_v27_set_heavy`.

### v28 recommendation
- **More targeted single-tactic shapes** for the *fresh-holdout* residuals
  (`mem_inter_iff`, `union_subset`) — the plateau (0.714) is data-coverage-bound,
  not architecture- or planning-bound, so this is the highest-value lever.
- Broaden categories (Finset, more order/lattice, Function) the same way.
- Only **after** single-tactic coverage saturates, consider LeanDojo next-state
  supervision (`state_after`) — it is **not** yet the bottleneck.
- Optional separate broad-core pass for the 3 deferred v24 residuals
  (`and_assoc_one`, `or_inr`, `or_elim_to_common`) — keep it off the protected
  v24 model (specialist/router), never co-train into broad-core.

---

Ordered by dependency. Status as of the Mini-ELF v0 milestone (historical below).

## Near-term engineering

1. **Grow the corpus.** Add more variants per family and more families via
   `scripts/generate_basic_corpus.py` (the generator + `audit_corpus.py` catch
   typos and drift). Target enough eval theorems per family that `pass@k` is
   statistically meaningful (current: 16 eval theorems/split → diagnostic only).
2. **Collect real LLM proposals.** Wire `--llm-backend anthropic|openai` into
   `collect_traces.py` runs (keys via env), compare prompt styles, and grow the
   verified corpus beyond hand-written templates.
3. **Robust lean-cli invocation.** Keep `MINI_ELF_LEAN_COMMAND` pointed at the
   concrete toolchain binary (not the elan shim) to avoid the WSL2 network-stall
   timeouts; consider documenting this in the runner's default resolution.
4. **Install numpy/sklearn (optional).** Would enable a real TF-IDF retrieval
   point of comparison and a less hand-rolled classifier without changing the
   evaluation harness.

## Research extensions

1. ~~Generative (open-vocabulary) decoding.~~ **Done**: the char-level GRU
   seq2seq (`src/mini_elf_lean/ar_model.py`) generates tactic strings character
   by character — it beats the classifier on every `pass@k` and produces *novel*
   verified tactics (composing `exact ⟨N, rfl⟩` for seen witnesses).
2. ~~A first embedded-flow generator.~~ **Done — Mini-ELF v0**
   (`src/mini_elf_lean/elf_{embed,flow,train,sample}.py`): a tactic-autoencoder
   latent + conditional rectified-flow model. Beats AR on `pass@5` (test 0.90 vs
   0.82) via ~20 stochastic candidates/row.
   ~~Mini-ELF v1: raise `pass@1` precision and make novel generations verify.~~
   **Done — Mini-ELF v1** (`elf_{structure,rerank,witness,v1_train,v1_sample}.py`):
   a verifier-aware reranker (trained on past Lean outcomes + self-training hard
   negatives) raises test `pass@1` 0.61→**0.89**; witness-copy makes
   `∃`-generations verify (`novel_verified` 0→**10/2**); structure-aware features
   crack the siblings. Open items → Mini-ELF v2 below.
3. ~~**Structure-aware model.** `and_elim` left vs right top-1 family accuracy
   0.00 for every model.~~ **Done in v1**: the reranker's conjunct/disjunct
   consistency features take `and_elim` and `or_intro` top-1 family accuracy
   0.00→**1.00**. Remaining: families needing multi-step tactics
   (`or_self_elim`), and lifting `exists_witness` from `pass@5` to `pass@1`.
4. **Real next-state supervision.** Unblock LeanDojo `run_tac` (fix the
   elaboration-stdin path, pin a working Lean version, or add an interactive
   REPL backend) so `state_after_is_real=true` data can be collected and a
   genuine `state_before → tactic → state_after` model trained.

## Mini-ELF roadmap

**Mini-ELF v0 (a small prototype of the *generation loop*) is implemented** — a
tactic autoencoder latent + conditional rectified-flow generator + Lean
verification, comparable to the baselines via the same `pass@k` harness. The
**full ELF method** (continuous embedded-flow over *proof states*) remains the
eventual research target and still needs:

1. A larger, real-LLM-augmented verified corpus.
2. ~~A strong autoregressive baseline to beat.~~ **Done**: AR seq2seq (test
   pass@5 0.82) and Mini-ELF v0 (test pass@5 0.90).
3. ~~**Mini-ELF v1**: precision + verifiable novel generation; structure-aware
   encoder for `and_elim`.~~ **Done** (test pass@1 0.89, pass@5 0.95; siblings
   1.00; `novel_verified` 10/2). See §9b of the project report.
4. ~~**Mini-ELF v2**: validate v1 on a larger, less-templated corpus.~~ **Done —
   generalization study** (§9c; [`V2_GENERALIZATION_REPORT.md`](V2_GENERALIZATION_REPORT.md)).
   Result: v1 **overfits** the templated basic corpus (`pass@5` 0.95 → 0.00–0.23
   under shift); only symbolic witness-copy transfers. Combined-corpus retraining
   (v2) recovers in-distribution-hard (`pass@5` 1.00) and partial adversarial
   siblings (0.53), but **not** compositional holdout (0.06) and **regresses**
   basic (0.82).
5. ~~**Mini-ELF v3**: compositional generalization.~~ **Done — structured
   proof-block planner** (`src/mini_elf_lean/proof_planner.py`,
   `elf_v3_sample.py`; [`V3_PROOF_PLANNER_REPORT.md`](V3_PROOF_PLANNER_REPORT.md)).
   A symbolic planner that *constructs* proofs (chains / projection / case splits
   / iff·eq composition) fused above the v2 model takes `difficulty_holdout`
   `pass@5` **0.06 → 1.00** (ablation: planner off = 0.08), recovers adversarial
   siblings (0.53 → 1.00) and the basic regression (0.82 → 1.00). **But it is
   engineered symbolic coverage, not learned generalization** — see §8 of the
   report. It also resolves the prior v3 wishlist: relational siblings under
   holdout (planner constructs both `Or.inl`/`Or.inr` and `h.1`/`h.2` directly)
   and reranker mis-calibration (the planner *bypasses* the reranker).
6. ~~**Mini-ELF v4**: proof shapes outside the template library.~~ **Done —
   planner-blind benchmark** (`scripts/generate_planner_blind_corpus.py`,
   `proof_planner_v4.py`; [`V4_PLANNER_BLIND_REPORT.md`](V4_PLANNER_BLIND_REPORT.md)).
   A 61-theorem corpus of negation/contrapositive/∃-elim/∀-inst/rewrite shapes the
   planner cannot construct. Unchanged v3 **collapses** to `pass@5` 0.096; a
   controlled template-addition ablation recovers only the *targeted* families
   (whack-a-mole) and leaves `forall_inst`/`rewrite_succ` at 0.00 — confirming
   symbolic coverage is per-shape and never complete.
7. ~~**Mini-ELF v5**: candidate proposal beyond hand-written templates.~~
   **Done — data-driven proposers** (`src/mini_elf_lean/proposer.py`,
   `retrieval_proposer.py`, `llm_proposer.py`, `elf_v5_sample.py`;
   [`V5_RESULTS_SUMMARY.md`](V5_RESULTS_SUMMARY.md)). A common
   `CandidateProposer` interface + a train-free **retrieval** proof-block
   proposer (example reuse + numeric-literal adaptation) takes the two
   template-less families `forall_inst` / `rewrite_succ` to `pass@5` **1.00** on a
   within-family split (`family_interpolation`) with **no** template, while v3
   stays at 0.107 and v4-templates at 0.821 (0.00 on the targets). Combining
   templates + retrieval reaches 1.00 overall (complementary). **Honesty:**
   retrieval is example reuse, not reasoning; char-similarity still confuses the
   negation siblings (`neg_exfalso` 0.00). The **LLM** proposer is implemented but
   API-key-gated (skipped here, not faked — `V5_LLM_PILOT_SKIPPED.md`); the
   learned seq2seq proposer is deferred (`V5_LEARNED_PROPOSER.md`).
8. ~~**Mini-ELF v6**: structure-aware retrieval ranking.~~ **Done**
   (`src/mini_elf_lean/retrieval_features.py`, `StructureAwareRetrievalProposer`
   in `retrieval_proposer.py`; [`V6_STRUCTURE_AWARE_RETRIEVAL_REPORT.md`](V6_STRUCTURE_AWARE_RETRIEVAL_REPORT.md)).
   Heuristic structural features (goal shape, hypothesis shapes, guessed
   `required_operation`, left/right conjunct position, connective overlap) +
   adapted-candidate preference re-rank the *same* retrieved candidates. Fixes all
   four v5 ranking failures: retrieval-alone goes from `pass@1` 0.357 → **1.000**
   and `pass@5` 0.595 → **1.000** (`forall_inst` pass@1 0.00 → 1.00,
   `exists_elim_conj`/`neg_exfalso`/`neg_imp_exfalso` recovered). A `no-structural`
   ablation collapses back to ~v5 (structural terms are the cause). Ranking, not
   reasoning — still example reuse, no templates, no `state_after`, no LLM.
9. ~~**Mini-ELF v7**: retrieval under donor scarcity (family/operation holdout).~~
   **Done** (`src/mini_elf_lean/retrieval_splits.py`, `retrieval_abstraction.py`,
   `retrieval_abstraction_proposer.py`, `scripts/{audit_retrieval_donors,build_planner_blind_retrieval_splits,evaluate_retrieval_v7}.py`;
   [`V7_RETRIEVAL_HOLDOUT_REPORT.md`](V7_RETRIEVAL_HOLDOUT_REPORT.md),
   [`V7_DONOR_AVAILABILITY_AUDIT.md`](V7_DONOR_AVAILABILITY_AUDIT.md)). Built a
   donor-scarcity gradient (interpolation → k-shot → literal-holdout →
   family-holdout → operation-holdout → 0-shot) and measured v5/v6 + an
   abstraction re-ranker with real lean-cli. **Result:** the determinant of
   success is the *presence vs. absence* of a same-family donor, not its quantity
   — ≥1 donor ⇒ pass@5 0.91–1.00, **zero** ⇒ **0.00** for every config.
   `cross_family_verified = 0` everywhere: v6's interpolation 1.00 is same-family
   reuse (forbid-same-family on the same split → 0.00), and the family/operation
   holdouts collapse to 0.00 because the donor pool simply lacks the proof.
   Role-based **re-concretisation** (template-free) helps only the *scarce*
   same-family regime (`kshot_1` pass@1 0.832 → 0.924). The wall is **donor
   coverage**, not ranking.
   - **Part 5 (tiny learned scorer): SKIPPED, justified.** No learnable headroom —
     positives are saturated where same-family donors exist (pass@k ≈ 1.0) and
     entirely absent where they do not (family/operation holdout = 0.0, no positive
     to rank toward). A pair ranker cannot cross the donor-coverage wall; the
     bottleneck is data + adaptation mechanism, not ranking. Re-open only if the
     corpus grows enough that *some* cross-family donor genuinely verifies.
10. ~~**Mini-ELF v8** — generative donorless proposer.~~ **Done**
    (`src/mini_elf_lean/{proof_block_dataset,proof_block_seq2seq,proof_block_cleaner,v8_fusion}.py`,
    `scripts/{extract_donorless_targets,build_proof_block_dataset,train_proof_block_seq2seq,evaluate_proof_block_seq2seq,evaluate_mini_elf_v8,analyze_v8_failures,summarize_v8,run_llm_donorless_pilot}.py`;
    [`V8_GENERATIVE_PROPOSER_REPORT.md`](V8_GENERATIVE_PROPOSER_REPORT.md),
    [`V8_DONORLESS_TARGETS.md`](V8_DONORLESS_TARGETS.md),
    [`V8_FAILURE_EXAMPLES.md`](V8_FAILURE_EXAMPLES.md),
    [`V8_LLM_DONORLESS_PILOT_SKIPPED.md`](V8_LLM_DONORLESS_PILOT_SKIPPED.md)).
    Built a 690-row pooled proof-block dataset (basic + hard + planner_blind) under
    four regimes (interpolation / family_holdout / operation_holdout / donorless_eval),
    trained the v0 AR seq2seq architecture under each regime (18 models, ~2 min each
    on CPU), and lean-verified beam top-10 candidates with a source-aware fusion
    policy that flips priorities by donor availability.
    - **The seq2seq is the first model in the project to verify any
      `cross_family_verified` candidate at all** — v7 retrieval was structurally
      zero. The wins are tiny and concentrated in `exists_reconstruct` (whose
      proof shape overlaps the basic-corpus `exists_witness` training set), so
      the empirical answer is "training-distribution overlap helps a little;
      genuine cross-family abstraction was not learned at this scale".
    - **LLM pilot SKIPPED honestly** — no `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in
      env. The script + prompt + verifier are wired and ready; the result is
      reported as `skipped`, not as `0.00`.
    - **Honesty caveats**: no `state_after`, no hand-written templates as the
      main solution (v3 templates remain as a labelled candidate source in
      `full_fusion`), no manual oracle counted as a model result, no interpolation
      vs holdout comparison without caveats, v0–v7 results untouched.
11. ~~**Mini-ELF v9** — eval-matrix completion, LLM pilot, data-scaling plan.~~
    **Done** (`scripts/build_v8_full_matrix.py`,
    `scripts/run_v9_llm_donorless_pilot.py`, `scripts/build_v9_corpus.py`;
    [`V8_FULL_EVAL_MATRIX.md`](V8_FULL_EVAL_MATRIX.md),
    [`V9_LLM_DONORLESS_REPORT.md`](V9_LLM_DONORLESS_REPORT.md),
    [`V9_DATA_SCALING_PLAN.md`](V9_DATA_SCALING_PLAN.md)).
    - **Step 1 — V8_FULL_EVAL_MATRIX.md.** Walks both v8 eval-output trees,
      reports measured pass@k per cell, and explicitly marks unmeasured
      cells as `—` rather than as `0.000`. Re-runnable; rebuilds from disk.
    - **Step 2 — LLM pilot SKIPPED honestly.** No `ANTHROPIC_API_KEY` /
      `OPENAI_API_KEY` was present. `run_v9_llm_donorless_pilot.py` (focused
      on the v8 zeroes: `forall_inst`, `instantiate_forall`, `rewrite_succ`,
      `neg_imp_exfalso`, `donorless_eval`) detected the absence and emitted
      `V9_LLM_DONORLESS_REPORT.md`. Never faked as `pass@k = 0.00`.
    - **Step 3 — data-scaling plan + verified corpus skeleton.** Designed an
      operation×family redundancy table (≥3 sibling families per operation),
      sketched a LeanDojo/`Init` integration path, and implemented
      `scripts/build_v9_corpus.py` emitting a 10-theorem proof-of-concept
      (2 operations × 5 families). Each cell's closing tactic is **lean-cli
      verified before commit** (10/10 verified, 0 refused — no fake corpus).
    - **No new model pass@k measured in v9.** v10 will retrain the seq2seq
      on the scaled corpus and re-run the v8 eval loop.
12. **Mini-ELF v10** (complete, with mid-flight methodology correction):
    operation×surface-family redundancy corpus + scaled retraining of
    the v8 seq2seq.
    - **40 verified cells** across 8 proof operations × 5 surface
      families. The 8 cells initially refused as WSL/lean cold-start
      timeouts all verified on rerun with `--timeout 180`;
      `data/traces/redundancy_lean_cli_failed.jsonl` is now empty.
    - **Major leakage bug discovered and corrected.** The legacy
      `combined_v10` (trained on the v10 interpolation split) had 36 of
      40 holdout test theorems in its training pool; the prior draft's
      "combined_v10 wins 5/8 op-holdouts" headline was measuring
      in-distribution memorisation, not generalisation. Pinned by
      `tests/test_v10_no_leakage.py`.
    - Replacement: 8 per-operation LOFO models trained from scratch
      with the held op's v10 cells excluded
      (`scripts/build_combined_v10_per_op.py` +
      `scripts/train_combined_v10_per_op.sh` +
      `scripts/eval_combined_v10_per_op.sh`). Clean per-op metrics live
      at `data/baselines/v10_eval_clean/per_op/<op>/`.
    - **Clean signal (16/16 cells)**: mean pass@5 0.600 for
      `combined_v10_per_op` vs 0.575 for `baseline_v8` (zero-shot, never
      saw v10) — Δ +0.025; per-fold 2 wins / 1 loss / 5 ties; total
      `cross_operation_verified` 39 vs 34 (+5). Small, mixed positive
      contribution; not the dramatic uniform lift the leaked draft
      claimed.
13. **Mini-ELF v11** (complete): clean per-family LOFO with v10 redundancy
    — the direct negative-control test.
    - 5 per-family LOFO regimes built
      (`scripts/build_v11_family_lofo.py`): train = v8 family-LOFO + 40
      v10 cells minus held-test duplicates; test = the v8
      `family_holdout/<fam>/test.jsonl` rows verbatim (apples-to-apples
      vs v8 numbers).
    - 5 leakage-guard tests in `tests/test_v11_family_lofo_no_leakage.py`
      (theorem-name disjointness, `(state_before, tactic)` disjointness,
      held-family planner_blind absent from train).
    - 5 per-family seq2seq models trained
      (`scripts/train_v11_family_lofo.sh`).
    - Headline: **`rewrite_succ` 0/5 → 4/5 pass@5 (+0.800)**,
      **`forall_inst` 0/7 → 1/7 (+0.143)** (both v8 negative controls);
      `exists_reconstruct` 0.400 → 0.800; `neg_exfalso` precision lift
      (pass@1 0.125 → 0.625) at unchanged recall; `neg_imp_exfalso`
      unmoved. `novel_verified = 0` on every win (the v10 siblings
      supply the tactic string; v11 copies it).
    - One `rewrite_succ` row also emitted `rw [h]` at rank 0 but the
      verifier hit a 20 s cold-start timeout — reported honestly as
      0.800, not 1.000.
14. **Mini-ELF v12** (complete): literal-aware decode + rule-based
    reranker — post-generation processing on the v11 model's beam.
    - `src/mini_elf_lean/literal_aware_decode.py` substitutes the first
      goal literal into `exact <ident> <num>` / `exact ⟨<num>, rfl⟩`
      schemas; tagged `source = seq2seq_literal_adapt`; no
      `state_after`, no manual oracle, no model retrain.
    - `src/mini_elf_lean/proof_block_reranker.py` rule-based reranker
      scores candidates on goal-literal match, stale-literal penalty,
      malformed penalty, schema match, source priority, length and
      beam-rank tie-breaks.
    - Headline (clean v11 family-LOFO test rows, lean-cli pass@5):
      **`forall_inst` 1/7 → 3/7 (+0.286)**, **`exists_reconstruct`
      4/5 → 5/5 (+0.200)**, `rewrite_succ` preserved at 0.800 (brief
      floor), `neg_exfalso`/`neg_imp_exfalso` unchanged.
    - 3 of the 4 remaining `forall_inst` failures emit the correct
      adapted candidate at rank 0 but lean-cli cold-start timed out —
      reported as FAIL (honest lower bound; NOT retconned to 6/7).
    - Tokenization analysis at `docs/V12_TOKENIZATION_NOTE.md`; v13
      defers the actual tokenizer change.
15. **Mini-ELF v13** (complete): warm-verifier rerun + tactic-token
    tokenizer prototype. No model retraining; v12 metrics on disk
    preserved untouched.
    - **Warm rerun confirmed v12's honest lower bound was a 20-s
      verifier-timeout noise floor** — the 3 timed-out `forall_inst`
      adapted candidates (`exact h 5`, `exact h 13`, `exact h 8`) and
      `rewrite_succ_ij`'s `rw [h]` all verify at `timeout=120 s` after
      one warm-up theorem. Corrected `forall_inst` pass@5 **3/7 →
      6/7 (+0.428)**; corrected `rewrite_succ` pass@5 **4/5 → 5/5
      (+0.200)** across every config. v12 lower-bound numbers
      remain pinned on disk; corrected numbers live at
      `data/baselines/v13_timeout_rerun/metrics_rerun.json`.
    - **Tactic-token tokenizer prototype** at
      `src/mini_elf_lean/tactic_tokenizer.py`: lossless round-trip,
      explicit `KEYWORD`/`IDENT`/`NUMBER`/`SYMBOL`/`PUNCT`/`WS`
      classes, vocabulary builder, encode/decode with `BOS`/`EOS`/
      `PAD`/`UNK` ids. Unit tests at `tests/test_tactic_tokenizer.py`
      pin the round-trip, keyword-vs-IDENT distinction, and the
      truncation patterns (`exact h.`, `rw [hns`, `cases h wi`,
      `refintro hn`, `rwexact h`).
    - **Residual `forall_inst_var_m` failure** remains. Its beam is
      dominated by `rcases h wi`, `refintro hn/hq`, `rwexact h`,
      `refin rfl⟩` — char-truncation patterns the v13 tokenizer
      module exists to prevent at v14 train time.
    - Full report:
      [`V13_TIMEOUT_RERUN_REPORT.md`](V13_TIMEOUT_RERUN_REPORT.md),
      [`V13_TOKENIZATION_DECISION.md`](V13_TOKENIZATION_DECISION.md).
16. **Mini-ELF v14** (complete): token-level seq2seq retrain. Same
    v11 family-LOFO folds; same v12 literal-adapt + reranker; same v13
    warm verifier (extended to 180 s in v14 timeout rerun); same
    (bi)GRU+attention architecture, ~484k params, CPU.
    - **`forall_inst_var_m` solved** under v14 + LA + warm — closes
      the v13 residual char-truncation case. `forall_inst` pass@5 =
      **7/7 = 1.000** (v13 char + warm = 6/7).
    - **`neg_imp_exfalso` cracked** under v14 raw beam — pass@5 =
      **12/15 = 0.800** (v13 = 0/5). Mechanism: token model
      composes `intro hp` (from many implication families in train)
      with `exact absurd hp hnp` (from 7 sibling negation families)
      → cross-family compositional novelty.
      `novel_verified=12`.
    - **Token-level invariant achieved**: 0 fused-keyword tokens
      (`refintro`/`rwexact`/`casexact`/`introexact`) across all 5
      families × beam=10 = 350 candidates.
    - **The v12 reranker mis-calibrates** on the new contrapositive
      shape (raw 0.800 → +LA+rerank 0.200; pass@10 = 1.000). This is
      a reranker design limit, not a model defect.
    - v12 and v13 metrics on disk are NOT overwritten. v14 warm
      numbers live at `data/baselines/v14_timeout_rerun/`.
    - Full report:
      [`V14_TOKEN_SEQ2SEQ_REPORT.md`](V14_TOKEN_SEQ2SEQ_REPORT.md),
      [`V14_CHAR_VS_TOKEN_REPORT.md`](V14_CHAR_VS_TOKEN_REPORT.md),
      [`V14_FAILURE_EXAMPLES.md`](V14_FAILURE_EXAMPLES.md).
17. **Mini-ELF v15** (complete): learned reranker + operation-aware
    policy. Pure rerank-only change. v14 metrics on disk untouched.
    - **`neg_imp_exfalso` pass@5 0.200 → 0.800** by routing
      `intro_negation` rows to the learned reranker (the rule
      reranker pushes contrapositives past top-5; learned keeps
      them at rank 3-4). The residual `neg_imp_exfalso_ab` row is
      generator-bound at rank 6 — needs v16 generation work to
      close to 1.000.
    - **Mean pass@5 0.765 → 0.885 (+0.120); mean pass@1 0.514 →
      0.725 (+0.211); pass@10 ceiling preserved at 0.925.**
    - Audit finding: **rule and learned win disjoint operations**
      (rule dominates `instantiate_forall`/`rewrite`; learned
      dominates `intro_negation`/`unknown`). The policy router is
      the win.
    - Pure-Python sparse logistic regression — no sklearn, no
      torch. ~230 features per fold, 2s training, deterministic.
    - Full report:
      [`V15_LEARNED_RERANKER_REPORT.md`](V15_LEARNED_RERANKER_REPORT.md),
      [`V15_NEG_IMP_EXFALSO_RERANK_ANALYSIS.md`](V15_NEG_IMP_EXFALSO_RERANK_ANALYSIS.md),
      [`V15_FAILURE_EXAMPLES.md`](V15_FAILURE_EXAMPLES.md).
18. **Mini-ELF v16** (complete): contrapositive corpus augmentation
    + token seq2seq retrain. Generator-side change; v15 reranker/
    policy unchanged. v12–v15 metrics on disk untouched.
    - **`neg_imp_exfalso_ab` rank 6 → 0**, taking `neg_imp_exfalso`
      pass@5 from 0.200 → **1.000** with three verified candidates
      in top-5. Headline brief target hit.
    - **Collateral lift: `neg_exfalso` pass@5 0.625 → 0.875** as
      the model generalised the `(h hp).elim` form from the
      contrapositive corpus to two `neg_exfalso_arrow_*` rows.
    - Mean pass@1 0.514 → **0.875** (+0.361); mean pass@5 0.765 →
      **0.975** (+0.210); **mean pass@10 0.925 → 0.975 (+0.050)** —
      pass@10 lift is the strongest evidence of a real generator
      improvement (pass@10 = the union of verified candidates,
      unaffected by reranking).
    - 287 verified train rows across 3 surface families (classic /
      neg_imp / false_target), disjoint variable names, both
      leakage guards report 0 drops.
    - All v15 wins preserved (forall_inst / rewrite_succ /
      exists_reconstruct stay at 1.000 pass@5).
    - Full report:
      [`V16_CONTRAPOSITIVE_AUGMENTATION_REPORT.md`](V16_CONTRAPOSITIVE_AUGMENTATION_REPORT.md),
      [`V16_GENERATOR_BOUND_FAILURE_AUDIT.md`](V16_GENERATOR_BOUND_FAILURE_AUDIT.md),
      [`V16_FAILURE_EXAMPLES.md`](V16_FAILURE_EXAMPLES.md).
19. **Mini-ELF v17** (complete): arrow_false_elim corpus + policy
    edit. Two targeted changes:
    - **Policy edit**: `contradiction` moved from `USE_DEFAULT_RULE`
      to `USE_LEARNED` in `v15_rerank_policy.py`. Lifts neg_exfalso
      pass@1 0.375 → 0.625 on v16 candidates and 0.500 → 0.750 on
      v17 candidates.
    - **Corpus augmentation**: 137 lean-cli-verified
      `arrow_false_elim` rows (`(p q : Prop) (h : p → False)
      (hp : p) : q` with proof `exact (h hp).elim`) close the v16
      residual `neg_exfalso_arrow_pq` row. v17 retrains the token
      seq2seq for `neg_exfalso` only; other folds reuse the v16
      model.
    - **Headline on the templated v11 family-LOFO benchmark**:
      all 30 unique test rows verify at pass@5. Mean pass@1 0.875
      → 0.950, mean pass@5 0.975 → 1.000, mean pass@10 0.975 →
      1.000. `neg_exfalso_arrow_pq` first verified rank
      "—" → **1** (`exact absurd hp h` rank 1, `exact (h hp).elim`
      rank 2 in the v17 raw beam).
    - Full report:
      [`V17_ARROW_FALSE_ELIM_REPORT.md`](V17_ARROW_FALSE_ELIM_REPORT.md),
      [`V17_RESIDUAL_FAILURE_AUDIT.md`](V17_RESIDUAL_FAILURE_AUDIT.md),
      [`V17_FAILURE_EXAMPLES.md`](V17_FAILURE_EXAMPLES.md).
20. **Mini-ELF v18** (complete): broad-core transfer test. v17
    pipeline evaluated zero-shot on a 48-theorem hand-authored
    core-Lean benchmark spanning 10 categories; Mathlib skipped
    honestly (env lacks Mathlib).
    - **Headline (the honest answer to "how much of v17
      transfers"):** roughly half. v17 panel + v17 policy on v18
      reaches **pass@5 = 0.500, pass@10 = 0.583**. A single broad-
      synthetic model trained on the union of v11+v16+v17 corpora
      (1151 rows) **outperforms the v17 panel** at every metric
      (pass@1 0.292→0.500, pass@5 0.500→0.583, pass@10
      0.583→0.604) — the v17 family-LOFO specialists were
      over-fit; broader training generalises better even on the
      same data.
    - **The wall is categorical, not gradient.**
      `equality_rewrite` 1.000 / `conjunction` 0.833 / `list`
      0.800 / `negation` 0.800 transfer cleanly. `implication`
      0.000 and `bool` 0.000 are **total misses** — corpus-shape-
      bound (no synthetic training for those shapes).
    - **Dominant failure class: `unknown_identifier`** — v17 names
      identifiers (`h`, `hp`, `hnp`) from its training
      distribution; v18 introduces unfamiliar names (`xs`, `b`,
      `hImp`, `prf`) and the model references unbound symbols.
    - v12-v17 metrics on disk untouched; v18 publishes at
      `data/baselines/v18_*/`.
    - Full report:
      [`V18_ZERO_SHOT_TRANSFER_REPORT.md`](V18_ZERO_SHOT_TRANSFER_REPORT.md),
      [`V18_BENCHMARK_DESIGN.md`](V18_BENCHMARK_DESIGN.md),
      [`V18_BROAD_CORE_REPORT.md`](V18_BROAD_CORE_REPORT.md),
      [`V18_FAILURE_EXAMPLES.md`](V18_FAILURE_EXAMPLES.md).
21. **Mini-ELF v19** (complete, **negative result**): tested
    state-aware identifier abstraction. Full pipeline built and
    tested; v18 broad-synthetic+policy pass@5 = 0.583;
    v19 abstract-only+policy pass@5 = **0.208**; v19 ensemble =
    **0.312**. `unknown_identifier` did drop (127→~30) but was
    replaced by `unresolved_placeholder` at 210/480 slots (44 %)
    — worse exchange. Categorical regressions: conjunction
    0.83→0.17, list 0.80→0.20. Three root causes documented
    (placeholder-dropout, over-aggressive dedup, no
    tactic-introduced-binder tracking). Local-context parser +
    abstraction module + dataset round-trip work correctly (0
    failures across 3984 synthetic rows); the v19 abstract model
    trains to val_exact=0.26 — the problem is *transfer*, not
    in-distribution accuracy. Honest negative finding logged per
    the v19 brief.
22. **Mini-ELF v20** (complete): closed both confirmed v18
    data-shape gaps and added ranker-time abstraction. Implication
    **0.000 → 1.000**, bool **0.000 → 1.000**; mean pass@1 0.500 →
    0.625, pass@5 0.583 → 0.729, pass@10 0.604 → 0.729 (timeout-
    corrected best config). The pass@10 lift confirms a real
    generator change. The ranker-time abstract-pattern reranker is
    the best config and produces **0** unresolved-placeholder errors
    (vs v19's 44 %). Honest negative: **forall regressed 0.667 →
    0.000** (single-model capacity tradeoff from the
    implication-heavy corpus). v18/v19 metrics on disk unchanged.
    See `V20_BROAD_TRANSFER_REPORT.md`.
23. **Mini-ELF v21** (complete): recovered the v20 forall regression
    via **model routing**. forall **0.000 → 1.000**, implication/bool
    preserved at 1.000, mean pass@5 0.729 → **0.792**. Compared four
    fixes; **routing (C, zero collateral) > higher-capacity (D, 0.771,
    loses exists) > single-retrain (B, 0.729, relocates the tradeoff
    to disjunction/negation/exists) = v20**. Confirmed the regression
    was a single-model capacity tradeoff (instantiation schema absent
    from generation). Honest caveat: routing is composition-of-
    specialists, not a single general model. Safe repo checkpoint
    taken first (repo mid-paused-rebase, untouched). v18/v20 metrics
    unchanged. See `V21_FORALL_RECOVERY_REPORT.md` +
    `V21_CAPACITY_TRADEOFF_ANALYSIS.md`.
24. **Mini-ELF v22** (complete): answered v21's open **general-model
    question** — *can one model serve all broad-core categories without
    the tradeoff, or is routing necessary?* **A single model suffices.**
    Folded a **471/471 lean-cli-verified exists corpus** (6 shape
    families) into the v21 pool and trained four single models
    (pool × capacity). **`v22_general_plus_exists`** (one decoder, **no
    router**) **beats v21 routed**: pass@5 0.792 → **0.812**, pass@10
    0.792 → **0.833**, MRR 0.728 → 0.774, no_verify 10 → 8 — forall/
    implication/bool held at 1.000, **exists 0.250 → 0.750**. Key negative
    findings: **oversampling and larger capacity did NOT help** (both
    regressed nat_succ/list; `balanced_large` gets exists=1.0 but breaks
    implication/disjunction). The residual gap was a **data-shape coverage
    gap**, not imbalance or capacity — **routing was a proxy for missing
    exists/forall shapes**. v18/v20/v21 metrics unchanged; no state_after,
    no manual oracle, no Mathlib, no v10-leakage revival. See
    `V22_GENERAL_MODEL_REPORT.md` + `V22_CATEGORY_INTERFERENCE_ANALYSIS.md`.
25. **Mini-ELF v23** (complete): refreshed the reranker on a pooled
    6,011-row v16–v22 candidate-outcome dataset (grounding features:
    unbound-identifier penalty + locally-bound-name awareness, abstract-
    pattern feature, category cues), **ranking-only**, offline on the
    fixed v22 plus_exists pool, leave-one-theorem-out. **Honest negative:
    no reranker beats `raw`** (the v22 generator's beam is already best —
    pass@1 0.792 / pass@5 0.833); the learned LR over-demotes (pass@1 →
    0.688), the conservative hybrid recovers to 0.771 (net −1). v23 *does*
    beat the v22 `abstract` headline (hybrid pass@5 0.812 → 0.833,
    negation 0.600 → 0.800) — the negation regression was purely the
    abstract reranker, **so retire it**. Decisive: the residual gap is
    **generator-bound** (39/48 solved@1, 1 ranking-bound & feature-
    unfixable, 8 generator-bound). v22 metrics unchanged; ranker-time
    abstraction scoring-only; no state_after/manual-oracle/Mathlib. See
    `V23_LEARNED_RERANKER_REFRESH_REPORT.md` + `V23_GENERATOR_BOUND_AUDIT.md`.
26. **Mini-ELF v24** (complete): added a **163/163 lean-verified core-Lean
    shape corpus** (8 families, one per v23 generator-bound failure) to the
    v22 pool and retrained the broad generator (no ranking work, no
    Mathlib). **Closed 5 of 8 generator-bound failures**: pass@10
    0.833 → **0.938** (no_verify 8 → 3), pass@5 (abstract) 0.812 → **0.917**.
    Per-category (abstract): negation 0.600 → 1.000, exists 0.750 → 1.000,
    list 0.800 → 1.000, nat_succ 0.600 → 0.800; forall/impl/bool/eq stay
    1.000; **zero category regressions**. The `abstract` reranker (harmful
    in v22) is now v24's best config and recovers `neg_not_intro` —
    grounded candidates make ranking safe. v18/v22/v23 metrics unchanged;
    core Lean only; no state_after/manual-oracle/v10-leakage. See
    `V24_BROAD_GENERATOR_REPORT.md` + `V24_RESIDUAL_ROW_RESULTS.md`.
27. **Mini-ELF v25** (complete): **first real Mathlib tier-C probe.** Mathlib
    **v4.30.0** installs cleanly (external scratch project, `lake exe cache`
    auto-fetch, 7.4 G oleans) and imports — **no environment wall**. Built a
    **36-theorem, 103-candidate Mathlib-verified** tier-C benchmark
    (`lake env lean`, `import Mathlib`; 0 timeouts, 0 zero-success). **v24
    zero-shot transfers bimodally**: pass@10 0.556 overall, but **0.812 on
    core-shaped** Mathlib theorems vs **0.350 on Mathlib-lemma-needing** ones
    (all 5 Set theorems unreachable). Failure is **generator coverage**
    (164 `unknown_identifier` + theorem-shape gaps), **not** environment
    (0 import errors). A **tiny 68-row verified Mathlib augmentation improves
    held-out transfer** (pass@10 0.571 → **0.786**, +3 theorems, 0 lost) — but
    naive co-training **regresses v18 broad-core** (pass@10 0.938 → 0.833,
    protected `bool` 1.000 → 0.667). **So v24 stays the broad-core model; the
    augmented model is not adopted.** See `V25_ZERO_SHOT_TIERC_REPORT.md`,
    `V25_TIERC_AUGMENTATION_REPORT.md`, `V25_BROADCORE_REGRESSION_REPORT.md`.
28. **Mini-ELF v26** (complete): **Mathlib coverage via specialist + router,
    no broad-core cannibalisation.** v25 established Mathlib availability and
    partial transfer; v25 co-training improved Mathlib but **regressed
    broad-core** — v26 tests a separate specialist + router instead.
    - **Built + Lean-verified a 237-row Mathlib specialist corpus** (93 tiny
      theorems, 6 categories, **54 Set / 37 order rows**) using a new **batched
      `import Mathlib` verifier** (`mini_elf_lean.mathlib_verifier`: direct
      v4.30.0 binary + precomputed `LEAN_PATH`, ~60× faster than v25's
      per-candidate `lake env lean`; gold-tested **0 mismatches vs
      one-example-per-file**).
    - **Mathlib specialist (`v26_base`, Mathlib-only, 149 train rows)** lifts the
      v25 held-out tier-C pass@10 **0.786 → 0.929** and reaches **0.909** on a
      fresh 22-theorem holdout. **Set goals (v24 = 0.00, "unreachable") now
      reach 0.50–1.00**; mathlib-lemma transfer 0.20 → 0.87. `plus_core`
      (Mathlib + small core) was **worse** → adopt pure-Mathlib specialist; the
      `large` config was unnecessary (no underfitting).
    - **Router** (`v26_mathlib_router`: `import Mathlib`/flag → specialist, else
      v24) **preserves broad-core** (routed p@5/p@10 = 0.938/0.958, `bool` 1.00)
      while lifting tier-C to 0.917 — vs v25 co-training's **regressed** 0.833.
    - **Set widening pass** (Part 9, executed): +47 verified Set-shape rows lifted
      held-out Set **0.50 → 0.75** (p@1 0.50 → 0.77) with **zero** other-category
      regression → `v26_widened` recommended. Residual Set bottleneck is
      **proof-shape diversity**, not capacity/vocabulary/environment.
    - See `V26_REPO_STATUS.md`, `V26_MATHLIB_FAILURE_AUDIT.md`,
      `V26_MATHLIB_SPECIALIST_{CORPUS,DATASET,EVAL}_REPORT.md`,
      `V26_ROUTED_SYSTEM_REPORT.md`, `V26_MATHLIB_CATEGORY_ANALYSIS.md`,
      `V26_FAILURE_EXAMPLES.md`.

29. **Mini-ELF v27** (open): from the v26 bottleneck analysis —
    - **Scale the Set/Mathlib-lemma corpus** further (the widening pass proved
      a few dozen verified rows move held-out Set; volume is the lever).
    - **More Mathlib categories** (Finset, function injectivity, simple algebra)
      behind the router; measure where the specialist's vocabulary runs out.
    - **The 1 unclosed broad-core shape** (`or_elim_to_common`) + the
      `and_assoc_one` parse case — still shape-diversity-bound.
    - **Real next-state supervision** via LeanDojo `run_tac` unblock.
    - Carried: cell_holdout clean matrix (40 per-cell LOFO) from v10;
      donorless_eval × 3 v10 models; LLM pilot if a key arrives;
      v3 `∃ _, p ∧ q` parser fix.
    - **Resolve the paused rebase** (the repo has carried an in-progress
      `rebase -i` of `main` since 2026-05-28; v13–v26 all layered on top).
      A deliberate, user-authorized `git rebase --continue` (or `--abort`)
      + commit is warranted — but only on explicit request. **v26 left it
      untouched and committed nothing.**

## What NOT to claim yet

- ❌ "Real proof-state transition modeling" — all verification is theorem-level;
  `state_after_is_real=false` everywhere, AR and Mini-ELF v0 included.
- ❌ "Mini-ELF / ELF solved" or "real embedded proof-state flow" — Mini-ELF v0/v1
  are small **prototypes of the generation loop**, not the full method; they
  operate on tactic-string latents, not proof states.
- ❌ "Mini-ELF v1's witness-copy is neural open-vocabulary generation" — it is an
  explicit **symbolic** augmentation (copy a literal into `exact ⟨N, rfl⟩`),
  evaluated honestly by the same Lean verifier but not learned generation.
- ❌ "v1's reranker is well-calibrated in general" — its clean verified/failed
  separation is on a small, templated corpus and uses self-training on v1's own
  train-split candidates; v2 shows it **mis-calibrates off-distribution** (failed
  scores rise 0.25 → 0.45–0.59 under shift).
- ❌ "Mini-ELF v1 generalizes" — it **does not**. v2 shows `pass@5` 0.95 →
  0.00–0.23 under distribution shift (the basic numbers reflect template
  coverage). v2's recovery is **in-distribution-hard only**; compositional
  (difficulty) holdout stays 0.06 and basic regresses to 0.82.
- ❌ "v2 beats v1" — v2 trades basic-corpus precision (0.95 → 0.82) for hard-corpus
  coverage; it is a generalization *study*, not a strictly-better model.
- ❌ "Mini-ELF v3 *learns* compositional generalization" — it does **not**. v3's
  `difficulty_holdout` `pass@5` 0.06 → 1.00 is from a **symbolic, hand-written
  planner** that constructs proofs from the parsed goal; it is indifferent to the
  train/test split and would fail on any proof shape outside its template
  library. It is engineered *coverage*, not learned generalization.
- ❌ "v3 solves theorem proving / the planner is general" — the planner covers
  exactly this corpus's closed family of proof shapes (chains, projection, case
  splits, iff/eq composition, `∃`-witness). New structure ⇒ no template ⇒ failure.
  **v4 demonstrates this directly**: on the planner-blind corpus every unchanged
  system (AR/v1/v2/v3) drops to `pass@5` ≤ 0.096.
- ❌ "the v4 template ablation shows the system *learned* the new families" — it
  shows the opposite. Each added template is a hand-written symbolic rule; it
  takes its target family 0.00 → 1.00 and **nothing else** (`forall_inst` /
  `rewrite_succ` stay 0.00 with no template). It quantifies engineered coverage,
  not reasoning. The v4 templates are explicitly labelled and **not** part of v3.
- ❌ "Mini-ELF v5's retrieval proposer *reasons* / *generalizes compositionally*"
  — it does **not**. It is **example reuse + light adaptation**: it copies a
  verified tactic from a same-family training donor (verbatim, because the corpus
  uses constant hypothesis names within a family) and at most substitutes a
  numeric literal copied from the goal. It solves `forall_inst` / `rewrite_succ`
  only because such donors exist in the `family_interpolation` train split; it
  does **not** compose new proof shapes and has **no** notion of why a tactic is
  correct.
- ❌ "v5 beats v4 templates" — different axes. On the split, v4-templates reaches
  pass@5 0.821 (negation/∃-elim families) while retrieval reaches 0.595 but solves
  the **template-less** targets templates cannot. They are **complementary**
  (fusion → 1.00), not a ranking. The v5 split test set (32 theorems) is **not**
  the v4 all-test set (61), so the numbers are not directly comparable.
- ❌ "v5's retrieval is robust" — it inherits the v1 **sibling-confusion** failure
  at the retrieval layer: char-n-gram similarity ranks a wrong-family or
  wrong-direction donor above the correct one, so `neg_exfalso` stays at pass@5
  0.00 and `exists_elim_conj` at 0.25 (`docs/V5_FAILURE_EXAMPLES.md`).
- ❌ "the v5 LLM pilot was run" — it was **skipped** (no API key) and wrote
  `docs/V5_LLM_PILOT_SKIPPED.md`; no LLM metric is reported. The `llm` config's
  all-zero numbers mean "no candidates produced", not a measured capability.
- ❌ "v5 has a learned proof-block model" — **deferred** to v6
  (`docs/V5_LEARNED_PROPOSER.md`); no model is trained or shipped.
- ❌ "Mini-ELF v6 *reasons* / does proof search" — it does **not**. v6 only
  **re-ranks the same retrieved candidates** with heuristic structural features;
  it constructs no proofs and adds no templates. The `no-structural` ablation
  collapsing to ~v5, and its dependence on same-family donors, show it is example
  reuse with a better ranking — not reasoning.
- ❌ "v6 generalizes to unseen proof shapes" — untested and unlikely. v6 is
  evaluated on the `family_interpolation` split where every family has same-family
  donors; with **no** donor it has nothing correct to rank. A family-holdout probe
  (v7) is needed before any generalization claim.
- ❌ "v6 fusion ≥ v6 retrieval-alone" — on `exists_elim_conj` pass@1 the fusion is
  **worse** (0.50 vs 1.00) because v3's unfixed `∃, ∧` parser mis-fires `exact h.2`
  into the top slot; v3 is deliberately left unchanged in v6.
- ❌ "v6's adapted-preference penalty is load-bearing" — the `no-adapt-pref`
  ablation is unchanged; the adapted-first + LHS-first tie-break already fixes
  `forall_inst` pass@1. The explicit stale-literal penalty is belt-and-suspenders
  on this corpus.
- ❌ Any v5/v6 metric not backed by a generated `metrics.json`; the v6 split test
  set (32) is **not** the v4 all-test set (61) and the two are not comparable.
- ❌ "Mini-ELF v7 shows retrieval generalizes across families" — it shows the
  **opposite**. With no same-family donor (`family_holdout` / `operation_holdout`),
  every config — v5, v6, and the v7 abstraction re-ranker — scores `pass@5`
  **0.00**, and `cross_family_verified = 0` on every split. Retrieval can only
  return a proof already in the donor pool.
- ❌ "v6's planner-blind 1.00 is generalization" — it is **interpolation**.
  Forbidding same-family donors on the *same* split drops v6 to **0.00**; v7's
  family-holdout (donors genuinely removed from train) confirms 0.00. The v7
  holdout numbers are **not comparable** to v6's interpolation 1.00.
- ❌ "v7's abstraction enables cross-family transfer" — role re-concretisation
  helps only the **same-family scarce** regime (`kshot_1` pass@1 0.832 → 0.924, all
  arrow-form negation hyps re-bound to a *same-family* donor). It never produces a
  verified cross-family candidate; it reuses + re-binds an existing donor proof, it
  does not synthesise a missing one. It is **not** a template and reads **no**
  `state_after`.
- ❌ "v7 trained a learned scorer" — **skipped** (justified: no learnable headroom;
  see roadmap item 9). No model is trained or shipped in v7.
- ❌ "Mini-ELF v8 generalizes across all families" — the seq2seq verifies
  **5/8 held `neg_exfalso` theorems with 9 *novel* verified tactic strings**
  (composing the token `absurd` from sibling negation families with the
  hypothesis names `hp`/`hnp`), but the **negative control**
  `family_holdout/forall_inst` (whose flat `exact h N` shape has no
  token-compatible cousin in train) stays at **0/7**. The mechanism is
  *composing tokens learned from sibling families*, not abstract
  generalization to genuinely unseen proof shapes. On the strictest regime
  `donorless_eval` (no PB family in train at all) the model verifies only
  3/61 via training-distribution slot-fill (`novel_verified = 0`). v9 wall:
  breadth of sibling-family coverage in training.
- ❌ "Mini-ELF v8 ran an LLM proposer" — **skipped** (no API key). Reported as
  `skipped`, not as `0.00`. The script + prompt + verifier are wired and
  ready (`scripts/run_llm_donorless_pilot.py`) but require
  `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` to activate.
- ❌ "v8 fusion strictly beats v7 retrieval everywhere" — under interpolation
  v7 retrieval still wins (it has a same-family donor); the fusion policy is
  designed to *prefer* it there. v8's contribution is on the donorless rows.
- ❌ "Mini-ELF v9 measured new pass@k" — v9 is *infrastructure* only:
  matrix summary, gated LLM pilot (SKIPPED — no key), and a verified
  10-theorem corpus skeleton. **No new model performance numbers are
  reported in v9**; the v10 retraining experiment is the next measurement.
- ❌ "Mini-ELF v9 retrained the seq2seq on the v9 corpus" — the v9 corpus
  exists and is shape-compatible with the v8 trainer, but the retraining
  experiment is explicitly v10's deliverable.
- ❌ "`exists_witness` solved" — solved at `pass@5`, **not** `pass@1` (the
  witness-copy numeric-literal-first ordering still mis-ranks `exists_hyp_copy`).
  `or_self_elim` is now solved by the v3 planner's case split (`pass@5` 1.00 on
  the hard splits), but by **symbolic construction**, not by the learned model.
- ❌ "LeanDojo works end-to-end" — tracing + initial state work; `run_tac` is
  blocked and `xfail`'d.
- ❌ "A large / pretrained / transformer model" — AR (410K) and Mini-ELF v0
  (343K) are small char-level CPU models; PyTorch is an optional extra.
- ❌ "Solved open-vocabulary generation" — AR's is **partial** (template
  composition over `{0,1,2}`); Mini-ELF's novel generations don't verify.
- ❌ "Statistically significant" gaps — 16 eval theorems/split; directional.
- ❌ Any metric not backed by a generated `metrics.json` file.
