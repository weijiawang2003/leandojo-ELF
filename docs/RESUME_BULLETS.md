# Résumé bullets — Mini-ELF-Lean

Reusable phrasings for a CV / portfolio. All numbers match the project's
generated metrics files. Keep the honesty caveats (theorem-level, not
next-state) when space allows.

## Short (one line each)

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
