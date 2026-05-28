# Mini-ELF-Lean: Verifier-Filtered Tactic Generation Infrastructure

## Abstract

Mini-ELF-Lean is a small, modular **data factory** for Lean 4 tactic traces:
it turns candidate tactics (from a mock, a hand-written/agent JSONL file, or a
real LLM) into a clean, Lean-verified dataset of `(state_before, tactic)`
records, and evaluates tactic-prediction baselines against a real Lean
verifier. The guiding principle is *candidate generators propose, Lean
verifies* — a raw candidate is never a positive label until Lean accepts it.

This report documents the infrastructure, an honest investigation of the
LeanDojo backend (which currently cannot complete a real `run_tac` on this Lean
toolchain), the verified **134-theorem / 21-pattern-family** corpus, and five
tactic-prediction models (majority, retrieval, a trained log-linear classifier,
a **generative char-level AR seq2seq**, and **Mini-ELF v0** — a tactic
autoencoder latent space with a conditional **rectified-flow** generator), all
evaluated with **lean-cli pass@k**. The headline empirical results: the
log-linear classifier decisively beats retrieval (pass@5 0.65/0.76 vs 0.22/0.32
on val/test); the AR model beats the classifier on every `pass@k` (test pass@5
0.82 vs 0.76, pass@1 0.76 vs 0.55) and generates *novel* verified tactics a
fixed-class model cannot; and **Mini-ELF v0 beats AR on `pass@5`** (test 0.90 vs
0.82) by producing ~20 distinct stochastic candidates per prompt — though it
trails AR on `pass@1` (precision) and its novel generations do not yet verify.
A sibling-family analysis shows the AR model cracks `iff` and (partly)
`or_intro`, while purely *relational* `and_elim` and out-of-range numeric
witnesses remain open for every model.

> **Mini-ELF scope.** Mini-ELF v0 is a deliberately small *prototype of the
> generation loop* (embedded latent + flow sampling + Lean verification) — **not**
> the full ELF method and **not** real proof-state flow. Verification is still
> theorem-level; `state_after_is_real=false`.

> **Scope honesty.** All Lean verification here is **theorem-level** (lean-cli
> typechecks the whole proof file). There is **no real `state_before → tactic →
> state_after` supervision** yet — the dataset's `state_after` is a placeholder
> and every row is flagged `state_after_is_real=false`. No Mini-ELF model is
> implemented.

---

## 1. Motivation

The eventual research goal is to test whether ELF-style *continuous embedded
flow* generation can produce Lean tactics or tactic blocks. **This stage is not
modeling-first.** Before any flow/diffusion model exists, the project needs a
robust verifier-filtered dataset pipeline and credible baselines — training
before having a clean, verified dataset and a measured baseline is a common way
such projects fail. The deliverable of this stage is therefore *infrastructure
plus an empirical baseline study*, not a novel model.

---

## 2. System overview

Everything is isolated behind two interfaces — `LLMClient` (candidate sources)
and `LeanRunner` (verification backends) — so the rest of the pipeline never
touches model/Lean specifics.

```
seed theorem / proof state
        │
        ▼
candidate generator        (mock | manual-file | anthropic | openai)
        │  proposes raw candidate tactics
        ▼
tactic sanitizer           (strip fences/bullets, dedupe, drop sorry/admit, flag automation)
        │
        ▼
Lean runner                (mock | lean-cli | leandojo)
        │  verifies
   ┌────┴─────┐
   ▼          ▼
verified    failed         (two separate JSONL files — failures never leak into labels)
   │
   ▼
dataset builder            → next_tactic.jsonl + plain_tactics.txt + theorem_splits.json + summary.json
   │
   ▼
baseline evaluation        majority / retrieval / log-linear / AR seq2seq / Mini-ELF v0, scored by lean-cli pass@k
```

---

## 3. Data pipeline

`seed theorem → candidate tactic/proof → Lean verifier → TraceRecord → dataset
builder`.

- **Seed** (`TheoremSeed`): a theorem statement plus, for lean-cli, a `template`
  with a `__TACTIC__` placeholder; optional `metadata` (e.g. `pattern_family`).
- **Candidate**: a proposed tactic string. Proposals only — never a label.
- **Verifier** (`LeanRunner`): returns success/failure (+ a `state_after` whose
  meaning depends on the backend).
- **TraceRecord**: one verified-or-rejected attempt; `success` is the *only*
  field that makes a record a positive transition. Verified and failed records
  are written to separate files.
