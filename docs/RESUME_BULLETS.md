# Résumé bullets — Mini-ELF-Lean

Reusable phrasings for a CV / portfolio. All numbers match the project's
generated metrics files. Keep the honesty caveats (theorem-level, not
next-state) when space allows.

## Short (one line each)

- **Packaged a multi-month research effort into a reproducible artifact and safely
  recovered a corrupted git state.** Diagnosed a stale interactive-rebase that had been
  orphaned mid-conflict (`git pull --rebase` stopped, work then continued on another
  branch), reconstructed exactly what happened from the reflog, and cleared it with the
  *non-destructive* `git rebase --quit` — after a full `.git` backup and a written
  recovery plan — preserving HEAD, the protected model, and all artifacts. Then wrote a
  consolidated paper-style report of the full arc, an artifact inventory, a
  reproducibility guide (exact commands + expected metrics), and a consistency audit that
  programmatically re-checks the project's honesty constraints (no `state_after`, no
  full-proving claim, trusted verifier only).
- **Drove a verified-tactic generation pipeline to measured saturation and made the
  disciplined call to stop modeling.** Closed the last failure class by (a) tracing
  ~9 % of adversarial-identifier failures to a one-line parser-coverage bug (Unicode
  subscripts weren't recognized as identifiers) — fixing it lifted adversarial-stress
  pass@10 **0.89 → 1.00 across every model with zero retraining** — and (b) adding 83
  verified coverage rows. The result: **pass@10 = 1.00 on every single-tactic
  benchmark** (including adversarial-identifier and fresh-shape held-outs), **routed
  tier 0.992 over 244 theorems**, protected core model **bit-for-bit**, **0 remaining
  multi-step failures** — and a saturation analysis recommending **packaging over more
  modeling or premature RL/next-state work.**
- **Built an adversarial stress test that distinguished genuine generalization from
  memorization, and used it to make a disciplined "is this saturated?" decision.**
  To check whether an identifier-normalization fix truly generalized, generated a
  held-out benchmark of theorems with **never-seen identifiers** (Greek, subscripts,
  underscores). The normalization scored **0.89** there vs **0.26** for the raw model
  and **0.28** for a data-augmentation alternative — proving the normalization
  generalized while augmentation had only memorized specific cases. Confirmed the
  routed system preserved its protected core model bit-for-bit (0.9375/0.9583) and held
  **0.95 pass@10 on the hardest 202-theorem benchmark**, then ran a saturation analysis
  showing **every remaining failure was single-tactic (0 multi-step)** — and on that
  evidence **recommended against** premature next-state/RL work, scoping one more
  coverage pass instead.
- **Diagnosed a model's last failure class as identifier memorization and removed it
  with a safe, valid-identifier normalization — learning from a prior negative result.**
  Showed the remaining ~15 % of failures were *surface-token* out-of-distribution (the
  proof shape was learned; only the local identifier was unseen). Designed an
  identifier-canonicalization scheme that avoided an earlier project attempt's failure
  mode (placeholder abstraction had *replaced* one error class with a worse one and
  halved pass@k) by using **valid identifiers**, **unioning with the raw model
  (fallback, never replacement)**, and **rejecting unresolved tokens before the
  verifier**. Lifted the held-out residual benchmark **0.00 → 0.92** and routed tier
  **0.921 → 0.985 pass@10** with **zero new training data** and zero unresolved-token
  failures, while preserving the protected core model **bit-for-bit**. Distilled the
  result into a two-axis coverage law (family density × surface-token coverage).
- **Turned a measured scaling law into a surgical fix — recovered a regression with 155
  verified rows.** When a release traded 2/14 on a micro-benchmark, audited it to
  *beam-absence + zero training siblings*, then used the density law as a construction
  rule: added 4–6 verified siblings to only the flagged families (no broad expansion,
  no balancing). **Recovered the benchmark to 1.000 with zero regression**, lifted the
  general model to match the specialized one, and kept the protected core model
  **bit-for-bit** — while honestly reporting the one repair that *didn't* work
  (held-out members with identifiers absent from training), refining the law into a
  **token-coverage** condition.
- **Derived a quantitative "density law" for verified-data scaling and shipped it.**
  Showed that a tactic model's held-out success is a function of **within-family
  training siblings**, not category breadth: pass@10 rises **0.68 → 0.83 → 0.94** for
  0 → 1–3 → 4–6 siblings (507 held-out evaluations), and the *same* hard families jump
  **0.16–0.26 → 0.70** from density 0 to ~6 with difficulty held fixed. Used the law
  to densify residual families (**+492 Lean-verified rows, 0 coverage gaps**,
  gold-audited **0 false positives across all 7 categories**), lifting a **fresh
  held-out 0.867 → 0.933/0.967**, a new holdout to **1.000**, and the routed Mathlib
  tier to **0.921** over 140 theorems — while keeping the protected core benchmark
  **bit-for-bit** (0.938/0.958). Reported the one honest cost transparently (a
  recoverable 2/14 micro-benchmark regression) and showed cross-category transfer does
  **not** scale, so density must be spent *within* each family.
- **Diagnosed a held-out plateau as a data problem and fixed it with verified
  data.** Audited a stalled fresh-holdout (pass@10 **0.714**) and showed the model
  proposes the right neighbourhood but **mis-binds identifiers when a proof family
  has too few siblings** — a coverage limit, not an architecture wall. Densified each
  residual family with alpha-renamed, independently Lean-verified siblings and added
  new categories (Finset with `[DecidableEq]`, polymorphic order over
  `[Preorder]`/`[Lattice]`): **+350 verified rows, 0 coverage gaps**, gold-audited **0
  false positives across all 7 categories**. Lifted the **fresh holdout 0.714 →
  0.857** (best config **1.000**), took a **new 30-theorem holdout to 0.867**, added a
  Finset category at **0.833** held-out — while keeping the protected core benchmark
  **bit-identical** (0.938/0.958) and confirming the next wall is still coverage, not
  proof-state supervision (only 1/5 residuals multi-step).
- **Scaled a verified-data specialist and proved the evaluator sound.** Hardened
  a batched Lean verifier into a **sound-and-complete** checker (sentinel +
  iterative success-confirmation + isolation rescue), gold-tested **0 false
  positives** vs one-declaration-per-file while an unsound naive batch shows
  3 — and showed the correction would have stopped a weak baseline's score being
  inflated 0.636 → 0.727 by gold-confirmed garbage proofs. Then scaled the
  Lean-verified Mathlib corpus (+181 rows) to take held-out tier-C **pass@10 to
  1.000 (v25) / 0.955 (v26)**, **closing the last Set residual 0.75 → 1.00**,
  while the router kept the protected core benchmark **bit-identical** (0.938/0.958).
- **Closed a cross-library transfer gap without regressing the base model.**
  After a co-trained model improved Mathlib but **regressed** the core benchmark,
  built a **Lean-verified 237-row Mathlib specialist corpus** (6 categories, Set
  & order shapes) behind a **deterministic router** (`import Mathlib` → specialist,
  else base): the specialist lifted held-out Mathlib-tier **pass@10 0.786 → 0.929**
  and made previously-**unreachable Set goals (0.00) reachable (0.50–1.00)**, while
  the router **preserved** the protected core benchmark (p@5/p@10 0.938/0.958) —
  beating the single co-trained model on both axes at once.
- **Built a ~60× faster Lean verifier and proved it correct.** Replaced
  per-candidate `lake env lean` (≈4.7 s each) with a **batched `import Mathlib`
  verifier** (direct toolchain binary + precomputed `LEAN_PATH`, hundreds of
  candidates per process); caught a subtle **parser-recovery false-positive**
  (Lean silently skips a declaration after a parse error), fixed it with an
  **iterative success-confirmation** pass, and gold-tested **0 mismatches vs
  one-example-per-file** over 468 candidates.
- Ran the **first cross-library transfer probe** for a tactic generator:
  installed **Mathlib v4.30.0** (olean cache auto-fetch) and built a
  **36-theorem, 103-candidate Mathlib-verified** benchmark, then showed the
  core-Lean generator transfers **bimodally** — pass@10 **0.812 on shared-skill
  goals vs 0.350 where a Mathlib lemma is required** (failure dominated by
  identifier-vocabulary, **0 environment errors**). A tiny 68-row verified
  Mathlib corpus **lifted held-out transfer 0.571 → 0.786** but **regressed the
  broad-core benchmark** (0.938 → 0.833), which I reported as an **honest
  co-training tradeoff** and declined to ship — keeping the prior model and
  recommending a specialist+router instead.
- Turned a diagnosis into a fix: after attributing a benchmark's residual
  failures to **generation, not ranking**, authored 8 small
  **lean-verified core-Lean shape corpora** (163/163 verified, leakage-
  guarded) targeting exactly those gaps and retrained the generator —
  **closing 5 of 8 unsolved theorems** (pass@10 0.833 → 0.938) with
  **zero category regressions**, and showed the previously-harmful
  reranker becomes beneficial once candidates are well-formed.
- Ran a leakage-controlled (leave-one-theorem-out) reranker refresh and
  reported an **honest negative**: after pooling 6,011 candidate-outcome
  rows and adding grounding features (unbound-identifier penalty,
  abstract-pattern), **no learned reranker beat the generator's raw beam
  order** — then proved *why* with a residual audit (39/48 solved@1, only
  1 ranking-bound, 8 generator-bound), redirecting the next effort from
  ranking to data/generation rather than chasing a ranking win.
- Showed a **single** tactic-generation model can replace a category
  **router**: after diagnosing a routed system's win as a *data-shape
  coverage gap* (not capacity or class imbalance) and adding a 471/471
  Lean-verified "exists" proof-shape corpus, one decoder beat the routed
  baseline on pass@5 (0.792→0.812) and pass@10 (0.792→0.833) while
  recovering the fragile category 0.250→0.750 — with controlled ablations
  proving oversampling and 2× capacity *did not* help.
- Built a verifier-filtered Lean 4 tactic-trace pipeline where an LLM/manual
  generator proposes and the Lean compiler verifies — only Lean-accepted tactics
  become labels.
- Authored a 134-theorem / 21-pattern-family core-Lean corpus (616 candidate
  attempts → 329 verified) and a deterministic, leakage-free dataset builder.
- Trained and benchmarked five tactic-prediction models against a real Lean
  `pass@k` verifier (majority → retrieval → log-linear → AR seq2seq → a
  conditional flow-matching generator), all CPU-only and deterministic; best
  test pass@5 reached 0.90 (generative) / 1.00 (retrieval-decode).
- Implemented a small **Mini-ELF v0** prototype in PyTorch (CPU): a char-level
  **tactic autoencoder** + a **conditional rectified-flow** generator, sampled by
  Euler integration and scored with the same Lean-grounded `pass@k`; its
  stochastic latent sampling raised test `pass@5` to 0.90 (vs 0.82 for the
  autoregressive model).
- Built **Mini-ELF v1**: added a **verifier-aware reranker** (CPU classifier
  trained on past Lean accept/reject outcomes plus *self-training* hard negatives
  — the model's own candidates re-labelled by Lean) and a symbolic **witness-copy**
  augmenter, lifting the generative model's test `pass@1` from 0.61 to **0.89** and
  `pass@5` to **0.95**, cutting the top-1 invalid rate from 0.34 to 0.11, and
  producing Lean-verified *novel* tactics (`novel_verified` 0 → 10/2).
- Added structure-aware features (a heuristic `⊢`-turnstile parser feeding
  conjunct/disjunct-consistency signals) that made Mini-ELF v1 the first model in
  the study to solve the relational `and_elim` / `or_intro` sibling families
  (top-1 family accuracy 0.00 → 1.00) — the gap every prior baseline missed.
- Ran a **generalization study (Mini-ELF v2)**: built a harder 94-theorem
  compositional Lean corpus + adversarial / family / difficulty-holdout split
  strategies, and showed the strong basic-corpus model **does not transfer**
  (`pass@5` 0.95 → 0.00–0.23 under distribution shift; only a symbolic
  witness-copy augmentation survives). Retraining on the combined corpus recovered
  in-distribution-hard performance (`pass@5` 1.00) but not compositional holdout
  (0.06) — diagnosing overfitting honestly rather than reporting the inflated
  in-distribution number.
- Built **Mini-ELF v3**, a **structured proof-block planner**: a heuristic goal
  parser + depth-bounded backward proof-term search + template library that
  *constructs* multi-step Lean proofs (implication chains, nested-conjunction
  projection, `∨`-elimination case splits, iff/equality composition) and fuses
  them above the v2 flow generator + reranker via a precision-first tier policy.
  It took the compositional `difficulty_holdout` `pass@5` from **0.06 to 1.00**
  (verified by a `--no-planner` ablation that stays at 0.08) and recovered the
  basic-corpus regression to 1.00 — then **reported it honestly as engineered
  symbolic *coverage*, not learned generalization** (the planner would fail on
  proof shapes outside its template library), reframing the open problem for v4.
- Diagnosed and *designed around* a learned reranker's off-distribution
  mis-calibration: it scored the planner's Lean-verified multi-step proof blocks
  as low as 0.25, so the fusion ranks symbolic candidates by their own
  construction-confidence rather than the reranker score — turning a known model
  weakness into an explicit, auditable architectural decision.
- Designed a **planner-blind generalization benchmark (Mini-ELF v4)** to stress my
  own v3 result: a 61-theorem core-Lean corpus of proof shapes the symbolic
  planner provably cannot construct (negation/contradiction, contrapositive,
  ∃-elimination, ∀-instantiation, rewrite). Showed the saturated v3 system
  **collapses** to lean-cli `pass@5` 0.096 — distinguishing engineered symbolic
  coverage from genuine generalization — and ran a controlled template-addition
  ablation proving recovery is pure whack-a-mole (each hand-written template lifts
  only its target family 0.00 → 1.00 at 100% precision; untargeted families stay
  at 0.00). Honest negative-result engineering rather than a saturated headline.
- Built **Mini-ELF v5**: a unified candidate-**proposer** interface (flow /
  planner / witness / retrieval / LLM behind one API) and a **train-free
  retrieval proof-block proposer** (char-n-gram retrieval of verified tactic
  blocks + numeric-literal adaptation) that solved the two planner-blind families
  *no* hand-written symbolic template could reach (`forall_inst`, `rewrite_succ`:
  lean-cli `pass@5` 0.00 → **1.00**) on a leakage-free within-family split — the
  first escape from per-shape whack-a-mole — and showed retrieval + templates are
  complementary (`pass@5` → 1.00). Reported the honest limits (example reuse, not
  reasoning; char-similarity reproduces sibling confusion) and **gated the LLM
  pilot on an API key** (skipped, not faked) rather than inventing a number.
- Built **Mini-ELF v6**: a **structure-aware retrieval** ranker — heuristic parse
  features (goal shape, hypothesis shapes, a guessed required-operation, left/right
  conjunct position, connective overlap) re-score the same retrieved proof blocks,
  plus an adapted-candidate preference (rank `exact h 13` above the stale
  `exact h 3`, goal-LHS first). Fixed all four v5 ranking failures: retrieval-alone
  lean-cli `pass@1` **0.357 → 1.00** and `pass@5` **0.595 → 1.00**
  (`forall_inst` pass@1 0.00 → 1.00, sibling/negation families 0.00 → 1.00), with a
  `no-structural` ablation that collapses back to ~v5 to attribute the gain — all as
  *ranking*, not proof search (no templates, no `state_after`, no LLM).
- Stress-tested my own v6 result with **Mini-ELF v7**: built a graded
  donor-scarcity benchmark (interpolation → k-shot → literal-holdout →
  family-holdout → operation-holdout → 0-shot) and showed v6's `pass@5` 1.00 was
  **same-family interpolation** — forbidding same-family donors drops it to 0.00,
  and genuine family/operation holdout collapses every config (incl. a new
  template-free abstraction re-ranker) to **0.00** with `cross_family_verified = 0`.
  Isolated the determinant as the *presence vs. absence* of a same-family donor,
  not its quantity (≥1 donor ⇒ 0.91–1.00; zero ⇒ 0.00), and showed role-based
  re-concretisation helps only the scarce 1-shot regime (pass@1 0.832 → 0.924) —
  reporting a sharp negative result on cross-family transfer rather than a headline.
- Built **Mini-ELF v8 — generative donorless proposer**, breaking the v7
  donor-coverage wall on regimes where the train pool contains
  shape-compatible sibling families. Trained 18 CPU-only char-level seq2seq
  models (reusing the v0 AR architecture) on a pooled 690-row corpus
  (basic + hard + planner_blind) under four regimes (interpolation /
  family_holdout × 10 / operation_holdout × 7 / donorless_eval), fused them
  with v7 retrieval under a donor-availability-aware ranking policy, and
  re-measured donorless rows with real lean-cli — **on
  `family_holdout/neg_exfalso` the seq2seq verifies 5/8 held theorems at
  pass@5 = 0.625 with 9 *novel* verified tactic strings**
  (`exact absurd hp hnp`, `exact (hnp hp).elim`), composing the token
  `absurd` and hypothesis names `hp`/`hnp` from sibling negation families in
  train; **v7 retrieval gets 0.00 on the same regime**, so v8 is the first
  model in the project to verify any `cross_family_verified` candidate on a
  v7 holdout regime. Negative control `family_holdout/forall_inst` (whose
  flat `exact h N` shape has no token-compatible cousin in train) stays at
  0/7, isolating the mechanism as *composing tokens learned from sibling
  families*, not abstract synthesis. On the strictest `donorless_eval`
  regime (basic+hard only, no PB family) the model verifies 3/61 via
  training-distribution slot-fill (`exact ⟨100, rfl⟩` on
  `exists_reconstruct`, `novel_verified = 0`). The LLM pilot was **skipped
  honestly** (no API key); reported as `skipped`, never as `0.00`. v9 wall
  identified: breadth of sibling-family coverage in training (pretrain on
  Mathlib4 tactic traces, or ungate the LLM pilot).
- Built **Mini-ELF v10 — operation×surface-family redundancy corpus +
  data-scaling test + leakage-bug discovery + correction**. Authored a
  40-cell DESIGN over 8 proof operations × 5 sibling surface families
  (variable names, proposition names, hypothesis order, nesting differ;
  closing-tactic shape held constant inside each operation); **all 40
  cells lean-cli verified against pure Lean 4 / Init** under a
  pre-commit refuse-or-write contract (no fake corpus; the 8 cells
  initially refused as WSL cold-start timeouts all verified at a longer
  timeout cap on rerun, leaving the failed-traces file empty). Built **5
  split regimes** with a new
  ``cell_holdout_folds``/``kshot_operation_split``/``operation_sibling_in_train``
  invariant family in `retrieval_splits.py`. Discovered and corrected a
  **major methodology bug**: the legacy `combined_v10` (interpolation-
  trained) had 36 of 40 holdout test theorems in its training pool; the
  prior draft's "combined_v10 wins 5/8 op-holdouts" headline was
  measuring in-distribution memorisation, not generalisation. Built a
  proper leakage guard suite (`tests/test_v10_no_leakage.py`, 4 tests
  that pin the bug and assert the corrected per-op LOFO regimes are
  clean), retrained **8 per-operation LOFO models** under the v8 base
  pool + the *other 7* operations' v10 cells, and re-evaluated cleanly.
  **Honest clean result (16/16 op-holdout cells, per-op LOFO)**: mean
  pass@5 **0.600** for `combined_v10_per_op` vs **0.575** for
  `baseline_v8` (zero-shot, never saw v10) — Δ +0.025; per-fold 2 wins
  / 1 loss / 5 ties; total `cross_operation_verified` 39 vs 34 (+5);
  v10 wins on `implication_chain` and `instantiate_forall` (+0.20
  pass@5 each, where the v8 base pool lacked siblings), regresses
  -0.20 on `contradiction` (v8 base pool already covered it),
  ties elsewhere. The prior draft's dramatic 5/8 win headline is **NOT
  reproduced** under proper LOFO — that was the leakage artifact.
  Reported honestly throughout: legacy leaked metrics relabelled as
  in-distribution diagnostics, never silently overwritten or zeroed;
  cell_holdout (40 per-cell LOFO models) deferred to v11. v10 is **data
  scaling only**: same architecture, no Mathlib, no `state_after`, no
  manual oracle counted as a model output.
- Built **Mini-ELF v11 — clean per-family LOFO with v10 redundancy** to
  directly test the question v10 left open: under proper LOFO
  methodology, does adding v10 redundancy unblock the v8 negative-
  control families `forall_inst` and `rewrite_succ`? Designed 5
  per-family regimes where train = v8 family-LOFO + 40 v10 cells minus
  held-test `(theorem_name, state_before, tactic)` duplicates and
  test = the v8 `family_holdout/<fam>/test.jsonl` rows verbatim
  (apples-to-apples on the same test rows). 5 leakage-guard tests
  (`tests/test_v11_family_lofo_no_leakage.py`) ratify three invariants:
  theorem-name disjointness, `(state_before, tactic)` pair
  disjointness, no held-family planner_blind row in train. Trained 5
  per-family seq2seq models (same v8/v10 architecture, no model
  changes), re-evaluated against the v8 family-LOFO baselines on the
  identical test sets. **Headline (clean LOFO, no leakage)**:
  `rewrite_succ` **0/5 → 4/5 pass@5 (+0.800)**; `forall_inst` **0/7
  → 1/7 pass@5 (+0.143)**; `exists_reconstruct` 0.400 → 0.800;
  `neg_exfalso` pass@5 unchanged (0.625) but pass@1 lifts 0.125 →
  0.625; `neg_imp_exfalso` unmoved at 0/5 because v10 contains no
  contrapositive shape. `novel_verified = 0` on every v11 win — the
  model copies the verifying tactic string from v10 siblings in
  train, not synthesising novel strings under LOFO. Reported honestly:
  the 5th `rewrite_succ` row also emitted `rw [h]` at beam rank 0
  but the verifier hit a 20 s cold-start timeout, so pass@5 0.800 is a
  lower bound rather than retconned to 1.000. v11 confirms the v10
  redundancy data is useful when the held family's tactic shape has a
  sibling in v10; it is not a uniform across-the-board lift, and it
  does not revive the v10 leaked metrics. Same architecture; no
  `state_after`; no Mathlib; no manual oracle counted.
- Built **Mini-ELF v12 — literal-aware decode + rule-based reranker**
  to attack the two v11 failure modes the analysis flagged as
  addressable: numeric-literal extrapolation (`exact h 4` for a goal
  needing `exact h 13`) and beam-rank failure (`exact h 3` exists in
  the v11 train pool but the beam puts wrong literals ahead). The
  literal-aware module
  (`src/mini_elf_lean/literal_aware_decode.py`) detects
  `exact <ident> <num>` / `exact ⟨<num>, rfl⟩` schemas in the model's
  beam, substitutes the first goal literal, and tags the result
  `source = seq2seq_literal_adapt`; gated by `∀` quantifier in state,
  numeric literal in goal, identifier in local context; **no
  `state_after` argument** (the function signature pins the
  invariant). The rule-based reranker
  (`src/mini_elf_lean/proof_block_reranker.py`) scores candidates on
  goal-literal match (+2.0), stale-literal penalty (−1.0), malformed
  penalty (−2.0), source priority (+0.5 for literal_adapt), known
  head (+0.2), schema match (+0.4), length and beam-rank tie-breaks.
  Composed both layers on the v11 family-LOFO predictions and re-
  verified with lean-cli (the v11 cache seeds free re-verifications).
  **Headline (clean v11 family-LOFO test rows)**: `forall_inst` 1/7
  → **3/7** pass@5 (+0.286) — every v12 win is a literal-adapt
  candidate; `exists_reconstruct` 4/5 → **5/5** (+0.200) via the ⟨N,
  rfl⟩ witness shape; `rewrite_succ` preserved at 0.800 (brief
  floor); `neg_exfalso`, `neg_imp_exfalso` unchanged. **3 of the 4
  remaining `forall_inst` failures emit the correct adapted candidate
  at rank 0 but the lean-cli verifier hit a cold-start timeout** —
  reported honestly as FAIL, NOT retconned to the would-be 6/7 =
  0.857. Char-level mid-token truncation (`exact h.`, `rw [hns`) is
  documented as a v13 tokenizer task
  (`docs/V12_TOKENIZATION_NOTE.md`) and only attenuated in v12 via the
  malformed penalty. Post-generation only; no new training, no
  architecture change, no model retrain. Both modules are pure-Python
  (no torch); 34 unit tests across `tests/test_literal_aware_decode.py`
  and `tests/test_proof_block_reranker.py` pin the schema gates,
  dedup, source preservation, malformed detection, and the
  no-`state_after` invariant.
- Built **Mini-ELF v13 — warm-verifier rerun + tactic-token tokenizer
  prototype** to resolve verifier-timeout uncertainty *before* spending
  compute on a model retrain. The v12 brief had flagged 3 forall_inst
  rows whose top-rank literal-adapt candidate (`exact h 5` /
  `exact h 13` / `exact h 8`) hit a 20-second lean-cli cold-start
  cap, reported honestly as `FAIL`. v13's
  `scripts/rerun_v12_timeouts.py` (1) snapshots the v12 metrics
  untouched, (2) discovers every (theorem, tactic) pair with
  `verifier.error == "timeout"` across the five v11 family-LOFO test
  folds, (3) pre-warms lean with one trivial theorem, and (4) re-runs
  each candidate at `timeout=120s` in a fresh subprocess. Headline
  correction: **`forall_inst` pass@5 3/7 → 6/7 (+0.428)** as all three
  literal-adapt candidates verify, and **`rewrite_succ` pass@5 4/5 →
  5/5 (+0.200)** as `rw [h]` on `rewrite_succ_ij` verifies — labelled
  explicitly as an *evaluation-reliability* improvement, not a model
  improvement. The 9 non-headline timeout slots were unmasked as
  genuine elaboration errors (type-mismatch, parse-end-of-input,
  unknown-identifier) the 20-s cap had been hiding. v12 metrics on
  disk are NOT overwritten (still pinned by `test_v12_eval.py`); v13
  publishes corrected numbers at `data/baselines/v13_timeout_rerun/`.
  Also shipped `src/mini_elf_lean/tactic_tokenizer.py` — a
  deterministic pure-Python token-level Lean tactic tokenizer
  (closed `KEYWORD` set, `IDENT` / `NUMBER` / `SYMBOL` (`⟨ ⟩ → ↔ ∧ ∨ ¬
  ∀ ∃ ≤ ≥ ≠`) / `PUNCT` / `WS` classes, lossless round-trip,
  vocabulary builder with `BOS` / `EOS` / `PAD` / `UNK` ids) targeted
  at the residual char-truncation failures (`rcases h wi`,
  `refintro hn`, `rwexact h`) that no warm rerun could fix. Token-level
  seq2seq retraining itself is deferred to v14. 89 new unit tests
  (`tests/test_tactic_tokenizer.py`, `tests/test_v13_timeout_rerun.py`)
  pin the round-trip, keyword-vs-IDENT distinction, the truncation
  patterns the brief explicitly named, the v13 metrics, and the
  no-overwrite invariant on v12 on-disk metrics. Full suite stays
  green at 674 passing tests.
- Built **Mini-ELF v14 — token-level seq2seq retrain** that replaces
  the v13 char-level decoder with a token-level one (vocabularies of
  136–142 Lean tokens per family-LOFO fold, ~484k parameters, same
  (bi)GRU+attention architecture, CPU-only, deterministic seed). The
  TokenVocab class is a drop-in for the char Vocab — same encoder
  surface — so the existing Seq2Seq / ar_train / ar_decode primitives
  absorb the swap unchanged. Per-fold token datasets are built by
  `scripts/build_token_seq2seq_dataset.py`; per-fold training by
  `scripts/train_token_seq2seq.py`; warm-verified evaluation
  (`timeout=120s` + a separate 180s timeout rerun for v14 stragglers
  via `scripts/rerun_v14_timeouts.py`) by
  `scripts/evaluate_token_seq2seq.py`; char-vs-token comparison by
  `scripts/compare_v13_v14.py`. **Headline corrected pass@5**:
  `forall_inst` 6/7 → **7/7 (+0.143)** as the v13 residual
  `forall_inst_var_m` (char-truncation case) is now solved; on
  `neg_imp_exfalso` the raw token beam reaches **12/15 = 0.800
  pass@5 vs v13's 0/5** by cross-family composition (the model
  emits `intro hp\n  exact absurd hp hnp` — neither substring is in
  the family-LOFO train set; `novel_verified=12`). Mean pass@5
  rises 0.696 → 0.765; mean pass@10 0.696 → 0.925. **Headline
  modelling invariant**: across all 5 families × beam=10 = 350
  candidates, **zero contain fused-keyword tokens** (`refintro`,
  `rwexact`, `casexact`, `introexact`) — the closed Lean KEYWORD set
  in the tokenizer makes these unrepresentable by construction.
  Honestly disclosed limit: the v12 rule-based reranker
  mis-calibrates on the contrapositive shape (neg_imp_exfalso raw
  pass@5 = 0.800 → +literal_adapt+rerank pass@5 = 0.200; pass@10 =
  1.000); a learned reranker is the v15 task. v12 and v13 metrics
  on disk are NOT overwritten; corrected v14 numbers live at
  `data/baselines/v14_timeout_rerun/metrics_rerun.json`. 124 new
  unit tests (token dataset, model smoke, v14 eval invariants,
  comparison structure, warm-rerun pins).
- Ran **Mini-ELF v21 — forall-regression recovery via model
  routing**. v20's implication+bool corpus had regressed the `forall`
  category from 0.667 to 0.000; diagnosed the cause with a regression
  audit as a **single-model capacity tradeoff** — the 948
  implication+bool rows (45 % of the pool) had crowded the
  `exact h <arg>` instantiation schema *out of generation* (absent
  from the beam, not merely demoted, so no reranker could recover it).
  Authored a 677/680 lean-cli-verified forall corpus (5 families) and
  ran a controlled four-way comparison — v20 baseline vs single-model
  retrain vs **category routing** (a deterministic
  category→model switch sending forall goals to a focused specialist
  and everything else to the frozen v20 model) vs higher-capacity
  (embed 128 / hidden 192). **All three fixes recovered forall to
  1.000 and preserved implication/bool at 1.000, but only routing had
  zero collateral**: single-retrain relocated the tradeoff
  (disjunction 0.60→0.40, negation 0.80→0.60, exists 0.25→0.00) and
  even higher capacity still lost exists — whereas routing reproduced
  every non-forall category exactly and lifted mean pass@5
  0.729 → **0.792** (pass@1 0.625→0.688, pass@10 0.729→0.792).
  Concluded **routing > capacity > single-retrain**, and reported the
  honest caveat that routing is composition-of-specialists
  (engineering on a category-separable benchmark), not a single model
  that generalizes across proof shapes. Took a safe non-destructive
  repo checkpoint first (the repo carries an in-progress paused
  interactive rebase from a prior session; left it untouched, archived
  it in a 100 MB tar.gz that preserves `.git`). v18/v20 metrics on
  disk unchanged; no state_after, no manual oracle, no Mathlib,
  routing injects no proof templates.
- Ran **Mini-ELF v20 — data-shape-gap closure + ranker-time
  abstraction**. From v19's negative result, took the directive that
  the fix for the two v18-broad-core dead categories was *corpus*,
  not abstraction, and that abstraction belonged at *ranking* not
  generation. A shape-gap audit proved `bool` had **zero** training
  support (0 rows with `cases b`/`Bool`/`decide` across 3,984 rows)
  and `implication` failed on **rank** not shape (the v17
  contradiction pattern `exact (hpfalse hp).elim` displaced the bare
  `exact hp`). Authored two core-Lean lean-cli-verified corpora —
  **759/760** implication candidates (7 families) and **189/239**
  bool candidates (7 families incl. `cases b <;> simp`), both
  v18-leakage-guarded — pooled them into a 2,099-row training set,
  and retrained a single **raw-name** token seq2seq (same v14/v18
  arch; explicitly *not* v19's placeholder model). Built a
  **scoring-only** abstract-pattern reranker that reuses v19's
  abstraction machinery to score raw candidates by abstract-pattern
  frequency and penalise unbound identifiers while **never emitting a
  placeholder**. Result (timeout-corrected best config):
  **implication 0.000 → 1.000, bool 0.000 → 1.000, mean pass@1
  0.500 → 0.625, pass@5 0.583 → 0.729, pass@10 0.604 → 0.729** — the
  pass@10 lift proving a real generator change, and the ranker-time
  abstraction the single best config with **0 unresolved-placeholder
  errors** vs v19's 44 %. Reported the one honest regression
  (**forall 0.667 → 0.000**, a single-model capacity tradeoff from
  the implication-heavy pool) rather than hiding it in the mean.
  Applied the v13/v14 warm-rerun precedent to flip 9 spurious WSL
  `lean` timeouts to success (26 confirmed real errors, 0 still
  timeout); original metrics on disk untouched, corrected metrics in
  parallel. v18/v19 metrics unchanged; no state_after, no manual
  oracle, no Mathlib, no v10-leakage.
- Ran **Mini-ELF v19 — state-aware identifier abstraction (an
  honest negative result)**. Hypothesised that replacing local
  identifier names in both state and tactic with stable typed
  placeholders (`<HYP_IMP_0>`, `<HYP_PROP_0>`, `<VAR_NAT_0>`, ...)
  during training and resolving them against the v18 test
  theorem's local context at inference would reduce v18's
  dominant `unknown_identifier` failure class (28 % of all top-10
  slots). Built the full pipeline: a 13-category type classifier
  for parsed `state_before` text, word-boundary-aware
  abstraction/concretisation with keyword protection, an abstract
  dataset (1111 unique rows from v11+v16+v17 corpora with 0
  round-trip failures and a clean v18 leakage guard), and an
  abstract token seq2seq trained to val_exact=0.26 (vs v18 broad
  baseline's 0.15 — *better in-distribution*). **The hypothesis
  did not hold on v18 transfer**: v18 broad-synthetic+policy
  pass@5 = 0.583; v19 abstract-only+policy pass@5 = 0.208; v19
  ensemble pass@5 = 0.312. `unknown_identifier` *did* drop
  (127→~30 slots) but was replaced by a larger
  `unresolved_placeholder` class (0→210/480 = 44 %). Categorical
  regressions on conjunction (0.83→0.17), list (0.80→0.20),
  negation (0.80→0.40). Diagnosed three root causes
  (placeholder dropout against v18 local-context shapes,
  over-aggressive dedup, and the impossibility of tracking
  tactic-introduced binders with a state-only abstraction).
  Reported honestly per the v19 brief's explicit escape hatch
  ("If pass@k does not improve, report that honestly and analyze
  the new dominant failure"). v17/v18 metrics on disk untouched.
  Local-context parser + abstraction module remain reusable for
  v20 *ranker-time* abstraction (emit raw names, rerank by
  abstract-pattern match) which sidesteps the unresolved-
  placeholder cliff.
- Ran **Mini-ELF v18 — broad-core transfer test**: hand-authored
  a 48-theorem off-template benchmark across 10 categories
  (implication, conjunction, disjunction, negation, equality
  rewrite, exists, forall, nat-succ, bool, list) in core Lean
  (Mathlib tier skipped honestly), lean-cli-verified the 115
  proposed candidates (109/115 = 94.8 %), and evaluated the v17
  composed pipeline zero-shot. **The honest answer**: ~half of v17
  transfers — v17 panel + policy reaches pass@5 = 0.500, pass@10
  = 0.583 on v18 (vs 1.000 on the templated v11 LOFO). A single
  broad-synthetic token seq2seq trained on the union of v11 + v16
  + v17 corpora (1151 leakage-guarded rows) **outperforms the v17
  family-LOFO panel** at every metric (pass@1 0.292→0.500, pass@5
  0.500→0.583, pass@10 0.583→0.604) — the v17 specialists were
  over-fit; broader training generalises better even on the same
  data. The wall is **categorical, not gradient**:
  `equality_rewrite` 1.000 / `conjunction` 0.833 / `list` 0.800 /
  `negation` 0.800 / `disjunction` 0.600 transfer; `implication`
  0.000 and `bool` 0.000 are total misses (no synthetic training
  for those shapes). The dominant failure class —
  `unknown_identifier` (28 % of all 480 top-10 slots) — points at
  v19's largest available win: state-aware tokenisation that
  emits `<local-hyp-N>` placeholders. v12-v17 metrics on disk
  untouched; the v18 brief's "do not retcon v17" honoured (v17
  still closed the *templated* benchmark; v18 is the next wall,
  not a downgrade). Tier-C Mathlib skipped honestly per the
  brief's escape hatch.
- Built **Mini-ELF v17 — arrow_false_elim corpus + one-line policy
  edit** that closes the v16 residual failure on the templated
  v11 family-LOFO benchmark. Two changes: (a) moved
  `contradiction` from `USE_DEFAULT_RULE` to `USE_LEARNED` in
  `src/mini_elf_lean/v15_rerank_policy.py` (the v15 audit had
  found rule/learned tied on v14 candidates; v16 broke the tie
  in learned's favour; v17 acts on it); (b) generated 137
  lean-cli-verified `arrow_false_elim` rows (`(p q : Prop) (h : p
  → False) (hp : p) : q` with proof `exact (h hp).elim`) using
  disjoint variable names + two leakage guards (0 drops), and
  retrained the v14 token seq2seq architecture for `neg_exfalso`
  only (other folds reuse the v16 model). **Headline on the
  templated v11 LOFO benchmark**: `neg_exfalso_arrow_pq` first
  verified rank — (no top-10) → **1** (`exact absurd hp h` at
  rank 1, `exact (h hp).elim` at rank 2). `neg_exfalso` pass@5
  **0.875 → 1.000**. **Mean pass@5 0.975 → 1.000; mean pass@1
  0.875 → 0.950; mean pass@10 0.975 → 1.000** — every unique
  v11 LOFO test theorem now verifies at pass@5 on this
  *templated* benchmark. Honestly bounded scope: this is not
  Mathlib, the v18 wishlist starts with "move off the templated
  corpus to find the next wall". v12–v16 pinned metrics on disk
  untouched (only v15/v16 policy-eval regenerated under new
  routing; pinned pass@5 unchanged). 96 new tests pin the
  residual-failure audit, the policy edit, the corpus
  verification, the leakage guards, and the v17 headline
  numbers. Full suite stays green.
- Built **Mini-ELF v16 — contrapositive corpus augmentation +
  token seq2seq retrain** that closes the v15 generator-bound
  residual failure (`neg_imp_exfalso_ab`). After auditing v15
  failures into "rank-bound" (1 row) vs "corpus-shape-bound" (3
  rows), built and lean-cli-verified a 287-row contrapositive
  corpus across 3 surface families
  (`contrapositive_classic` 117, `contrapositive_neg_imp` 141,
  `contrapositive_false_target` 29) using disjoint Greek +
  double-letter variable names with two leakage guards (theorem
  name and `(statement, state, tactic)` triple, both 0 drops).
  Retrained the v14 token seq2seq architecture on the
  v16-augmented v11 family-LOFO folds (40 epochs CPU,
  hyperparameters unchanged, ~15 min for all 5 folds).
  **Headline brief target hit cleanly:** `neg_imp_exfalso_ab`'s
  first verified rank moved from **6 → 0** with three verifying
  candidates in top-5 (three distinct proof forms — `exact fun hp
  => absurd hp hnp`, `intro hp\n  exact absurd hp hnp`, `intro
  hp\n  exact (hnp hp).elim` — all from the v16 corpus, none in
  pre-v16 train). `neg_imp_exfalso` pass@5 **0.200 → 1.000**;
  collateral win on `neg_exfalso` pass@5 **0.625 → 0.875** as
  the model generalised the `(h hp).elim` form to 2 of 3
  `neg_exfalso_arrow_*` rows the v16 brief never targeted.
  **Mean pass@5 0.765 → 0.975 (+0.210); mean pass@1 0.514 → 0.875
  (+0.361); mean pass@10 0.925 → 0.975 (+0.050)** — the pass@10
  lift is the strongest evidence v16 is a real generator change
  (reranking cannot move pass@10). All v15 wins
  (forall_inst / rewrite_succ / exists_reconstruct at 1.000)
  preserved. Honestly disclosed v15-policy sub-optimality under
  v16's distribution shift: `contradiction` should now route to
  learned (pass@1 0.625) instead of rule (pass@1 0.375); a
  one-line v17 fix. v12 / v13 / v14 / v15 metrics on disk
  untouched; v16 numbers at parallel paths.
- Built **Mini-ELF v15 — learned reranker + operation-aware
  policy**: a rerank-only change (no generation work, no new
  templates, no manual oracle) that closes the v14 reranker
  mis-calibration on contrapositive shapes. Walked v11/v12/v13/v14
  predictions + warm-rerun corrections to build a 1779-row
  candidate-outcome dataset (155 verified positives, 8.7 %,
  per-family-LOFO leakage guard) and trained a pure-Python sparse
  logistic regression (~230 features, ~2 s/fold, deterministic)
  with 33 named pattern bits (intro / absurd / rw / cases / ⟨ /
  goal-literal-match / malformed / required_operation one-hots)
  plus hashed char-3-grams + tactic-head buckets. The v15 audit
  reveals that **rule and learned each dominate disjoint
  operations** (rule: `instantiate_forall` / `rewrite`; learned:
  `intro_negation` / `unknown`-tagged `exists_reconstruct`), so
  the headline v15 ranker is an **operation-aware policy** that
  routes each row to the best sub-scorer. Result: **mean pass@5
  0.765 → 0.885 (+0.120)**, **mean pass@1 0.514 → 0.725
  (+0.211)**, **`neg_imp_exfalso` pass@5 0.200 → 0.800 (+0.600)**;
  pass@10 preserved at the v14 generator's ceiling 0.925; the
  residual `neg_imp_exfalso_ab` row stays at rank 6 (generator-
  bound, documented honestly). No sklearn / no torch (the LR is
  hand-rolled because the rest of the project's neural_baseline.py
  already is). v12 / v13 / v14 metrics on disk untouched; v15
  numbers live at `data/baselines/v15_learned_reranker/`. New
  unit tests pin the leakage guard, deterministic-seed weights,
  routing table, pass@10 ceiling preservation, and the
  no-state_after invariant.

## Medium (one–two lines each)

- Designed a modular Lean-tactic data factory (mock / manual-file / lean-cli /
  LeanDojo backends behind two stable interfaces) that records *how real* each
  verification was, so downstream training can never mistake a whole-file
  typecheck or a mock for a true proof-state transition.
- Diagnosed a real LeanDojo failure to a Lean-toolchain root cause (batch-mode
  elaboration receives an empty stdin, crashing the REPL on the first tactic),
  reproduced it across two Lean versions, and shipped it as a documented,
  strict-`xfail` test rather than faking success.
- Ran a controlled baseline study (majority vs char-n-gram retrieval vs a
  trained log-linear classifier) with real Lean `pass@k`, and showed via a
  pattern-family confusion analysis exactly which proof patterns each baseline
  can and cannot generalize to.

## Technical (precise, for ML/PL audiences)

- Implemented a pure-Python (no numpy/torch) softmax/log-linear classifier over
  hashed, field-aware character-n-gram features (full text + goal line),
  trained with seeded SGD; deterministic, CPU-only, ~28 s for 80 epochs, 55
  tactic classes — pass@5 0.65 (val) / 0.76 (test) vs retrieval 0.22 / 0.32.
- Built a lean-cli `pass@k` evaluation harness with a `sha256(theorem‖tactic)`
  verification cache, per-pattern-family `pass@k`, and a sibling-family
  confusion table; showed the classifier solves lexically separable siblings
  (`eq`, `imp`: top-1 family accuracy 1.00) but not relational ones
  (`and_elim`, `or_intro`: 0.00), isolating the need for a structure-aware model.
- Engineered the dataset for transfer: ≥5 variants per proof-pattern family with
  constant hypothesis names so a same-family train theorem supplies the exact
  verified tactic an eval theorem needs — which lifted both retrieval and the
  trained model from 0% to non-trivial `pass@k`, demonstrating a coverage
  problem rather than a code bug.
- Built a character-level GRU encoder–decoder with attention (PyTorch, CPU,
  410K params, deterministic beam search) that decodes tactics token-by-token;
  it beat the log-linear classifier on every `pass@k` (test pass@1 0.76 vs 0.55)
  and generated *novel* Lean-verified tactics outside the fixed label set —
  composing the `exact ⟨N, rfl⟩` witness template — a partial open-vocabulary
  capability the classifier structurally cannot have.
- Prototyped a conditional **flow-matching** tactic generator ("Mini-ELF v0"): a
  char-level tactic autoencoder defines a latent space and a rectified-flow MLP
  transports Gaussian noise → tactic latent conditioned on the proof state, with
  Euler sampling + Lean-verified `pass@k`. Its stochastic decoding produced ~20
  distinct candidates per prompt and beat the autoregressive model on `pass@5`
  recall (test 0.90 vs 0.82), trading off top-1 precision — characterized
  honestly against the AR baseline.
- Diagnosed and fixed a reranker distribution-mismatch failure: a `(state,
  candidate)→P(verifies)` classifier trained only on collected traces saturated
  at 1.0 on the generator's candidates (token features alone separated the easy
  trace negatives), *degrading* `pass@5`. Adding **self-training hard negatives**
  (the generator's own flow candidates, Lean-labelled on train theorems) plus
  hand-engineered structural features (bracket balance, hypothesis-binding ratio,
  conjunct/disjunct consistency) forced the model onto the discriminative signal —
  held-out verified vs failed candidate scores separated to 0.97 vs 0.25 — and a
  "rerank a top-frequency shortlist, keep the tail" policy guaranteed precision
  gains without sacrificing recall.
- Designed leave-one-family-out / leave-one-operation-out / k-shot / literal-holdout
  split builders + a pooled lean-cli evaluator with a donor-condition failure
  taxonomy, and a template-free **operation-abstraction** layer that abstracts a
  verified donor tactic to hypothesis *roles* (`exact absurd <prop_hyp> <neg_hyp>`)
  and re-binds the slots to a target's own hypotheses — generalizing type-exact
  hyp-remap to role-based re-concretisation. Used it to attribute v6's success to
  donor coverage (115/157 family-holdout failures *had* a cross-family
  same-operation donor that still failed; 42/157 had none) rather than ranking, and
  **skipped a tiny learned scorer with justification** (no learnable headroom:
  positives saturated where donors exist, absent where they don't).
- Built a v8 generative-proposer stack on top of that audit: a 690-row pooled
  proof-block dataset (basic + hard + planner_blind) carved into four
  donor-condition regimes with unit-tested leakage invariants
  (`proof_block_dataset.py`); the same v0 AR encoder–decoder retrained per regime
  (18 CPU models in ~2 min each), wrapped as a unified `CandidateProposer` with
  beam-rank metadata; a multi-line-aware proof-block cleaner (strip fences /
  drop prose / preserve multiline Lean blocks / reject `state_after` /
  dedup); and a **donor-availability-aware source-priority fusion** that
  ranks v7 retrieval first when a same-family donor exists and seq2seq first
  when it doesn't. Result on the v7-identified donorless wall: **first
  non-zero `cross_family_verified` in the project's history** (3 verifications
  on `exists_reconstruct` via training-distribution slot fill), with
  `novel_verified = 0` honestly attributing the win to overlap rather than
  cross-family abstraction. Skipped the LLM pilot cleanly when no API key was
  configured (the script + prompt + verifier are wired but report `skipped`,
  never `0.00`).