- **Dataset builder**: classifies each record by *how real its verification
  was*, applies an explicit filter policy, splits by `theorem_name`, and writes
  the modeling artifacts.

---

## 4. Backend status

| Backend | Role | Status |
| --- | --- | --- |
| `mock` | candidate source + Lean runner | Working; deterministic; **not real verification** — pipeline/plumbing tests only |
| `manual-file` | candidate source | Working; reads hand/agent-authored candidate JSONL; no API key |
| `lean-cli` | Lean runner | Working on Windows + Unix; **real whole-file typecheck** (theorem-level); `state_after` is the placeholder `<verified by lean-cli>` |
| `leandojo` | Lean runner | **Experimental**: tracing + initial state work; `run_tac` blocked (see §5); real smoke test marked `xfail(strict=True)` |
| `anthropic` / `openai` | candidate source | Implemented, optional (needs API key); not exercised in this study |

The key distinction: **lean-cli confirms a whole file typechecks** — it does not
expose intermediate proof states — whereas **leandojo** is the only backend that
would yield true per-step `state_after`. lean-cli is therefore sufficient for
*tactic prediction* (the task here) but not for *next-state modeling*.

---

## 5. LeanDojo live-run investigation

LeanDojo was exercised against a real install (lean-dojo 4.20.0, Lean
toolchains v4.20.0 and v4.30.0) under WSL2 Ubuntu. Findings:

- **Tracing works.** The published mini repo traces and caches successfully.
- **Initial state works.** `runner.start(seed)` returns a real `TacticState` —
  e.g. for `id_of_p`: `pp = "p : Prop\nh : p\n⊢ p"`, `id=0`, `num_goals=1`.
- **`run_tac` is blocked.** The first `runner.run_tactic(state0, tactic)` raises
  `DojoCrashError: Unexpected EOF`. Root cause (reproduced with five scripts in
  `scripts/`): `lake env lean file.lean` runs theorem-body elaboration with an
  **empty/EOF stdin** (the same documented limitation as `#eval`), so LeanDojo's
  `lean_dojo_repl` elab tactic crashes on its first `IO.getStdin.getLine` with
  `[fatal] failed to parse JSON offset 0: unexpected end of input`. Disabling
  `Elab.async` does not help; the behavior is identical on Lean 4.20.0 and
  4.30.0. The Python `Dojo._read_next_line` happens to scrape the printed init
  line, which is why `start()` *looks* successful.
- **The runner is API-correct.** `Dojo.run_tac(state, tactic)` signature and the
  result classes (`TacticState`/`ProofFinished`/`LeanError`/`ProofGivenUp`,
  incl. `ProofFinished.tactic_state_id`) are pinned by mocked tests; the failure
  is in the Lean process, not project code.
- **Honest handling.** `tests/test_leandojo_smoke_real.py` is
  `xfail(strict=True)` — it still runs end-to-end when opted-in, but documents
  the gap and will XPASS loudly if a future Lean release restores
  elaboration-time stdin. Full diagnosis + reproducers: `docs/LEANDOJO_SETUP.md`
  §8.

**Consequence:** no real state-transition records exist; the dataset is
lean-cli-only (theorem-level) until LeanDojo is unblocked.

---

## 6. Dataset schema

Each row of `data/processed/basic_lean_cli/next_tactic.jsonl`:

| Field | Meaning |
| --- | --- |
| `theorem_name`, `theorem_statement`, `state_before`, `tactic` | the (input, target) pair; `state_before` is real |
| `verification_quality` | `real` (leandojo) · `theorem-level` (lean-cli) · `mock` — **how real the verification was** |
| `state_after_is_real` | `true` only for real leandojo intermediate/terminal states; **`false` for this whole corpus** |
| `proof_finished` | whether the tactic closed the goal (always `true` for lean-cli whole-file success) |
| `success` | the only field that makes a record a positive transition |
| `split` | `train`/`val`/`test`, assigned deterministically by `theorem_name` (no leakage) |
| `source_record_hash` | `sha256(theorem_name ‖ state_before ‖ tactic)` — dedup key + provenance |

The builder **refuses** to promote the lean-cli placeholder to a real state
(`state_after_is_real=false`), excludes `mock` rows unless `--allow-mock`, and
records every exclusion reason in `summary.json`.

---

## 7. The basic corpus

Generated from one Python source of truth (`scripts/generate_basic_corpus.py`),
core Lean 4 only (no Mathlib), in **21 pattern families** with ≥5 variants each.
Within a family the hypothesis names are held constant so the correct tactic
*string* is shared across variants — this is what lets a same-family train
theorem supply the tactic an eval theorem needs.

| Quantity | Value |
| --- | --- |
| Theorems | **134** |
| Pattern families | **21** |
| Candidate attempts | **616** |
| Verified (lean-cli) | **329** |
| Failed | **287** (0 timeouts) |
| Dataset rows (verified) | 329 |
| Unique tactics | 60 |
| Theorem split (train/val/test) | 102 / 16 / 16 |
| Row split (train/val/test) | 254 / 37 / 38 |

Every theorem has ≥1 verified tactic; every `expected_success_tactic` declared
by the generator actually typechecks. A coverage audit confirms **every val/test
theorem's family has a train representative** (only `eq_refl` and `or_comm`
landed train-only — harmless, just unevaluated).

> **Toolchain note.** Collection points `MINI_ELF_LEAN_COMMAND` at the concrete
> Lean toolchain binary, *not* the elan `lean` shim — the shim resolves the
> `stable` channel over the network and intermittently stalls 100s+ under WSL2,
> which once produced 108 spurious timeouts. Direct binary: ~0.17 s/call, 0
> timeouts, 616 attempts in ~1m45s.

---

## 8. Baselines

All five models predict `theorem_statement + "\n" + state_before → tactic` and
are scored by **lean-cli pass@k** (does any of the top-k predicted tactics
typecheck the theorem). `state_after` is never used as a target. Four are
covered here; **Mini-ELF v0** has its own section (§9).

1. **Majority** — predicts the top-k most frequent training tactics, ignoring
   input. The floor.
2. **Retrieval** — k-NN over training texts (char-2..4-gram cosine; would use
   sklearn TF-IDF if installed), returning deduplicated neighbor tactics.
3. **Log-linear classifier** — a softmax classifier (1-layer network)
   over hashed char-n-gram features with field-aware goal-line features,
   trained with seeded SGD; pure Python (no numpy in this env), deterministic,
   CPU. Training: 55 tactic classes, 254 rows, 80 epochs, lr 1.0, ~28 s, train
   top-1 acc 0.40 (ceiling ≈0.4 since each input maps to several verified
   tactics). It predicts one of a fixed set of full tactic strings.
4. **Generative AR seq2seq** — a **character-level encoder–decoder**: a
   bidirectional GRU encoder, additive (Bahdanau) attention, and a GRU decoder
   that emits the tactic one character at a time (PyTorch, CPU). Small by design:
   embedding 64, hidden 128, 1 layer, **410,309 parameters**, vocab 69 (built
   from the train split only). Trained 60 epochs with Adam (lr 0.003, batch 32,
   grad-clip 1.0, seed 0) in ~110 s; the checkpoint is selected by **val greedy
   exact-match** (epoch 41). Inference uses beam search (width 5, length penalty
   0.7) with top-k dedup. Unlike the classifier it is **open-vocabulary** — it
   can emit tactic strings never seen as a label.

All models read only `theorem_statement` and `state_before`; none reads
`state_after` (`Example` has no such field; `tests/test_ar_data.py` and
`tests/test_elf_embed.py` grep the AR/ELF sources for the access patterns).
PyTorch is an **optional** extra (`pip install -e .[ar]`); without it the
AR/Mini-ELF modules and their torch-gated tests skip cleanly.

---

## 9. Mini-ELF v0: embedded-flow tactic generation

The first **Mini-ELF prototype**. It is deliberately small and is a prototype of
the *generation loop* — **not** the full ELF method and **not** real proof-state
flow (verification is still theorem-level, `state_after_is_real=false`).

**Two-stage architecture (PyTorch, CPU; 342,965 params).**

1. **Tactic autoencoder** (`elf_embed.py`) — a char-level GRU encoder maps a
   tactic string to a fixed **latent vector (dim 48)**; a GRU decoder, conditioned
   on that latent at every step, reconstructs the string. This defines the
   continuous latent space and gives a way to turn an arbitrary latent *back* into
   a tactic. It is **frozen** after stage 1 (val reconstruction **0.89**), and the
   train latents are standardized (per-dim mean/std) so the flow target matches
   `N(0,I)`. (ae 120,597 params.)
2. **Conditional rectified flow** (`elf_flow.py`) — a bi-GRU **condition encoder**
   (172,912 params) embeds the prompt to a vector `c`; a 3-layer SiLU **MLP**
   (49,456 params) learns a velocity field `v_θ(z_t, t, c)`. Flow-matching:
   `ε ~ N(0,I)`, `z_t = (1−t)·ε + t·x`, target velocity `v = x − ε`, MSE loss.
   Trained 60 (AE) + 300 (flow) epochs with Adam in **~104 s**; flow checkpoint
   chosen by an offline val signal (epoch 60).

**Sampling.** Draw 32 noise vectors `ε`, **Euler-integrate** `dz/dt = v_θ`
(10 steps) from `z(0)=ε` to `z(1)`, un-standardize, and turn each latent into a
string by one of two **decode modes**, then dedup and rank by sample frequency:

- **`decoder` (generative Mini-ELF path)** — run the AE decoder on the latent.
  This can emit tactic strings never seen as a label (open-vocabulary), and is
  the honest Mini-ELF result.
- **`nn` (latent nearest-neighbour ablation)** — snap the latent to the closest
  train-tactic latent and return that tactic. This is robust and strong on
  `pass@k`, but it is **latent-space retrieval, not generation** (it can only
  emit tactics already in the train set; novel-candidate rate 0).

### Model ladder (lean-cli pass@k)

| model | val pass@1 | test pass@1 | val pass@5 | test pass@5 |
| --- | --- | --- | --- | --- |
| majority | 0.08 | 0.16 | 0.16 | 0.16 |
| retrieval (char-n-gram) | 0.22 | 0.16 | 0.22 | 0.32 |
| log-linear classifier | 0.46 | 0.55 | 0.65 | 0.76 |
| AR seq2seq (generative) | **0.70** | **0.76** | 0.78 | 0.82 |
| Mini-ELF v0 (decoder, generative) | 0.51 | 0.61 | **0.84** | **0.90** |
| Mini-ELF v0 (nn, retrieval ablation) | 0.65 | 0.76 | 0.89 | **1.00** |

**Precision vs recall.** **AR wins `pass@1`** (its single top guess is right most
often: test 0.76). **Mini-ELF v0 (decoder) wins `pass@5`** (recall): test 0.90 vs
AR 0.82, because integrating the flow from 32 independent noise draws yields ~20
*distinct* candidates per prompt (vs AR's ≤5 beam), so the verified tactic lands
in the top-5 more often — but the most-frequent sample (the top-1) is a noisier
point estimate, so it trails AR on `pass@1`. The `nn` ablation tops `pass@k`
(test `pass@5` 1.00) but, again, is retrieval, not generation.

### Examples

- **Successful alternative proof.** For `and_intro_ab` (goal `p ∧ q`, gold
  `exact ⟨hp, hq⟩`), Mini-ELF generated the verified *alternative*
  `constructor\n  exact hp\n  exact hq` — a different valid proof, not a copy of
  the gold.
- **Failed garbled / witness errors.** Off-distribution flow latents decode to
  char-level garble (`constructoontroctoo`; `acases h with | ales h with h with
  h with …` repetition collapse) or wrong witnesses (`exact ⟨a, rfl⟩`,
  `exact ⟨1, rfl⟩` for `exists_nat_0` whose answer is `⟨0, rfl⟩`). ~40% of
  candidates are novel but **none verified** (`novel_verified=0`), so its
  open-vocabulary reach is weaker than AR's.

---

## 9b. Mini-ELF v1: verifier-aware reranking + structure + witness-copy

v1 keeps the v0 latent + flow generator (it is still a tactic-string prototype,
still theorem-level, `state_after_is_real=false`) and adds four modules, each
targeting an observed v0 weakness. New code lives beside v0 (`elf_structure.py`,
`elf_rerank.py`, `elf_witness.py`, `elf_v1_{train,sample}.py`); v0 is byte-for-byte
untouched.

**A. Structure-aware condition encoder** (`elf_structure.py`). A heuristic parser
splits the prompt on the `⊢` turnstile into hypotheses + goal, classifies the
goal shape (`and/or/iff/implication/equality/exists/...`), and extracts numeric
literals and the parsed binary structure of `∧`-hypotheses / `∨`-goals. The v1
`StructuredConditionEncoder` is the v0 raw-prompt bi-GRU **plus** a goal bi-GRU, a
learned goal-shape embedding, and numeric features, projected to `c`.

**B. Denoising tactic-AE** (`elf_v1_train.py`). Encoder input chars are corrupted
(`ae_denoise_prob=0.1`) and Gaussian noise is added to the latent before decoding
(`ae_latent_noise_std=0.1`); the target stays the clean tactic. This widens the
basin of latents that decode to *valid* strings. A calibration sweep showed it
keeps clean AE reconstruction at **0.892** (no loss vs v0) while lifting the
candidate-pool recall — the diversity rose to **~35 distinct candidates/row**
(64 noise samples).

**C. Verifier-aware reranker** (`elf_rerank.py`) — *the highest-value module*. A
small CPU classifier scores `(condition, candidate) → P(verifies)` from a
char-GRU over the prompt, a char-GRU over the candidate, and **hand features**:
bracket balance, a *known-token ratio* (catches decoder garble), *numeric match*,
*conjunct/disjunct consistency* (does `h.1` project the conjunct the goal needs?
does `Or.inl` match the disjunct the hypothesis proves?), and a **context-binding
ratio** (does the candidate reference hypotheses that exist, or hallucinate
`hp`/`hq`?). It is trained on *previous Lean outcomes* — verified traces
(positive) and failed traces (negative) — **plus self-training hard negatives**:
v1's own flow candidates generated on the **train** theorems and labelled by Lean
(1,224 distinct, 243 pass / 981 fail). The self-training is the load-bearing
trick: trace-only training let token features alone hit AUC 1.0, so the model
*ignored* the structural features and saturated at score 1.0 on every plausible
candidate (it actively **hurt** `pass@5`, 0.89→0.65). With flow-distribution hard
negatives that share the positives' tokens, the model is forced to use the
structural features. On held-out candidates it then scores verified ones
**0.97–1.0** vs failed **0.21–0.30**.

**D. Witness-copy augmentation** (`elf_witness.py`). For `∃` goals it copies
numeric literals (and value identifiers) out of the prompt into the templates
`exact ⟨N, rfl⟩` / `refine ⟨N, ?_⟩; rfl` — an explicit **symbolic** augmentation
(not a neural pointer), merged with the flow candidates and tagged `witness_copy`
so its contribution is auditable, then verified by the *same* Lean verifier.

**Sampling + ranking** (`elf_v1_sample.py`). Draw 64 flow candidates; add witness
candidates; deduplicate. Without a reranker → frequency order. With a reranker →
rerank a **shortlist** (top-16 flow by frequency ∪ all witnesses) by a
frequency-*blended* reranker score, keeping the frequency tail after it. The
shortlist bound is what lets reranking improve top-1 *without* pushing recall out
of the top-5.

**Results (lean-cli pass@k; full table in §10).**

| mode | val p@1 | test p@1 | val p@5 | test p@5 | invalid@1 | novel_verified |
| --- | --- | --- | --- | --- | --- | --- |
| v1 decoder (no rerank) | 0.38 | 0.66 | 0.89 | 0.89 | 0.62 / 0.34 | 2 |
| v1 rerank | **0.89** | **0.89** | 0.89 | 0.89 | **0.11** | 2 |
| v1 rerank + witness | **0.89** | **0.89** | **1.00** | **0.95** | **0.11** | **10 / 2** |

- **Reranker effect:** test `pass@1` 0.66 → **0.89**, invalid@1 0.34 → **0.11**,
  with `pass@5` preserved. The raw flow decoder's frequency top-1 is *noisier*
  than v0 (more samples); the reranker, not the sampler, supplies the precision.
- **Witness effect:** `exists_witness` `pass@5` **0.0 → 1.0** (both splits);
  `exact ⟨5, rfl⟩` / `⟨7, rfl⟩` (val) and `refine ⟨0, ?_⟩; rfl` (test) verify as
  *novel* generations. `novel_verified` 0 → **10 (val) / 2 (test)**.
- **Structure effect:** `and_elim` and `or_intro` top-1 family accuracy
  **0.00 → 1.00** (val) — the relational sibling wall that stood at 0.00 for
  *every* prior model, AR included.

**Honesty.** v1 is still **not** the full ELF method and **not** real proof-state
flow. Witness-copy is symbolic augmentation, not neural generation. The reranker's
clean separation partly reflects the small, templated corpus and its self-training
loop. `exists_witness` is solved at `pass@5`, not `pass@1` (the witness lands at
rank 2–3); `or_self_elim` (a multi-step case split) is still unsolved
(`pass@5` 0). The `nn` row remains retrieval. 16–17 eval theorems/split →
directional.

---

## 10. Full results

134-theorem corpus, theorem-level split 102/16/16 (val 37 rows / 16 theorems,
test 38 rows / 16 theorems). lean-cli pass@k.

| model | split | top1_exact | top5 any-verified | pass@1 | pass@3 | **pass@5** |
| --- | --- | --- | --- | --- | --- | --- |
| majority | val | 0.03 | 0.16 | 0.08 | 0.16 | 0.16 |
| retrieval | val | 0.08 | 0.22 | 0.22 | 0.22 | 0.22 |
| log-linear | val | 0.19 | 0.65 | 0.46 | 0.59 | 0.65 |
| AR seq2seq | val | 0.30 | 0.78 | **0.70** | 0.70 | 0.78 |
| Mini-ELF v0 (decoder) | val | 0.22 | 0.84 | 0.51 | 0.84 | **0.84** |
| Mini-ELF v0 (nn) | val | 0.27 | 0.89 | 0.65 | 0.89 | 0.89 |
| **Mini-ELF v1 (rerank)** | val | 0.38 | 0.89 | **0.89** | 0.89 | 0.89 |
| **Mini-ELF v1 (rerank+witness)** | val | 0.38 | 1.00 | **0.89** | **1.00** | **1.00** |
| majority | test | 0.05 | 0.16 | 0.16 | 0.16 | 0.16 |
| retrieval | test | 0.05 | 0.32 | 0.16 | 0.16 | 0.32 |
| log-linear | test | 0.21 | 0.76 | 0.55 | 0.71 | 0.76 |
| AR seq2seq | test | 0.32 | 0.82 | **0.76** | 0.82 | 0.82 |
| Mini-ELF v0 (decoder) | test | 0.24 | 0.90 | 0.61 | 0.82 | **0.90** |
| Mini-ELF v0 (nn) | test | 0.32 | 1.00 | 0.76 | 0.92 | **1.00** |
| **Mini-ELF v1 (rerank)** | test | 0.37 | 0.89 | **0.89** | 0.89 | 0.89 |
| **Mini-ELF v1 (rerank+witness)** | test | 0.37 | 0.95 | **0.89** | 0.95 | **0.95** |

Among v0/AR, AR leads `pass@1`, Mini-ELF v0 (decoder) leads generative `pass@5`,
and the `nn` ablation tops `pass@k` (retrieval, not generation). **Mini-ELF v1
(rerank+witness) leads both axes among generative models** — `pass@1` 0.89 and
`pass@5` 0.95 (test) — see §9b. Note v1's `top1_exact` (0.37–0.38) stays modest:
the reranker maximizes *whether some top-1 candidate verifies* (`pass@1`), and the
verified top-1 is often a valid *alternative* rather than the exact gold string.

> Small-sample caveat: 16 eval theorems per split — these numbers are
> directional, not statistically tight.

### Sibling-family top-1 *family* accuracy

Majority and retrieval scored **0.00** on every sibling group, both splits.

| sibling group | log-linear v/t | AR v/t | v0 dec v/t | **v1 rerank v/t** |
| --- | --- | --- | --- | --- |
| `eq` (refl / symm / trans) | 1.00 / 1.00 | 1.00 / 1.00 | 0.50 / 0.50 | 1.00 / 1.00 |
| `imp` (identity / compose / modus_ponens) | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| `iff` (mp / mpr / intro) | 0.00 / 0.75 | 1.00 / 1.00 | 0.50 / 1.00 | 1.00 / 1.00 |
| `or_intro` (left / right) | 0.00 / 0.00 | 0.50 / 0.50 | 0.50 / 0.25 | **1.00 / 1.00** |
| `and_elim` (left / right) | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | **1.00 / 1.00** |

`and_elim` (goal = first vs second conjunct) stood at **0.00 for every prior
model, AR included**; **Mini-ELF v1's reranker is the first to reach 1.00** on
both `and_elim` and `or_intro`, via its conjunct/disjunct-consistency features
(it scores `h.left`/`h.right`/`Or.inl`/`Or.inr` against the parsed goal+hypothesis
structure). v1 numbers are the `decoder_rerank` mode.

### Generation quality (AR vs Mini-ELF decoder)

| metric | AR val/test | Mini-ELF val/test |
| --- | --- | --- |
| avg generated length (top-1) | 17.9 / 16.3 | 13.5 / 14.2 |
| empty-generation rate | 0.00 / 0.00 | 0.00 / 0.00 |
| **distinct candidates / row** | ≤5 / ≤5 | **20.3 / 19.1** |
| novel-candidate rate | 0.47 / 0.50 | 0.42 / 0.41 |
| candidate-invalid rate | 0.65 / 0.65 | 0.70 / 0.67 |
| novel candidates that verified | 0 / 2 | 0 / 0 |

---

## 11. Analysis

(Mini-ELF v0's precision/recall mechanism, examples, and open-vocabulary gap are
analysed in §9; this section covers the other models and the cross-model wall.)

**Why retrieval improved after coverage expansion.** On the earlier 43-theorem
corpus, every proof pattern was one-of-a-kind, so the by-theorem split isolated
each pattern entirely into val/test; the training set then contained *no example
of the tactic an eval theorem needed*, and both baselines scored 0% pass@k —
a coverage gap, not a code bug. Growing to 21 families × ≥5 variants makes most
families straddle train and eval, so a same-family train theorem supplies the
exact (string-identical) tactic, and retrieval rises to pass@5 0.22/0.32.

**Why the log-linear classifier beats retrieval.** Retrieval copies the *single
nearest neighbor's* tactic; when the nearest neighbor is a structurally similar
sibling, the copy is wrong and the top-5 fills with near-identical theorems'
tactics. The classifier instead learns global weights and ranks a family's
shared correct tactic high, so per-family pass@5 jumps to 1.00 for families
retrieval scored 0.00 on (`and_comm`, `eq_trans`, `iff_mp`, `imp_compose`,
`imp_identity`, `and_intro`, `iff_intro`, `iff_mpr`, `modus_ponens`,
`or_intro_right`). Net: pass@5 0.65/0.76 vs 0.22/0.32.

**Sibling-family confusion.** The classifier *solves* sibling groups whose
correct tactics are lexically distinct — `eq` (`rfl` vs `h.symm` vs
`h1.trans h2`) and `imp` reach top-1 family accuracy 1.00. It *fails* the groups
whose only discriminator is **relational position**: `and_elim_left`
(`⊢ p` → `h.1`) vs `and_elim_right` (`⊢ q` → `h.2`), and `or_intro` left vs
right, stay at 0.00 — the confusion matrix shows it emitting the wrong sibling's
tactic. A bag-of-n-gram model cannot represent "the goal equals the *first* vs
*second* conjunct"; this needs positional/structural awareness.

**Why the AR model beats the classifier.** pass@1 is where the gap is starkest
(test 0.76 vs 0.55): the classifier's single argmax is one fixed tactic string,
whereas the decoder composes the tactic conditioned on the input, so its top
beam hypothesis matches the goal more often. The attention over the goal line
also lets it separate sibling families the bag-of-n-gram classifier could not —
it newly solves `iff` (top-1 family accuracy 1.00 vs 0.00/0.75) and reaches 0.50
on `or_intro`. It also shrinks the set of 0-pass@5 families to
`{exists_witness, or_self_elim}` (val) and `{and_elim_left}` (test).

**Open-vocabulary — partial, and the most interesting finding.** ~50% of the AR
model's top-5 candidates are *novel* strings (not a training label), which a
fixed-class classifier can never produce. Concretely, the model learns the
**template** `exact ⟨N, rfl⟩` and varies the witness `N` over the small numbers
`{0,1,2}` seen in training. This is enough to solve `exists_nat_0` on test (the
classifier's hard 0-pass@5 case), but it still **fails** `exists_nat_5` and
`exists_nat_7` on val — it never learned to emit `5` or `7`. So the
open-vocabulary capability is real but **bounded: template composition, not
unbounded numeric extrapolation.** On test, 2 verified candidates were genuinely
novel strings.

**Honest failure modes.** Character-level decoding produces its own errors: the
model once generated `exact And.righ` (the final `t` of `And.right` dropped) and
incomplete blocks such as `constructor\n  exact hp\n ` (missing the second
`exact`). Of the 5 beam candidates per row, typically 1–2 verify (candidate-
invalid rate ~0.65) — beam diversity is what lifts pass@5 above pass@1.

**The hard wall: relational `and_elim`.** Top-1 *family* accuracy on `and_elim`
stays 0.00 even for the AR model — distinguishing `and_elim_left` (`⊢ p` → `h.1`)
from `and_elim_right` (`⊢ q` → `h.2`) requires representing *which* conjunct the
goal equals, a relational/structural fact neither a char-n-gram classifier nor a
char-level seq2seq captures reliably. This is the cleanest remaining motivation
for a structure-aware model — and it stays 0.00 for Mini-ELF v0 too. (Mini-ELF's
recall/precision tradeoff and its weaker, non-verifying open-vocabulary behaviour
are covered in §9.)

---

## 12. Limitations

- **No real state-transition supervision.** All verification is theorem-level;
  `state_after_is_real=false` for the entire corpus — the AR model included. The
  AR model is a *tactic generator scored at theorem level*, **not** a
  `state_before → tactic → state_after` model. Do not interpret these results as
  next-state modeling.
- **LeanDojo `run_tac` is blocked** on this Lean toolchain (elaboration-time
  stdin EOF); documented and `xfail`'d, not hidden.
- **Small corpus / small eval splits** (134 theorems; 16 eval theorems per
  split) — metrics are diagnostic, not statistically powered.
- **The trained models are deliberately small** (AR 410K, Mini-ELF v0 343K
  params; char-level, CPU). They are sequence/flow models, but not large or
  pretrained; PyTorch is an optional extra. Their open-vocabulary ability is
  partial (AR) or non-verifying (Mini-ELF decoder).
- **Mini-ELF v0 is a small prototype, not the full ELF method.** It is a tactic
  autoencoder + conditional rectified-flow generator that does **not** model real
  proof-state flow. Its generative (decoder) path trails AR on `pass@1` and its
  novel generations don't yet verify (`novel_verified=0`); the nn-decode variant
  is strong on `pass@k` but is latent-space retrieval, not generation. No
  diffusion; no next-state results.
- **Synthetic, template-generated candidates** (`source="manual-corpus"`); no
  real LLM proposals were collected in this study.
- **Relational `and_elim` (left vs right) and out-of-range numeric witnesses are
  unsolved** by every model.

---

## 13. Future work

1. **Real LLM proposals at scale** (anthropic/openai) with prompt-style
   comparison, to grow tactic diversity beyond hand-written templates.
2. **Larger corpus** with more variants per family (and more families), so
   metrics become statistically meaningful and open-vocabulary cases recur.
3. ~~A generative AR sequence model.~~ **Done**: the char-level GRU
   encoder–decoder (§8) beats the classifier on every `pass@k`, cracks the `iff`
   and (partly) `or_intro` siblings, and demonstrates partial open-vocabulary
   generation.
4. ~~A first Mini-ELF prototype.~~ **Done — Mini-ELF v0** (§9). The **Mini-ELF v1**
   roadmap (likelihood ranking, better latent decoder, copy/pointer witnesses,
   structure-aware conditioning, real next-state supervision) is detailed in §9.
5. **Structure-aware model** to crack relational `and_elim` (top-1 family
   accuracy 0.00 for every model) — positional/relational features or a small
   transformer with structural encodings.
6. **A LeanDojo/`run_tac` alternative** to obtain real `state_after`: either fix
   the elaboration-stdin path, pin a Lean version where it works, or add an
   interactive-REPL backend — unlocking true next-state supervision.
7. **The full ELF embedded-flow research target** — real proof-state flow,
   evaluated with the same lean-cli `pass@k` harness. Depends on (6). Mini-ELF v0
   is a prototype of the *generation loop*, not this method.

---

## 14. References

Pointers to the external work this project builds on. Informal — exact
bibliographic details are intentionally not fabricated; consult the sources.

- **ELF / embedded language flow** — the eventual research target this project is
  *inspired by* (continuous embedded-flow generation). See the Mini-ELF reference
  linked from the README (OpenReview: `tnx1VvrcAn`).
- **Lean 4** — the theorem prover and `lean` CLI used for all verification
  (`leanprover/lean4`, toolchain v4.30.0 here).
- **LeanDojo** — the interaction library evaluated as the `leandojo` backend
  (tracing + `Dojo.run_tac`); see `docs/LEANDOJO_SETUP.md` for the investigation.
- **Flow matching / rectified flow** — the training objective Mini-ELF v0's flow
  model is *inspired by* (straight-line interpolation `z_t=(1−t)·ε+t·x`, constant
  target velocity `v=x−ε`); our implementation is a small from-scratch MLP.
- **PyTorch** — the CPU framework for the AR and Mini-ELF models (optional `.[ar]`
  extra).

> These are attributions of inspiration and tooling, not claims of equivalence.
> Mini-ELF v0 is an independent small prototype, not a reimplementation of any
> cited method.
