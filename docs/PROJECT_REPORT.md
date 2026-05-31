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

## 9c. Mini-ELF v2: generalization / robustness study

§9b's v1 numbers are in-distribution on a small, **templated** corpus. v2 is a
**stress test**, not a new model. It builds a harder 94-theorem corpus
(`scripts/generate_hard_corpus.py`: 14 compositional families — multi-step
implication chains, nested `∧` projection, `∨`-elimination, iff/eq composition,
`∃` with unseen literals; 204 verified / 0 zero-success / 0 timeouts), adds
adversarial / family / difficulty **split strategies** (`src/mini_elf_lean/splits.py`),
evaluates the existing v1 model on the hard corpus with **no retraining**, and
trains a v2 model on the combined corpus. Full write-up:
[`V2_GENERALIZATION_REPORT.md`](V2_GENERALIZATION_REPORT.md).

**Central finding — v1 does not transfer.** lean-cli `pass@5`:

| split | v1 basic (in-dist) | v1 transfer→hard | v2 (combined) |
| --- | --- | --- | --- |
| hash | 0.95 | **0.23** | **1.00** |
| difficulty_holdout | — | 0.06 | **0.06** |
| adversarial_sibling | — | 0.11 | **0.53** |
| family_holdout | — | 0.00 | (not trained) |

The learned generator+reranker collapse under shift (`invalid@1` → 0.92–1.00);
only the **symbolic witness-copy** transfers. **v2 recovers in-distribution-hard**
(0.23→1.00 — v1's collapse was data-coverage, not architecture) and **partially**
recovers adversarial siblings (0.11→0.53, cracking `eq`/`imp` but not
`and_elim`/`or_intro`), but shows **no compositional generalization**
(difficulty-holdout 0.06) and **regresses the basic corpus** (0.95→0.82, a
fixed-capacity tradeoff). The reranker mis-calibrates off-distribution
(verified/failed score gap 0.97/0.25 → ~0.9/0.5). LLM proposal pilot **skipped**
(no API key; not faked).

## 9d. Mini-ELF v3: structured proof-block planner

v2 left one wall standing: compositional generalization (`difficulty_holdout`
`pass@5` 0.06 — the flat generator never learns to *compose* an unseen
multi-step proof). v3 keeps the entire v2 model and adds a deterministic
**symbolic planner** (`src/mini_elf_lean/proof_planner.py`) that parses the goal
into typed hypotheses and **constructs** proof blocks via a depth-bounded
backward search + a template library: implication/modus-ponens chains
(`h3 (h2 (h1 h))`), nested `∧` projection (`h.2.2` / `h.left.right`), `∧`-intro
(`⟨…⟩` / `constructor` / `And.intro`), `∨`-elim case splits (`cases`/`rcases`/
`Or.elim`) and `∨`-intro, iff `.mp/.mpr` composition, and equality `.trans/.symm`
path search. `∃`-goals defer to witness-copy. Candidates are fused above the v2
flow + reranker in a **tier policy** (`elf_v3_sample.MiniElfV3Baseline`): planner
first (by symbolic priority), then witness, then the v2 reranked flow pool +
tail — because the v2 reranker mis-calibrates off-distribution and would bury the
correct planner blocks (it scores them 0.25–0.86 though they all verify). Full
write-up: [`V3_PROOF_PLANNER_REPORT.md`](V3_PROOF_PLANNER_REPORT.md).

**Result — the compositional wall moves.** lean-cli `pass@5`:

| split | v1 transfer | v2 | **v3** | v3 pass@1 |
| --- | --- | --- | --- | --- |
| **difficulty_holdout** (compositional) | 0.06 | 0.06 | **1.00** | 0.98 |
| adversarial_sibling | 0.11 | 0.53 | **1.00** | 1.00 |
| hash | 0.23 | 1.00 | **1.00** | 1.00 |
| basic test | 0.95 | 0.82 | **1.00** | 1.00 |

The `--no-planner` ablation (same model, same split) stays at `pass@5` **0.083**
— the entire lift is the planner; v3 also **recovers the basic regression** v2
introduced (0.82→1.00), making it the only uniform improvement in the project.
On `difficulty_holdout` the planner alone solves **88 / 96** theorems the flow
generator cannot, and **every** planner candidate that reached the top-5
verified. **Honest framing:** this is *engineered symbolic coverage* of the
corpus's proof shapes, **not** learned generalization — the planner is
indifferent to the train/test split because it constructs proofs from the parsed
goal, but on a proof shape with no matching template it would fail like v1/v2.
v3 therefore *reframes* the open problem (handle/learn shapes outside the
template library) rather than closing it. The 2 `difficulty_holdout` pass@1
misses are a witness-ordering quirk (`exists_hyp_copy_12`). LLM pilot still
**skipped** (no API key; not faked).

## 9e. Mini-ELF v4: planner-blind generalization benchmark

v3 saturated the hard corpus by *engineered symbolic coverage*, so v4 asks where
that coverage ends. A coverage audit (`scripts/audit_planner_coverage.py`)
confirms the planner is **blind** to negation/contradiction, contrapositive
`¬`-goals, `∃`-elimination, `∀`-instantiation, and rewrite/substitution. The v4
corpus (`scripts/generate_planner_blind_corpus.py`: 61 theorems / 10 families /
157 verified / 0 zero-success) is built from exactly those shapes. Full write-up:
[`V4_PLANNER_BLIND_REPORT.md`](V4_PLANNER_BLIND_REPORT.md).

**Unchanged systems collapse** (lean-cli `pass@5`, all 61 theorems held-out):

| system | pass@5 | note |
| --- | --- | --- |
| AR seq2seq | 0.00 | nothing solved |
| Mini-ELF v1 | 0.096 | witness-copy only |
| Mini-ELF v2 | 0.096 | witness-copy + a little flow |
| **Mini-ELF v3 (planner unchanged)** | **0.096** | planner verifies **0**; only `exists_reconstruct` (witness shortcut) |

v3 drops from 1.00 (hard difficulty) to **0.096** — the corpus is genuinely
planner-blind. **Controlled template-addition ablation** (optional, explicitly
-labelled `proof_planner_v4.py`; *not* folded into v3): adding `planner_negation`
takes the 5 negation families 0.00 → **1.00** (global 0.61); adding
`planner_exists_elim` takes those 2 families to 1.00 (global 0.31); both → 0.83;
new templates verify **241/241** and **68/68**. But `forall_inst` and
`rewrite_succ` (no template added) **stay at 0.00** even with both — symbolic
coverage is per-shape whack-a-mole, never complete. LLM pilot **skipped** (no
API key; not faked). This benchmark is neither too easy (every prior system
fails) nor trivially saturable (two families resist the ablation).

## 9f. Mini-ELF v5: data-driven candidate proposers (off whack-a-mole)

v4 left `forall_inst` / `rewrite_succ` at 0.00 even with both hand-written
template sets. v5 asks the real question: can a *data-driven* proposer produce
useful proof blocks on those shapes **without** a per-shape template? It adds a
common `CandidateProposer` interface (`src/mini_elf_lean/proposer.py`) wrapping
every source — flow / planner / witness / manual-oracle / **LLM** / **retrieval**
— and a fusion baseline (`elf_v5_sample.py`). Full report:
[`V5_RESULTS_SUMMARY.md`](V5_RESULTS_SUMMARY.md), targets
[`V5_TARGET_FAMILIES.md`](V5_TARGET_FAMILIES.md), failures
[`V5_FAILURE_EXAMPLES.md`](V5_FAILURE_EXAMPLES.md).

To give retrieval same-family donors without leaking the test theorem, a new
**`family_interpolation`** split (`splits.py`) carves each family into held-out
test theorems + same-family train donors → `data/processed/planner_blind_split_lean_cli`
(29 train / 32 test theorems). All configs are re-run on this same 32-theorem
split (it is **not** the v4 all-test 61 set, so the two are not directly
comparable).

**The retrieval proof-block proposer** (`retrieval_proposer.py`) retrieves
verified blocks by char-n-gram similarity and *lightly adapts* them: numeric
substitution copies the goal's LHS literal into `exact h _` (for `forall_inst`),
verbatim reuse handles the rest (constant hyp names within a family). Results
(lean-cli `pass@5`, split test):

| config | pass@5 | forall_inst@5 | rewrite_succ@5 | note |
| --- | --- | --- | --- | --- |
| v3 (unchanged) | 0.107 | 0.00 | 0.00 | off-library collapse (mirrors all-test 0.096) |
| v4 templates (both, labelled) | 0.821 | **0.00** | **0.00** | recovers negation/∃-elim, not the targets |
| **retrieval (alone, no template)** | 0.595 | **1.00** | **1.00** | numeric adapt + verbatim reuse |
| retrieval-verbatim (no adapt) | 0.571 | 0.33 | 1.00 | ablation: adaptation lifts `forall_inst` |
| v3 ⊕ retrieval | 0.595 | 1.00 | 1.00 | `novel_verified` 20 |
| **v3 + v4-tmpl ⊕ retrieval** | **1.00** | 1.00 | 1.00 | template + proposer complementary |
| LLM (alone) | — | — | — | **skipped, no API key** (not faked) |

- **Retrieval escapes whack-a-mole on the targets**: `forall_inst` /
  `rewrite_succ` reach `pass@5` 1.00 with **no** hand-written template — the exact
  families v4 templates could not reach. The `retrieval` vs `retrieval-verbatim`
  comparison isolates numeric adaptation as the lift on `forall_inst`.
- **Complementary, not competing**: hand-written templates cover the negation
  families retrieval confuses; retrieval covers the template-less targets; the
  union reaches `pass@5` 1.00.
- **Honest limits**: retrieval is **example reuse + adaptation, not reasoning**;
  it needs same-family donors; and char-n-gram similarity reproduces the v1
  **sibling-confusion** failure (`neg_exfalso` 0.00, `exists_elim_conj` 0.25 —
  the wrong-family / wrong-direction donor out-ranks the correct one). The **LLM**
  proposer is implemented + unit-tested but **API-key-gated** (skipped, wrote
  `V5_LLM_PILOT_SKIPPED.md`); a learned seq2seq proposer is **deferred** to v6
  with rationale (`V5_LEARNED_PROPOSER.md`).

## 9g. Mini-ELF v6: structure-aware retrieval (fixing v5's ranking)

v5 retrieval solved the targets at `pass@5` but ranked by char-similarity alone,
so it mis-ranked siblings: `forall_inst` pass@1 0.00 (the adapted `exact h 13`
sat below the stale verbatim `exact h 3`), `neg_exfalso` 0.00 and
`exists_elim_conj` 0.25 (the wrong-family / wrong-direction donor out-ranked the
correct one). v6 adds **heuristic structural features**
(`src/mini_elf_lean/retrieval_features.py`: goal shape, hypothesis-shape flags, a
guessed `required_operation`, left/right conjunct position, connective multiset)
and a `StructureAwareRetrievalProposer` that re-scores the **same** retrieved
candidates by a weighted sum (char + goal-shape + operation + connective +
numeric + hyp-shape + conjunct-match − penalties), plus an adapted-candidate
preference (rank a safe adaptation above its stale verbatim donor, goal-LHS
first). Reports: [`V6_STRUCTURE_AWARE_RETRIEVAL_REPORT.md`](V6_STRUCTURE_AWARE_RETRIEVAL_REPORT.md),
[`V6_RETRIEVAL_FAILURE_ANALYSIS.md`](V6_RETRIEVAL_FAILURE_ANALYSIS.md),
[`V6_FAILURE_EXAMPLES.md`](V6_FAILURE_EXAMPLES.md).

Same `family_interpolation` split as v5 (32 test / 29 train). lean-cli pass@k:

| config | pass@1 | pass@5 | forall_inst@1 | exists_elim_conj@5 | neg_exfalso@5 |
| --- | --- | --- | --- | --- | --- |
| v5 retrieval (char-sim) | 0.357 | 0.595 | 0.00 | 0.25 | 0.00 |
| **v6 retrieval (structure-aware)** | **1.000** | **1.000** | **1.00** | **1.00** | **1.00** |
| v5 fusion | 0.357 | 0.595 | 0.00 | 0.25 | 0.00 |
| v6 fusion | 0.952 | 1.000 | 1.00 | 1.00 | 1.00 |
| v6 — no structural (ablation) | 0.393 | 0.595 | 1.00 | 0.25 | 0.00 |
| v6 — no adapt-pref (ablation) | 0.952 | 1.000 | 1.00 | 1.00 | 1.00 |

- **Structure-aware ranking fixes all four v5 failures**; retrieval-alone reaches
  global pass@1 = pass@5 = **1.00**.
- **The structural terms cause it**: the `no structural` ablation collapses back
  to ~v5 (negation/∃-elim pass@1 → 0), while `forall_inst` stays fixed (that is
  the adaptation + LHS-first tie-break, not the structural terms).
- **`no adapt-pref` is unchanged** from full v6 — the adapted-first tie-break
  already handles `forall_inst`; the explicit stale-literal penalty is redundant
  on this corpus (reported, not hidden).
- **Honest scope**: v6 changes *ranking only* — no proof templates, no
  `state_after`, no LLM; still **example reuse**, not reasoning (the `no
  structural` collapse and the dependence on same-family donors show this). In
  *fusion*, v3's unfixed `∃, ∧` planner mis-parse still occupies rank 0 on the
  right-projection theorems, so fusion `exists_elim_conj` pass@1 is 0.50 vs
  retrieval-alone 1.00 (v3 is deliberately left unchanged).

## 9h. Mini-ELF v7: retrieval under donor scarcity (family/operation holdout)

v6 left one question open and unasked: its `family_interpolation` split keeps a
**same-family donor in train for every test row**, so its pass@5 1.00 might be
interpolation, not transferable proof structure. v7 answers it. It builds a graded
donor-scarcity benchmark (`src/mini_elf_lean/retrieval_splits.py`,
`scripts/build_planner_blind_retrieval_splits.py`) over the 61 planner-blind
theorems and re-measures v5/v6 plus a template-free abstraction re-ranker
(`retrieval_abstraction{,_proposer}.py`) with real lean-cli. Reports:
[`V7_RETRIEVAL_HOLDOUT_REPORT.md`](V7_RETRIEVAL_HOLDOUT_REPORT.md),
[`V7_DONOR_AVAILABILITY_AUDIT.md`](V7_DONOR_AVAILABILITY_AUDIT.md),
[`V7_FAILURE_EXAMPLES.md`](V7_FAILURE_EXAMPLES.md).

> ⚠️ Holdout numbers are **not comparable** to v6's 1.00 on the interpolation
> split — a different, harder regime, built precisely to remove the same-family
> donors interpolation provides.

| split (pass@5) | donor condition | v5 | v6 | v7_abstract |
| --- | --- | --- | --- | --- |
| `current` (interpolation) | abundant same-family | 0.595 | **1.000** | 1.000 |
| `kshot_2` | 2 same-family / family | — | **1.000** | 1.000 |
| `kshot_1` | 1 same-family / family | — | 0.908 | **0.939** |
| `literal_holdout` | schema in train, literal unseen | 1.000 | **1.000** | 1.000 |
| `family_holdout` | **no same-family donor** | 0.000 | **0.000** | 0.000 |
| `operation_holdout` | **no same-operation donor** | 0.000 | **0.000** | 0.000 |
| `kshot_0` | no donors (floor) | — | **0.000** | — |

- **The cliff is presence vs. absence of a same-family donor, not quantity.** With
  ≥1 same-family donor (incl. 1-shot) retrieval scores 0.91–1.00; with **zero**
  every config collapses to 0.00.
- **v6's interpolation 1.00 is same-family reuse.** On the *same* rich split,
  forbidding same-family donors at retrieval time drops v6 to **0.00** (pass@1 too);
  its rank-0 donor is same-family **100%** of the time. Forbidding same-*operation*
  leaves only 0.107 — exactly the `exists_reconstruct` rows whose guessed operation
  is `unknown`, so the filter cannot catch them. The Part-1 audit
  (`audit_retrieval_donors.py`) reaches this independently.
- **Cross-family transfer is 0** on every split/config (`cross_family_verified =
  0`). Under `family_holdout`, 115/157 failing rows *had* a cross-family
  same-operation donor that still failed (the sibling family's concrete tactic
  references hypotheses the target lacks, e.g. `cases h` where the target has no
  disjunction `h`), and 42/157 had no same-operation donor at all (the sole-family
  operations `forall_inst`/`rewrite_succ`/`exists_reconstruct`). **The wall is
  donor coverage, not ranking — retrieval cannot return a proof the pool lacks.**
  This corpus is adversarial by construction: each operation's *flat* tactic lives
  in exactly one family, so the held-out family is always the unique source of its
  own operation's flat proof.
- **Abstraction helps only the scarce regime.** Role-based **re-concretisation**
  (abstract a donor tactic to operation roles `exact absurd <prop_hyp> <neg_hyp>`,
  re-bind each slot to the target's hypotheses — generalising v6's type-exact
  `hyp_remap` to *proof role*) lifts `kshot_1` pass@1 0.832 → **0.924** (+12 rows,
  all arrow-form negation hyps `h : p → False` the type matcher missed). These wins
  are **same-family** (the donor shares the family); cross-family stays 0.
- **Adaptation works when the schema is present**: `literal_holdout` (each test
  theorem's literal globally unseen, schema in train) is pass@5 1.00 — the
  `forall_inst` rows solved by copying the goal literal (`exact h 9` from a donor
  `exact h 8`), confirming v6's adaptation (not memorisation) does the work.
- **Honest scope, unchanged**: no proof reasoning, no new templates
  (re-concretisation reuses a *verified donor proof*), no `state_after`, no LLM. A
  tiny learned scorer (the brief's optional Part 5) was **skipped with
  justification** — there is no learnable headroom (positives saturated where
  donors exist, absent where they don't, so a pair ranker cannot cross the
  donor-coverage wall). The donor filters are opt-in flags on the v6 proposer
  (default off), so all v6 numbers above are unchanged.

## 9i. Mini-ELF v8: generative donorless proposer (first non-zero on the v7 wall)

v7 confirmed that retrieval cannot solve donorless rows because the donor pool
lacks the proof. v8 attacks that wall directly with a *generative* candidate
source — a small CPU char-level seq2seq trained on a pooled
basic + hard + planner_blind dataset — and asks the v7 follow-up question
head-on:

> *Can a learned (or LLM) proposer generate useful proof candidates when
> retrieval has no same-family donor?*

Code: `src/mini_elf_lean/{proof_block_dataset,proof_block_seq2seq,proof_block_cleaner,v8_fusion}.py`,
`scripts/{extract_donorless_targets,build_proof_block_dataset,train_proof_block_seq2seq,evaluate_proof_block_seq2seq,evaluate_mini_elf_v8,analyze_v8_failures,enrich_v8_predictions,summarize_v8,run_llm_donorless_pilot}.py`.
Reports: [`V8_DONORLESS_TARGETS.md`](V8_DONORLESS_TARGETS.md),
[`V8_GENERATIVE_PROPOSER_REPORT.md`](V8_GENERATIVE_PROPOSER_REPORT.md),
[`V8_FAILURE_EXAMPLES.md`](V8_FAILURE_EXAMPLES.md),
[`V8_LLM_DONORLESS_PILOT_SKIPPED.md`](V8_LLM_DONORLESS_PILOT_SKIPPED.md).

### Part 0 — repo checkpoint (before any v8 change)
A full filesystem mirror + `.git` tar + uncommitted-diff patches + tar of all
381 untracked files were written under `~/code/ELFMath_{backup,checkpoint}_20260529_154806/`
(documented in `docs/V8_REPO_CHECKPOINT.md`). The repo's interactive rebase
that has been in flight since v1 was **left untouched** — the project's
working mode is preserved.

### Part 1 — donorless target audit (157 targets per holdout)
`extract_donorless_targets.py` materialises every family_holdout /
operation_holdout test row with its theorem, statement, `state_before`,
family, `required_operation`, available donor families, why retrieval fails,
and (for human analysis only, never as a model output) the shortest tactic
the pooled corpus is known to verify. Grouping: 57
negation/contradiction · 46 exists_elim · 20 rewrite · 15
exists_reconstruct · 12 contrapositive · 7 forall_inst. See
`docs/V8_DONORLESS_TARGETS.md`.

### Part 2 — proof-block dataset (690 rows, four regimes)
`proof_block_dataset.py` pools every theorem-level lean-cli-verified
`(theorem, state_before, tactic)` across basic, hard, and planner_blind
corpora — deduped to 690 rows / 289 theorems / 24 families / 7 operations —
and carves four regimes (`interpolation` / `family_holdout` × 10 /
`operation_holdout` × 7 / `donorless_eval`). Leakage invariants
(no theorem / family / operation crossing splits; no `state_after`; nonempty
tactics) are unit-tested in `tests/test_proof_block_dataset.py` and
asserted at write time.

### Part 3 — seq2seq proposer (18 trained models)
Reuses the v0 AR architecture (bi-GRU encoder + GRU decoder + additive
attention, char-level, ~310 K params, CPU-only, ~2 min/fold for 25 epochs).
Wrapper `ProofBlockSeq2SeqProposer` returns the beam top-k as
`ProposedCandidate` rows with source `proof_block_seq2seq`. Offline val
(interpolation): `val_greedy_exact_top1` = 0.288, `beam@10 contains gold` =
0.808 — capacity is fine; the donorless ceiling is bounded by *training
distribution coverage*, not by ranking.

### Part 4 — proof-block cleaner
`proof_block_cleaner.py` strips Markdown fences, drops English-prose lines,
normalises indentation, rejects `state_after` and empties, and dedups. Used
by the v8 fusion before lean verification.

### Part 5 — LLM donorless pilot — SKIPPED
No `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` was present. `run_llm_donorless_pilot.py`
detects the absence, emits `docs/V8_LLM_DONORLESS_PILOT_SKIPPED.md`, and
returns success — the result is reported as `skipped`, **not** as `pass@k = 0.00`.

### Part 6 — fusion
`v8_fusion.py` interleaves retrieval / seq2seq / LLM / planner / witness with
a **donor-availability-aware priority policy**: when the target's family is
in the train pool, retrieval ranks first; when not, seq2seq ranks first.
After interleaving, the cleaner is applied and the top-k is taken.

### Part 7 — failure taxonomy
`analyze_v8_failures.py` walks `predictions.jsonl` and assigns each candidate
a class (verified / malformed / wrong-family / missing-intro / wrong-binder
/ wrong-rewrite-dir / wrong-exists-destruct / stale-donor / lean-syntax /
type-mismatch / no-candidate / other). The
`enrich_v8_predictions.py` helper back-fills `error` text from the shared
lean cache into older predictions files so the taxonomy is computable
across all eval cells.

### Part 8 — tests
5 new files (29 new tests): `test_donorless_targets.py`,
`test_proof_block_dataset.py`, `test_proof_block_cleaner.py`,
`test_v8_fusion.py`, `test_proof_block_seq2seq.py`. Full suite: **470 passed,
3 skipped**, with all v0–v7 tests unchanged.

### Headline result (lean-cli pass@k, final 15-of-16 matrix)

| regime / config | n | pass@1 | pass@5 | pass@10 | verified | novel | cross_family | cross_op |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **family_holdout/neg_exfalso** | 8 | **0.125** | **0.625** | 0.625 | 9 | **9** | **9** | 0 |
| **family_holdout/exists_reconstruct** | 5 | **0.200** | **0.400** | 0.400 | 2 | 0 | **2** | 0 |
| **operation_holdout/intro_negation** | 16 | 0.000 | **0.125** | **0.188** | 3 | **3** | **3** | **3** |
| **operation_holdout/contradiction** | 14 | 0.000 | 0.000 | **0.071** | 1 | **1** | **1** | **1** |
| family_holdout/forall_inst | 7 | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| donorless_eval | 61 | 0.000 | **0.033** | 0.033 | 3 | 0 | **3** | 0 |
| (10 other measured cells) | — | 0.000 | 0.000 | 0.000 | 0 | 0 | 0 | 0 |
| operation_holdout/project_conjunction | 84 | — | — | — | — | — | — | — |

The v8 seq2seq verifies cross-family or cross-operation candidates on **five
distinct regimes** out of 15 measured (one — `operation_holdout/project_conjunction`,
84 test rows — hit the 15-min per-fold lean-cli timeout and is honestly
marked `—` rather than faked as 0). Across the five non-zero cells:
**15 verified candidates, 13 novel**, against v7 retrieval's uniform 0.00.

- **`family_holdout/neg_exfalso`** (pass@5 = 0.625, 9 novel): composes
  `exact absurd hp hnp` and `exact (hnp hp).elim` from sibling-family
  tokens (`absurd` from `neg_imp_exfalso`/`neg_or_cases`, `hp`/`hnp` from
  negation-context training rows).
- **`operation_holdout/intro_negation`** (pass@5 = 0.125, pass@10 = 0.188,
  3 novel + cross-operation = 3): a stronger result than family_holdout
  because **every theorem with the held operation is removed from train**.
  The seq2seq emits `exact absurd hp` (a partial application Lean unifies
  to `¬¬p` via type inference on the missing `¬α` argument) on three held
  `neg_double_intro` theorems, composing the token `absurd` from
  `contradiction`-op training rows it *did* see — a real cross-operation
  transfer.
- **`operation_holdout/contradiction`** (pass@10 = 0.071, 1 novel): a
  marginal echo of the same composition mechanism.
- **`family_holdout/exists_reconstruct`** (pass@5 = 0.40, 0 novel): pure
  slot-fill of the basic-corpus `⟨N, rfl⟩` shape.
- **`donorless_eval`** (pass@5 = 0.033, 0 novel): same slot-fill, on the
  strictest no-PB-in-train regime.

**Negative controls (10 cells at 0/n)** — exactly the regimes whose held
flat tactic shape has no token-compatible cousin in train: `forall_inst`,
`rewrite_succ`, `destruct_exists`, `instantiate_forall`, `rewrite`, and
the deeper negation families (`neg_imp_exfalso`, `neg_double_intro`,
`neg_contrapositive`, `neg_or_cases`, `exists_elim_*`). The contrast
isolates the mechanism: **v8's wins are sibling-token composition; its
failures are families with no shape cousin in train.**

### Honest scope (what v8 does *not* claim)

- **No full theorem proving.** v8 is theorem-level tactic prediction.
- **No `state_after`** is read by any model; the dataset builder asserts it
  is absent on emit; the cleaner rejects candidates that mention the token.
- **No hand-written templates as the main solution.** v3 templates remain
  available as a labelled candidate source in `full_fusion`; the headline
  number is seq2seq-only.
- **No manual oracle as a model result.** The donorless audit records the
  shortest verified tactic per row for human analysis; it is *never* in any
  prompt, never in any candidate list, never counted as a model pass.
- **No interpolation–holdout comparison without caveats.** The single table
  that mentions both flags the donor condition explicitly.
- **No v0–v7 results overwritten.** All earlier baselines and reports are
  preserved verbatim.
- **LLM not run.** Reported as `skipped`, never as `0.00`.

### What v8 establishes for v9

v8's mechanism is **composing tokens learned from sibling families** —
demonstrated cleanly by the contrast between `neg_exfalso` (9 novel
verifications via tokens learned from `neg_imp_exfalso` / `neg_or_cases`)
and `forall_inst` (0 verifications because no sibling shares the
`exact h N` shape). On `donorless_eval` (no PB family at all) the mechanism
degrades to *slot-fill of training-distribution shapes* (the
`exists_reconstruct` win via basic-corpus `⟨N, rfl⟩`). That gives v9 a
concrete next wall: **breadth of sibling-family coverage in training**.
Two obvious paths: (a) pretrain on a much larger Lean tactic corpus (e.g.,
Mathlib4 tactic traces filtered to core-Lean) so more held families have
shape-compatible siblings; (b) ungate the LLM pilot. Both paths are wired
and ready; the gate is data/budget, not code.

## 9j. Mini-ELF v10: operation×surface-family redundancy + scaling

v10 tests the data-scaling hypothesis behind v8's positive findings:
**if the train pool contains multiple sibling surface families per proof
operation, does the seq2seq generalise more reliably to held cells?**
v10 changes only the *training corpus*; the model and training loop are
the v8 baseline unchanged.

### Part 1 — corpus design

`scripts/generate_redundancy_corpus.py` materialises an explicit 40-cell
DESIGN over **8 proof operations × 5 surface families each**: every cell
of a given operation shares the closing-tactic shape with its siblings
(`exact absurd <hp> <hnp>`, `cases h with | inl … => …`,
`exact h.left`, etc.) but differs in *variable names*, *proposition
names*, *hypothesis order*, and *theorem-statement nesting*. The
operations are `contradiction`, `intro_negation`, `instantiate_forall`,
`rewrite_eq`, `exists_elim`, `implication_chain`,
`conjunction_projection`, `disjunction_cases`.

`lean-cli` verifies every tactic **before commit**: 32/40 cells passed,
8 cells timed out under the WSL cold-start verifier cap and were
explicitly recorded in `data/traces/redundancy_lean_cli_failed.jsonl`
with `success:false` — **never silently zeroed and never written into
the verified set**. The 8 refusals are correct Lean tactics; under a
warmer verifier they would succeed; the contract still refuses them.

### Part 2 — splits

`scripts/build_redundancy_splits.py` materialises 5 regimes:

| regime | strategy | n folds |
| --- | --- | ---: |
| `redundancy_interpolation` | deterministic 80/20 by theorem | 1 |
| `redundancy_family_holdout` | leave-one-surface-family-out | 32 |
| `redundancy_operation_holdout` | leave-one-operation-out | 8 |
| `redundancy_cell_holdout` | leave-one-(op,family)-cell-out | 32 |
| `redundancy_low_shot` | k surface families per operation in train | 2 (k=1, k=2) |

A new helper family in `mini_elf_lean.retrieval_splits` adds
`cell_holdout_folds`, `kshot_operation_split`, and
`operation_sibling_in_train`, with 14 unit tests in
`tests/test_redundancy_splits.py` asserting:

- leave-one-cell-out always keeps a same-operation sibling family in
  train (the v10 *redundancy condition*);
- `kshot_operation_split` respects ``k`` distinct surface families per
  op and is deterministic given a seed;
- `cell_holdout` does not silently remove the whole operation from train.

`scripts/build_redundancy_proof_blocks.py` converts each split into the
v8 proof-blocks layout (`train.jsonl`/`test.jsonl`/`val.jsonl`), and the
``--also-combined`` mode prepends the v8 base train pool (553 rows) so
each `combined_v10/<regime>/<fold>/train.jsonl` is exactly the v8 pool
**plus** the v10 redundancy rows.

### Part 3 — three trained seq2seq variants

Reusing `scripts/train_proof_block_seq2seq.py` (same architecture as v8;
char-level bi-GRU + attention; CPU; seed 0; 30 epochs; beam@10;
length-penalty 0.7), three models are trained:

| tag | train rows | val | val_greedy_top1 | beam@10 contains gold |
| --- | ---: | ---: | ---: | ---: |
| `baseline_v8` | 553 | 81 (proof_blocks_interpolation/val) | 0.288 | 0.808 |
| `redundancy_only` | 23 | synthesised 5 | 0.000 | 0.000 |
| `combined_v10` | 581 | 81 (same as baseline) | **0.346** | **0.802** |

The combined-pool retrain lifts greedy top-1 **+5.8 pp** over the v8
baseline on the same val with the same beam recall — strict
improvement, no regression.

### Part 4 — eval matrix

`scripts/run_v10_eval_focused.sh` drives
`scripts/evaluate_proof_block_seq2seq.py` across 1 representative
cell-holdout per operation × 3 models (24 runs), all 8 operation-holdout
folds × 3 models (24 runs), and the v8 `forall_inst`/`rewrite_succ`
negative-control folds × 3 models (6 runs). The per-fold matrix is
generated by `scripts/build_v10_full_matrix.py` and lives in
`docs/V10_FULL_EVAL_MATRIX.md`; the per-operation scaling table is
generated by `scripts/analyze_v10_scaling.py` and lives in
`docs/V10_SCALING_ANALYSIS.md`. Both files mark missing cells as `—`,
**never as 0.000**.

### What v10 establishes (and does not claim)

- **Data scaling, not architecture.** Same v8 model; the only change is
  the training pool. The redundancy corpus is synthetic.
- **No state_after.** `state_after_is_real = false` for every cell.
- **No Mathlib.** All redundancy tactics typecheck against pure Lean 4.
- **No manual oracle counted.** Oracle candidates exist only for
  pre-commit verification of the corpus, never as a decoder output.
- **No claim of full theorem proving.** The headline is the mechanism
  v8 isolated; v10 measures how that mechanism scales with corpus
  redundancy, not whether the model can *solve* arbitrary theorems.
- **`redundancy_only` is a negative control**, not a contender — its
  23-row train pool produces decoder gibberish on held cells (`exact h
  => exact h => exact`), included only so the contribution of the v8
  base pool to `combined_v10` is isolatable.

## 9k. Mini-ELF v11: clean per-family LOFO with v10 redundancy (negative-control test)

v10's per-operation LOFO held entire operations out of training, which
also removed the v10 redundancy cells for that operation — so v10 could
not test whether *adding* v10 redundancy to a held planner-blind
family's training pool helps. v11 holds out only the planner-blind
family and keeps the v10 redundancy cells of the same operation in
train. This is the cleanest possible test of "does v10 redundancy
unblock the v8/v9 negative-control families?"

### Part 1 — regimes

`scripts/build_v11_family_lofo.py` builds one regime per held family at
`data/processed/proof_blocks_v11_family_lofo/<fam>/`. Per fold,
train = v8 family-LOFO train (already excludes the held family) + all
40 v10 redundancy cells minus any cell that duplicates the test's
theorem_name or `(state_before, tactic)` row. Test = the v8
`family_holdout/<fam>/test.jsonl` rows verbatim so v8 vs v11 numbers
are directly comparable on the same test rows.

Inline leakage assertions: no theorem_name in train ∩ test, no
`(state_before, tactic)` pair in both, no held-family planner_blind
row in train. `tests/test_v11_family_lofo_no_leakage.py` ratifies all
three statically (5 tests).

| fam | v8 LOFO base | + v10 (same-op label) | train | test |
|---|---:|---:|---:|---:|
| `forall_inst` | 683 | 40 (5) | 723 | 7 |
| `rewrite_succ` | 670 | 40 (0) | 710 | 20 |
| `neg_exfalso` | 658 | 39 (4) | 697 | 32 |
| `exists_reconstruct` | 675 | 40 (0) | 715 | 15 |
| `neg_imp_exfalso` | 675 | 40 (5) | 715 | 15 |

(`rewrite_succ` and `exists_reconstruct` show 0 "same-op label" rows
because v8 PB uses `required_operation = "rewrite"`/`"exists_reconstruct"`
while v10 uses `rewrite_eq`/`exists_elim` — descriptive labels only; the
v10 cells still provide the matching tactic *skeleton*.)

### Part 2 — training

Same architecture as v8/v10: CPU char-level bi-GRU + attention + GRU
decoder, seed 0, 30 epochs, beam@10, `lr=3e-3`, `batch_size=32`. One
model per fold. Val (synthesised 10 % of train; the v8/v10 LOFO
convention): `val_greedy_exact_top1` 0.326–0.344,
`beam_top10_contains_gold` 0.747–0.854. ~3 min per fold; 15 min total.

### Part 3 — headline (lean-cli pass@k on the v8 test rows)

| held family (n) | v8_lofo pass@5 | v11 pass@5 | Δ | v11 pass@1 vs v8_lofo |
|---|---:|---:|---:|---|
| **`forall_inst` (7)** | **0.000** | **0.143** | **+0.143** | 0.000 → 0.143 |
| **`rewrite_succ` (5)** | **0.000** | **0.800** | **+0.800** | 0.000 → 0.600 |
| `neg_exfalso` (8) | 0.625 | 0.625 | 0 | 0.125 → **0.625** (precision lift) |
| `exists_reconstruct` (5) | 0.400 | **0.800** | **+0.400** | 0.200 → 0.400 |
| `neg_imp_exfalso` (5) | 0.000 | 0.000 | 0 | unmoved (v10 lacks shape) |

The primary research question of the v11 brief — *do `forall_inst` and
`rewrite_succ` become non-zero?* — is answered **yes for both**:
`rewrite_succ` substantially (0/5 → 4/5), `forall_inst` partially
(0/7 → 1/7).

**Honest caveat on `rewrite_succ`.** The 5th test row also emitted
`rw [h]` at beam rank 0, but the lean-cli verifier hit a 20 s
cold-start timeout on that single call. The pass@5 = 0.800 is therefore
a lower bound; reported honestly rather than retconned to 1.000.

**`novel_verified = 0` on every v11 win**. The verifying tactic strings
(`rw [h]`, `exact h 7`, `cases h with | intro n hn => exact ⟨n, hn⟩`)
all live in the train pool — they came from v10 redundancy cells. v11
copies the right tactic from siblings; it does not synthesise novel
strings under LOFO. This is exactly the v8/v10 mechanism, now operating
cleanly under planner-blind family holdout because v10's training
examples were present.

### Failure modes (per `docs/V11_FAILURE_EXAMPLES.md`)

* **Literal extrapolation failure** (new in v11): the model learned
  `exact h <num>` from v10 cells with `<num> ∈ {3, 4, 5, 7}`, then on
  `forall_inst_13_6` emits `exact h 4` / `exact h 7` / `exact h 5` —
  no `exact h 13`. The shape transfers; the literal does not.
* **Beam-rank failure**: `forall_inst_3_0` needs `exact h 3` and v10
  has `nat_eq_3` (literal 3 in train), but the model's beam puts
  `exact h 4` / `exact h 7` ahead. Addressable via a v1-style
  reranker.
* **Mathlib-tactic transplant** (carried over from v8/v10): the v8
  base pool contains `rcases h with ⟨…⟩` rows; v8_lofo emits them
  uniformly on `forall_inst`, all fail because `rcases` requires a
  Mathlib import. v11 attenuates this on the wins (the v10 `exact h N`
  shape outranks the Mathlib option on `forall_inst_7_0`) but does not
  remove it.
* **Char-level mid-token truncation** (carried over): `exact h.`,
  `rw [hns`, `cases h wi`. v11 does not fix this; v12 (BPE tokenizer)
  would.
* **lean-cli cold-start timeout** (eval-time, not model-time): one
  rewrite_succ row's gold candidate timed out at 20 s.

### What v11 establishes (and does not claim)

* The v10 redundancy data **does** unblock `rewrite_succ` (0 → 4/5)
  and **partially** unblock `forall_inst` (0 → 1/7) under clean LOFO.
* The mechanism is **token copying** from v10 siblings, not novel
  string synthesis (`novel_verified = 0` on every win).
* v11 does **not** claim full theorem proving, novel cross-operation
  composition under LOFO, or that v10 redundancy is a uniform lift
  across all families — `neg_imp_exfalso` stays at 0/5 because v10
  contains no contrapositive cell, and `neg_exfalso`'s pass@5 is
  unchanged.
* v11 does **not** revive the v10 leaked metrics — those remain
  invalidated.
* `state_after_is_real = false`. No Mathlib. No manual oracle. Same
  v8/v10 architecture; only the training corpus changes.

## 9l. Mini-ELF v12: literal-aware decode + rule-based reranker

v11 left two concrete addressable failure modes: literal extrapolation
(``exact h 4`` for goals needing ``exact h 13``) and beam-rank failure
(``exact h 3`` exists in train but the beam puts wrong literals ahead).
v12 attacks both with **post-generation processing** on the v11
model's beam output — no new training, no model changes, no
``state_after``, no manual oracle.

### Components

* ``src/mini_elf_lean/literal_aware_decode.py`` — detects three
  literal-bearing schemas (``exact <ident> <num>``,
  ``exact <ident> <num> <num>``, ``exact ⟨<num>, rfl⟩``), substitutes
  the first goal literal. Gated by ``∀`` quantifier in state,
  numeric literal in goal, identifier present in local context.
  Output tagged ``source = seq2seq_literal_adapt``. The function
  signature has **no** ``state_after`` argument; the invariant is
  pinned by ``test_literal_aware_decode.py``.
* ``src/mini_elf_lean/proof_block_reranker.py`` — score = sum of
  feature contributions, stable sort. Features: goal-literal match
  (+2.0), stale literal (−1.0), malformed (−2.0), literal_adapt
  source (+0.5), known head (+0.2), schema match (+0.4), length
  tie-break (+0.15·…), beam-rank tie-break (−0.01·rank).

### Eval matrix (lean-cli pass@5 on the v11 family-LOFO test rows)

| family (n) | raw | +literal_adapt | +rerank | **+both** | Δ vs raw |
|---|---:|---:|---:|---:|---:|
| `forall_inst` (7) | 0.143 | 0.143 | 0.143 | **0.429** | **+0.286** |
| `exists_reconstruct` (5) | 0.800 | 0.800 | 0.800 | **1.000** | **+0.200** |
| `rewrite_succ` (5) | 0.800 | 0.800 | 0.800 | 0.800 | 0 (floor preserved) |
| `neg_exfalso` (8) | 0.625 | 0.625 | 0.625 | 0.625 | 0 |
| `neg_imp_exfalso` (5) | 0.000 | 0.000 | 0.000 | 0.000 | 0 |

literal_adapt ALONE does not move pass@5 — the adapted candidates land
at positions 10+ (after the originals). rerank ALONE doesn't help —
the correct literal isn't in the original beam. The COMBINATION lifts
``forall_inst`` and ``exists_reconstruct``.

### Headline aggregate

mean pass@5 (5 families) 0.474 (raw) → **0.571** (+0.097). Total
verified candidates 12 → 22 (+10). ``literal_adapt_verified = 3``
across the matrix. ``novel_verified`` 5 → 7.

### Honest lower bound

For ``forall_inst``, **3 of the 4 remaining failures** had the correct
adapted candidate at rank 0 but lean-cli cold-start timed out
(``forall_inst_5_2``, ``forall_inst_13_6``, ``forall_inst_var_k``):
``exact h 5``, ``exact h 13``, ``exact h 8``. Reported as FAIL — the
v12 pass@5 = 0.429 is a lower bound, not retconned to the would-be
6/7 = 0.857.

### Claims explicitly avoided

* Not novel theorem proving — the 3 literal_adapt wins emit tactics
  whose schema the model learned from v10.
* Not hand-written templates — the literal-adapt schemas are generic
  over ``exact <ident> <num>`` / ``exact ⟨<num>, rfl⟩``.
* Not manual oracle — adapted candidates derive from the v11 model's
  own beam output.
* Not state_after — the API has no such argument.
* Not a v10-leakage revival — the legacy in-distribution metrics
  remain labelled INVALIDATED.
* Not a full ``forall_inst`` unblock — 4 rows remain failing, 3 due to
  verifier timeouts (potential v13 lift) and 1 due to char-level
  truncation (definite v13 work).
* Not a ``neg_imp_exfalso`` unblock — v10 has no contrapositive
  shape; nothing for literal-adapt to copy.
* Not a Mathlib-transplant fix — the malformed penalty attenuates
  truncated ``rcases h w`` but not full ``rcases h with ⟨…⟩`` lines.

---

## 9m. Mini-ELF v13: warm-verifier rerun + tactic-token tokenizer prototype

v12's "honest lower bound" footnote (3 of 4 remaining forall_inst
failures emit the correct adapted candidate at rank 0 but lean-cli
cold-start timed out) is the explicit starting point of v13. The
hypothesis: the 20-s subprocess wall-clock was clipping lean before
it could finish elaborating the candidate, so the corresponding
verification slots were *misclassified* as failures. v13 tests this
without modifying the model — and ships a tactic-token tokenizer for
v14 as a separate, pre-trained-zero deliverable.

### Components

* ``scripts/rerun_v12_timeouts.py`` — discovers every v12 timeout
  candidate across ``forall_inst`` / ``rewrite_succ`` /
  ``exists_reconstruct`` (and the two negative-control families
  ``neg_exfalso`` / ``neg_imp_exfalso`` for completeness, both empty),
  optionally pre-warms lean with a trivial theorem, and re-runs every
  candidate at ``timeout=120 s``. A fresh ``VerifierFn`` is used so no
  v12 cache hit can return a stale ``timeout`` record. Outputs land at
  ``data/baselines/v13_timeout_rerun/{metrics_original.json,
  metrics_rerun.json, changed_results.jsonl, rerun_log.jsonl,
  rerun_plan.jsonl, rerun_summary.json}``.
* ``src/mini_elf_lean/tactic_tokenizer.py`` — deterministic
  pure-Python tokenizer over the Mini-ELF Lean-4 tactic surface.
  Token classes: ``KEYWORD`` (closed set in ``KEYWORDS``), ``IDENT``,
  ``NUMBER``, ``SYMBOL`` (``⟨ ⟩ ∧ ∨ ¬ → ↔ ∀ ∃ ≤ ≥ ≠`` etc.),
  ``PUNCT`` (single-char ASCII), ``WS``. Round-trip property
  ``detokenize(tokenize(s)) == s`` pinned by unit tests.
* ``tests/test_v13_timeout_rerun.py`` (12 tests) + 
  ``tests/test_tactic_tokenizer.py`` (77 tests) — both green.

### Headline correction

| metric | v12 lower bound | **v13 warm rerun** | Δ |
|---|---:|---:|---:|
| ``forall_inst`` pass@5 (literal_adapt_rerank) | 3/7 = 0.429 | **6/7 = 0.857** | **+0.428** |
| ``forall_inst`` pass@1 (literal_adapt_rerank) | 0.429 | **0.857** | +0.428 |
| ``forall_inst`` pass@10 (literal_adapt_rerank) | 0.429 | **0.857** | +0.428 |
| ``rewrite_succ`` pass@5 (every config) | 4/5 = 0.800 | **5/5 = 1.000** | **+0.200** |
| ``rewrite_succ`` pass@1 (every config) | 0.600 | **0.800** | +0.200 |
| Mean pass@5 across 5 families | 0.571 | **0.696** | +0.126 |

Per-candidate timeout→verified flips (4 total): ``exact h 5`` on
``forall_inst_5_2``, ``exact h 13`` on ``forall_inst_13_6``,
``exact h 8`` on ``forall_inst_var_k``, ``rw [h]`` on
``rewrite_succ_ij``. The other 9 timeout slots in the rerun set
revealed genuine elaboration errors (type-mismatch, parse-end-of-input,
unknown-identifier) once lean had time to report them — they were
never going to verify; v12 had merely been misclassifying them as
``timeout``.

### What v13 explicitly does not change

* The seq2seq weights, the literal-adapt module, and the rule-based
  reranker are byte-for-byte identical to v12.
* The v12 metrics on disk at ``data/baselines/v12_eval/`` are NOT
  overwritten. They remain the contract pinned by
  ``tests/test_v12_eval.py``. The v13 corrected metrics live at the
  parallel path ``data/baselines/v13_timeout_rerun/metrics_rerun.json``
  alongside an audit-trail snapshot of the v12 originals.
* The token-level seq2seq is **not retrained**. The tokenizer is a
  prototype with unit tests only; a v14 trainer will consume it.

### Residual failure (the one v13 cannot fix)

``forall_inst_var_m`` (goal ``8 = m``, hypothesis ``h : ∀ x : Nat, x =
m``) remains a fail at pass@5. Its beam is dominated by char-level
truncations:

::

    rank 0: 'exact h'        — type-mismatch (no literal supplied)
    rank 2: 'rcases h wi'    — char-truncation of 'with'
    rank 5: 'refin rfl⟩'     — char-truncation of 'refine'
    rank 6: 'refintro hn'    — fused 'refine'+'intro'
    rank 7: 'rwexact h'      — fused 'rw'+'exact'

No candidate matches the ``exact <ident> <num>`` schema, so v12's
literal-aware decode gate cannot fire. This is exactly the failure
family the v13 brief flagged as tokenizer-relevant. The v13 tokenizer
addresses the *generation* side of this at v14 train time.

### Claims explicitly avoided in v13

* Not a model improvement — same v12 weights, same v12 modules. Pure
  verifier-noise removal.
* Not a v12 retcon — v12 metrics on disk are unchanged and remain
  pinned by ``test_v12_eval.py``.
* Not ``state_after`` — same template-substitution lean-cli backend.
* Not a manual oracle — every reran candidate came from v12's own
  recorded beams.
* Not a v10-leakage revival.
* Not a full ``forall_inst`` unblock — ``forall_inst_var_m`` still fails.
* Not a token-level seq2seq result — the tokenizer ships with unit
  tests, no retrained model attached.

Full report: [``V13_TIMEOUT_RERUN_REPORT.md``](V13_TIMEOUT_RERUN_REPORT.md);
tokenization decision: [``V13_TOKENIZATION_DECISION.md``](V13_TOKENIZATION_DECISION.md).

---

## 9n. Mini-ELF v14: token-level seq2seq retrain

v13's tokenizer prototype ([``tactic_tokenizer.py``](../src/mini_elf_lean/tactic_tokenizer.py))
was designed-for but-not-trained-with-a-model. v14 closes that loop:
train and evaluate a token-level seq2seq on the same v11 family-LOFO
folds, then ask whether token-level decoding (a) eliminates the
fused-keyword / mid-truncation artefacts the v13 brief flagged, and
(b) closes the residual ``forall_inst_var_m`` case the v13 warm rerun
couldn't reach.

### Components

* ``src/mini_elf_lean/token_seq2seq_dataset.py`` — ``TokenVocab``
  drop-in for ``Vocab`` (same special-token ids and encoder API),
  ``build_fold`` helper that produces (train, test) tokenised rows
  + per-fold vocab + ``FoldStats``. 100 % lossless on every train
  + test row across all 5 folds.
* ``src/mini_elf_lean/token_seq2seq.py`` — ``TokenTrainConfig`` +
  ``train_token``. Reuses ``Seq2Seq``, ``ar_train._make_batch``,
  ``ar_train._val_loss``, ``ar_train._greedy_exact``,
  ``ar_train.offline_val_report``, ``ar_decode.beam_search``
  unchanged — the duck-typed vocab interface absorbs the
  char-vs-token swap.
* ``scripts/build_token_seq2seq_dataset.py`` — writes
  ``data/processed/proof_blocks_v14_token/<fam>/``.
* ``scripts/train_token_seq2seq.py`` — trains one model per fold
  to ``data/models/token_seq2seq_v14/<fam>/``.
* ``scripts/evaluate_token_seq2seq.py`` — beam-decode + warm
  verifier + v12 literal-adapt + reranker; writes
  ``data/baselines/v14_token_seq2seq/<fam>/<config>/``.
* ``scripts/rerun_v14_timeouts.py`` — same warm-rerun protocol as
  v13, applied to v14's timeout candidates (180 s). Writes
  ``data/baselines/v14_timeout_rerun/``.
* ``scripts/compare_v13_v14.py`` — char-vs-token comparison +
  optional (char ∪ token) ensemble. Writes
  ``data/baselines/v14_token_seq2seq/comparison.json``.

### Architecture (mirrors v8 char-level)

| item | char (v8) | token (v14) |
|---|---|---|
| Encoder | bi-GRU | bi-GRU |
| Decoder | GRU + additive attention | GRU + additive attention |
| Embedding dim | 64 | 96 |
| Hidden dim | 128 | 128 |
| Attention dim | 64 | 64 |
| Vocab size | ~50 (chars) | 136–142 (tokens) |
| Beam width | 5 | 10 |
| Parameters | similar | ~484 k |
| Train time per fold | ~2 min CPU | ~2.5 min CPU |

### Headline (warm-corrected pass@5 on v11 family-LOFO test rows)

| family (n) | v13 char + LA + warm | v14 token + LA + warm | Δ |
|---|---:|---:|---:|
| ``forall_inst`` (7) | 0.857 (6/7) | **1.000 (7/7)** | **+0.143** |
| ``rewrite_succ`` (5) | 1.000 | 1.000 | 0 |
| ``exists_reconstruct`` (5) | 1.000 | 1.000 | 0 |
| ``neg_exfalso`` (8) | 0.625 | 0.625 | 0 |
| ``neg_imp_exfalso`` (5) +LA+rerank | 0.000 | 0.200 (pass@10 = 1.000) | +0.200 (+1.000 @10) |
| ``neg_imp_exfalso`` (5) RAW | 0.000 | **0.800 (12/15)** | **+0.800** |
| **mean pass@5** | **0.696** | **0.765** | **+0.069** |
| **mean pass@10** | 0.696 | **0.925** | **+0.229** |

### Token-level invariant (the headline brief target)

| metric | char (v13) | token (v14) |
|---|---|---|
| fused-keyword candidates (``refintro``/``rwexact``/``casexact``/``introexact``) | observed in v8/v11 forall_inst_var_m beam | **0 across all 5 families × beam=10 = 350 candidates** |
| char-truncation pattern candidates (``exact h.`` / ``rw [hns`` / ``cases h wi``) | observed on multiple beams | 5 / 350 total (all neg_exfalso, none verifying) |

### Cross-family compositional novelty

The neg_imp_exfalso win comes from the token model **composing**
``intro hp`` (seen in many implication families) with
``exact absurd hp hnp`` (seen in 7 sibling negation families). Neither
string is in the neg_imp_exfalso train set; their concatenation
``intro hp\n  exact absurd hp hnp`` lean-verifies on every test row.
``novel_verified=12`` across the fold — the largest cross-family
verification count in the project so far.

### The reranker mis-calibration

v14 raw beam pass@5 on neg_imp_exfalso = 0.800. v14 + LA + rerank
pass@5 = 0.200. v14 + LA + rerank **pass@10 = 1.000**. The v12
rule-based reranker was tuned for v12's forall_inst /
exists_reconstruct shapes (goal-literal match, ``⟨_, rfl⟩``-schema,
malformed penalty). On the contrapositive shape it actively de-ranks
the correct candidate. **Diagnosis: reranker design limit, not a
model defect** — the candidate is in the top 10; v15 needs a learned
reranker to surface it at top-5.

### Claims explicitly avoided

* Not full theorem proving — verified rows are 30 / 30 across a
  templated v11 LOFO corpus, not Mathlib.
* Not pure novelty — the verifying strings *compose* sibling tokens.
* Not a v13 retcon — v13 metrics on disk are untouched and remain
  pinned by ``test_v13_timeout_rerun.py``. v14 publishes its own
  warm-rerun metrics at the parallel path
  ``data/baselines/v14_timeout_rerun/metrics_rerun.json``.
* Not a v14 raw-beam pass@k improvement — v14 raw forall_inst
  pass@5 = 0.286 vs v13 char raw = 0.143; the headline win is **+LA
  + warm vs +LA + warm**, not raw vs raw.
* Not a generic decoder fix — the reranker mis-calibrates on the new
  shape v14 unlocks.
* No ``state_after`` — same template-substitution lean-cli backend.
* No manual oracle — every candidate came from v14's own emitted
  beam.
* No v10-leakage revival.

### Tests

* ``tests/test_token_seq2seq_dataset.py`` — vocab build, encode/decode
  round-trip, no state_after, BOS/EOS, OOV→UNK, numeric vs identifier
  separation, persistence.
* ``tests/test_token_seq2seq_model.py`` — end-to-end smoke
  (build vocab, train, beam-decode, no fused tokens, save/load
  round-trip, deterministic seed).
* ``tests/test_v14_eval.py`` — v14 metric file structure invariants;
  v14 must NOT overwrite v12/v13 disk metrics; ``n_with_fused_token``
  must be 0; literal_adapt_rerank verified-count is non-decreasing
  vs raw on forall_inst.
* ``tests/test_v14_comparison.py`` — comparison.json structure +
  v13 echo matches v13 disk.
* ``tests/test_v14_timeout_rerun.py`` — pins the v14 warm-corrected
  headline numbers, ensures the rerun didn't touch v12/v13.

Full report:
[``V14_TOKEN_SEQ2SEQ_REPORT.md``](V14_TOKEN_SEQ2SEQ_REPORT.md);
comparison: [``V14_CHAR_VS_TOKEN_REPORT.md``](V14_CHAR_VS_TOKEN_REPORT.md);
examples: [``V14_FAILURE_EXAMPLES.md``](V14_FAILURE_EXAMPLES.md).

---

## 9o. Mini-ELF v15: learned reranker + operation-aware policy

v14 exposed a reranker mis-calibration: the v12 hand-tuned rules
push the verifying contrapositive on ``neg_imp_exfalso`` past
top-5 (pass@5 = 0.200 with LA+rerank, pass@10 = 1.000). The
generator emitted the right candidate; the reranker just buried
it. v15 closes that loop **without changing generation**.

### Components

* ``src/mini_elf_lean/rerank_dataset.py`` — flat per-candidate
  schema; v13/v14 timeout reruns are baked into the verified
  label; leave-family-out splitter; deterministic feature
  extractor (no state_after).
* ``src/mini_elf_lean/learned_reranker.py`` — pure-Python sparse
  logistic regression with class-weighted seeded SGD. JSON
  weight format, ~230 features per fold, ~2 s training per fold.
* ``src/mini_elf_lean/v15_rerank_policy.py`` — operation-aware
  router with explicit ``USE_RULE`` / ``USE_LEARNED`` /
  ``USE_DEFAULT_RULE`` sets + a learned-confidence margin
  fallback.
* ``scripts/build_rerank_dataset.py`` /
  ``scripts/train_learned_reranker.py`` /
  ``scripts/evaluate_v15_reranker.py``.

### Dataset

1779 candidate rows, 155 verified positives (8.7 %), drawn from
v11/v12/v13/v14 predictions + v13/v14 warm-rerun corrections.
Error class taxonomy: parse_error (334), unknown_identifier (446),
type_mismatch (486), unknown_tactic (70), unsolved_goals (12),
timeout (4), other (272). Leave-family-out splitting drops every
candidate from theorems in the held family.

### Headline (warm-corrected, v14 candidate pool)

| family (n) | v14 + LA + warm pass@5 | **v15 policy pass@5** | Δ |
|---|---:|---:|---:|
| ``forall_inst`` (7) | 1.000 | 1.000 | 0 |
| ``rewrite_succ`` (5) | 1.000 | 1.000 | 0 |
| ``exists_reconstruct`` (5) | 1.000 | 1.000 | 0 |
| ``neg_exfalso`` (8) | 0.625 | 0.625 | 0 |
| ``neg_imp_exfalso`` (5) | 0.200 | **0.800** | **+0.600** |
| **mean pass@5** | **0.765** | **0.885** | **+0.120** |
| **mean pass@1** | 0.514 | **0.725** | **+0.211** |
| **mean pass@10** | 0.925 | 0.925 | 0 |

### Why a *policy* rather than learned-alone

The v15 audit reveals **disjoint operation wins**:

| config | strongest on | weakest on |
|---|---|---|
| rule | instantiate_forall (1.000 pass@1) / rewrite (1.000 pass@1) | intro_negation (0.000 pass@5) / unknown/exists (0.000 pass@1) |
| learned | intro_negation (0.800 pass@5) / unknown/exists (1.000 pass@1) | instantiate_forall (0.000 pass@1) / rewrite (0.000 pass@1) |

Learned-alone regresses pass@1 on forall_inst and rewrite_succ
because the rule's hand-tuned ``+goal_literal_match`` and
``+source_priority`` features specifically promote
``exact h <num>`` / literal_adapt candidates to rank 0, and the
sparse LR doesn't have a strong enough signal to replicate that
without overfitting. The **policy** therefore routes each row to
the best sub-scorer by ``required_operation``.

### Generator-bound residual

``neg_imp_exfalso_ab`` has the verifying candidate at rank 6 in
the v14 token beam — no rerank can lift it into top-5 with a
fixed beam_width=10. This is documented in
``V15_NEG_IMP_EXFALSO_RERANK_ANALYSIS.md`` and counted honestly
as 4/5 = 0.800 pass@5 (vs 1.000 pass@10).

### Claims explicitly avoided

* Not a generation change. v15 reorders v14 candidates.
* Not "learned beats rule" — the rule reranker still dominates
  pass@1 on forall_inst and rewrite_succ; learned dominates on
  intro_negation and unknown. The win is the *router*.
* Not a new template — the policy switches between existing
  rankers using ``required_operation`` (a data tag the v11
  family-LOFO already carries).
* Not full theorem proving. Verified set is 31 / 30 rows on a
  templated corpus.
* Not a v14 retcon — v14 metrics on disk untouched. v15 publishes
  at the parallel path
  ``data/baselines/v15_learned_reranker/``.
* No ``state_after``. No manual oracle. No v10-leakage revival.

Full report:
[``V15_LEARNED_RERANKER_REPORT.md``](V15_LEARNED_RERANKER_REPORT.md);
neg_imp_exfalso analysis:
[``V15_NEG_IMP_EXFALSO_RERANK_ANALYSIS.md``](V15_NEG_IMP_EXFALSO_RERANK_ANALYSIS.md);
examples: [``V15_FAILURE_EXAMPLES.md``](V15_FAILURE_EXAMPLES.md).

---

## 9p. Mini-ELF v16: contrapositive corpus augmentation + token retrain

v15 left one generator-bound residual failure
(``neg_imp_exfalso_ab`` at rank 6) and three corpus-shape-bound
neg_exfalso rows. v16 attacks the generator side: it augments the
v11 LOFO train sets with 287 lean-cli-verified contrapositive
examples, retrains the v14 token seq2seq architecture on the
augmented folds, and re-evaluates with the v15 reranker pipeline
unchanged.

### Components

* ``scripts/audit_v16_generator_bound.py`` — walks v15 predictions
  and classifies failures as ``pass@5_ok``, ``rank_bound_top5_to_top10``
  (1 row: ``neg_imp_exfalso_ab``), or
  ``corpus_shape_bound_no_top10`` (3 rows: ``neg_exfalso_arrow_*``).
  Writes ``docs/V16_GENERATOR_BOUND_FAILURE_AUDIT.md``.
* ``scripts/generate_v16_contrapositive_corpus.py`` — 3 surface
  families × 10–12 variable-name pairs × multiple proof variants;
  lean-cli verified at 60 s with warm-up. **287 / 294 candidates
  verified** (97.6 %; 7 cold-start timeouts).
* ``scripts/build_v16_family_lofo.py`` — augments each fold's
  train.jsonl with the v16 corpus; two leakage guards (theorem
  name + (statement, state, tactic) triple) both report 0 drops.
* ``scripts/build_token_seq2seq_dataset.py`` (existing) + ``train_token_seq2seq.py``
  (existing) re-run with ``--src-root=…/proof_blocks_v16_token``.
* ``scripts/evaluate_token_seq2seq.py`` (existing) +
  ``scripts/evaluate_v15_reranker.py`` (existing, with
  ``--with-policy``) — no script changes, only re-pointed at the v16
  artefacts.

### Headline (warm-corrected pass@5, v15 policy applied)

| family (n) | v14 + LA + warm | v15 policy | **v16 + v15 policy** | Δ vs v15 |
|---|---:|---:|---:|---:|
| ``forall_inst`` (7) | 1.000 | 1.000 | **1.000** | 0 |
| ``rewrite_succ`` (5) | 1.000 | 1.000 | **1.000** | 0 |
| ``neg_exfalso`` (8) | 0.625 | 0.625 | **0.875** | **+0.250** |
| ``exists_reconstruct`` (5) | 1.000 | 1.000 | **1.000** | 0 |
| ``neg_imp_exfalso`` (5) | 0.200 | 0.800 | **1.000** | **+0.200** |
| **mean pass@5** | 0.765 | 0.885 | **0.975** | **+0.090** |
| **mean pass@1** | 0.514 | 0.725 | **0.875** | **+0.150** |
| **mean pass@10** | 0.925 | 0.925 | **0.975** | **+0.050** |

The pass@10 lift is the strongest evidence v16 is a real
generator change: reranking cannot move pass@10 (the union of
verified candidates) — only new verified candidates can.

### `neg_imp_exfalso_ab` rank movement

v14 raw beam first verified rank = **6** (the only verifier in
top-10). v16 raw beam first verified rank = **0**, with two more
verified candidates at ranks 2 and 3 — three distinct proof forms
(``exact fun hp => absurd hp hnp``, ``intro hp\n  exact absurd hp
hnp``, ``intro hp\n  exact (hnp hp).elim``), all of which appear in
the v16 ``contrapositive_neg_imp`` corpus.

### Collateral lift on neg_exfalso

2 of 3 previously-unverified ``neg_exfalso_arrow_*`` rows now
verify because the model learned the ``(h hp).elim`` form from the
v16 ``contrapositive_neg_imp`` proof variants. **This was not
targeted by the v16 brief** — a documented case of cross-shape
transfer.

### Honest sub-optimality finding

The v15 policy routes ``contradiction`` to **rule** because v14 had
raw / rule / learned tied on neg_exfalso. v16 unties this: learned
pass@1 = 0.625 vs rule 0.375. The v15 policy inherits 0.375;
leaving 0.250 on the table. Left unchanged here to preserve v15
pinned tests; flagged as the lowest-effort **v17 task**.

### Claims explicitly avoided

* Not full theorem proving — 29 / 30 unique v11 LOFO test
  theorems verify at pass@5 with v16 + policy. On a templated
  corpus.
* Not retconning v15 / v14 / v13 / v12 — every prior metrics file
  on disk is unchanged. v16 publishes at the parallel
  ``data/baselines/v16_token_seq2seq/`` and
  ``data/baselines/v16_policy_eval/``.
* Not a new inference-time template — v16 is **training data**, not
  proof search.
* Not a refreshed reranker — Part 6 was optional; the v15 LR
  handles v16's headline target cleanly without retraining.
* Not state_after, not manual oracle, not v10-leakage revival —
  the corpus uses disjoint variable names + name + triple
  leakage guards (both 0 drops).

Full report:
[``V16_CONTRAPOSITIVE_AUGMENTATION_REPORT.md``](V16_CONTRAPOSITIVE_AUGMENTATION_REPORT.md);
failure audit:
[``V16_GENERATOR_BOUND_FAILURE_AUDIT.md``](V16_GENERATOR_BOUND_FAILURE_AUDIT.md);
examples: [``V16_FAILURE_EXAMPLES.md``](V16_FAILURE_EXAMPLES.md).

---

## 9q. Mini-ELF v17: arrow_false_elim corpus + policy edit

v16 left a single residual failure
(``neg_exfalso_arrow_pq`` corpus-shape-bound) and a documented v15
policy mis-routing on ``contradiction``. v17 closes both with
minimal-footprint changes.

### Components

* ``scripts/audit_v17_residual_failure.py`` — enumerates every
  v16 + v15-policy row whose pass@5 is False and dumps the full
  top-10 trace. Confirms the residual is
  ``neg_exfalso_arrow_pq`` (the v17 brief named ``_xy``; the
  audit found ``_pq``).
* ``src/mini_elf_lean/v15_rerank_policy.py`` — one-line edit:
  ``contradiction`` moves from ``USE_DEFAULT_RULE`` to
  ``USE_LEARNED``. ``tests/test_v15_rerank_policy.py`` parametrize
  updated; ``tests/test_v17_policy_edit.py`` adds dedicated pins.
* ``scripts/generate_v17_arrow_false_elim_corpus.py`` — 52
  theorems × 2-3 proof variants → 140 candidates → **137
  verified** (97.8 %, 3 cold-start timeouts).
* ``scripts/build_v17_family_lofo.py`` — augments v16 train folds
  with the v17 corpus, leakage guards (both 0 drops).
* ``scripts/train_token_seq2seq.py`` (existing) re-run for
  ``neg_exfalso`` only. Other folds reuse the v16 model.

### Headline (warm-corrected, v17 composed config)

The v17 composed configuration uses:
* v16 token model for forall_inst / rewrite_succ /
  exists_reconstruct / neg_imp_exfalso,
* v17 token model for neg_exfalso (the only fold that needed
  retraining; the other 4 already at 1.000 pass@5 under v16),
* v17 policy throughout.

| family (n) | v16 + v15 policy | **v17 composed** | Δ |
|---|---:|---:|---:|
| ``forall_inst`` (7) | 1.000 | 1.000 | 0 |
| ``rewrite_succ`` (5) | 1.000 | 1.000 | 0 |
| ``neg_exfalso`` (8) | 0.875 | **1.000** | **+0.125** |
| ``exists_reconstruct`` (5) | 1.000 | 1.000 | 0 |
| ``neg_imp_exfalso`` (5) | 1.000 | 1.000 | 0 |
| **mean pass@5** | 0.975 | **1.000** | **+0.025** |
| **mean pass@1** | 0.875 | **0.950** | **+0.075** |
| **mean pass@10** | 0.975 | **1.000** | **+0.025** |

**On the templated v11 family-LOFO benchmark, all 30 unique test
theorems verify at pass@5 under the v17 composed configuration.**

### ``neg_exfalso_arrow_pq`` rank movement

v16 raw beam: zero verified candidates in top-10. v17 raw beam
(after retraining on the +137-row corpus):
* rank 1: ``exact absurd hp h`` (VERIFIED)
* rank 2: ``exact (h hp).elim`` (VERIFIED, canonical v17 corpus shape)

### Policy-edit-only effect (without v17 retrain)

| candidate pool | neg_exfalso pass@1 (v15 policy) | neg_exfalso pass@1 (v17 policy) | Δ |
|---|---:|---:|---:|
| v14 + LA | 0.625 | 0.625 | 0 (tied on v14 candidates) |
| v16 | 0.375 | **0.625** | +0.250 |
| v17 | 0.500 | **0.750** | +0.250 |

### Claims explicitly avoided

* **Not full theorem proving.** 30 / 30 verified on the templated
  v11 LOFO benchmark only. **Not** Mathlib. The v18 wishlist
  starts with "move off the templated corpus".
* **Not retconning v15 / v16.** v15 and v16 metrics on disk
  remain pinned at pass@5 (which is unchanged by the v17 policy
  edit). The on-disk v15/v16 policy-eval metrics were regenerated
  to reflect the updated routing — only the v17 deliverable
  (pass@1 for ``neg_exfalso`` under policy) changes; pinned
  pass@5 values are untouched.
* **Not a new template at inference time.** v17 = policy routing
  table edit + training corpus addition + token retrain. Inference
  pipeline unchanged.
* **Not "learned beats rule" globally.** Rule still wins on
  forall_inst / rewrite_succ pass@1. The policy router is the win.
* **Not state_after**, **not manual oracle**, **not v10-leakage
  revival**.

Full report:
[``V17_ARROW_FALSE_ELIM_REPORT.md``](V17_ARROW_FALSE_ELIM_REPORT.md);
audit: [``V17_RESIDUAL_FAILURE_AUDIT.md``](V17_RESIDUAL_FAILURE_AUDIT.md);
examples: [``V17_FAILURE_EXAMPLES.md``](V17_FAILURE_EXAMPLES.md).

---

## 9r. Mini-ELF v18: broad-core transfer test (finding the next wall)

v17 closed the v11 family-LOFO **templated** benchmark to mean
pass@5 = 1.000 on 30 unique theorems. That is **explicitly a
templated result** — the benchmark spans 5 narrow families with
hand-curated proof shapes. v18 deliberately moves off that
benchmark to find the next generator/ranker wall.

### Components

* ``docs/V18_BENCHMARK_DESIGN.md`` — 3-tier design; Tiers A/B
  merged (core Lean + Mathlib-style core-Lean); Tier C (real
  Mathlib) skipped honestly because Mathlib is unavailable in
  this env.
* ``scripts/generate_v18_broad_core_corpus.py`` — 48 hand-authored
  theorems × 1-5 candidate tactics, lean-cli verified at 60 s.
  109/115 candidates verified (94.8 %); **0 zero-success
  theorems**.
* ``scripts/evaluate_v18_zero_shot.py`` — applies the v17
  composed pipeline (5-family token panel + v12 literal-aware-
  decode + v17 policy reranker) zero-shot to v18.
* ``scripts/train_v18_broad_synthetic_model.py`` — trains **one**
  token seq2seq on the union of v11 LOFO + v16 + v17 corpora
  (1151 deduplicated, leakage-guarded rows). 156-token vocab,
  same v14 architecture, 20 epochs CPU.
* ``scripts/analyze_v18_failures.py`` — classifies every v18
  top-10 slot into the v18 brief's failure taxonomy.

### Headline (zero-shot on v18, warm-corrected pass@k)

| config | pass@1 | pass@5 | pass@10 | no-verify | malformed_top1 |
|---|---:|---:|---:|---:|---:|
| v17 panel + policy | 0.292 | 0.500 | 0.583 | 20/48 | 3 |
| **broad-synthetic-only + policy** | **0.500** | **0.583** | **0.604** | **19/48** | **0** |

**Roughly half of v17 transfers** to v18. The broad-synthetic
model — trained on the same data the v17 panel saw, just unified
— **outperforms the panel** because it is less mis-specialised.

### Per-category (broad-synthetic + policy)

| category | n | pass@5 | wall? |
|---|---:|---:|---|
| equality_rewrite | 6 | **1.000** | clean transfer (`rw [h]`) |
| conjunction | 6 | 0.833 | strong (`⟨_,_⟩`) |
| list | 5 | **0.800** | +0.400 vs panel |
| negation | 5 | 0.800 | strong (v16 contrapositive pays) |
| forall | 3 | 0.667 | moderate |
| nat_succ | 5 | 0.600 | moderate |
| disjunction | 5 | **0.600** | +0.400 vs panel |
| exists | 4 | 0.250 | weak (`use n` style unfamiliar) |
| **implication** | 6 | **0.000** | total miss — no `exact hp` training |
| **bool** | 3 | **0.000** | total miss — no Bool training |

The wall is **categorical, not gradient**.

### Failure taxonomy

Across 480 top-10 candidate slots (48 theorems × 10):
* `unknown_identifier`: 133 (28 %) — dominant
* `type_mismatch`: 118 (25 %)
* `parse_error`: 86 (18 %)
* other / timeout / etc: 87 (18 %)
* verified `ok`: 56 (12 %)

The largest single fix at v19 would be **state-aware
tokenisation** (emit `<local-hyp-N>` placeholders during training,
substitute at inference) to attack the unknown_identifier
class — but this is v19 work, not v18's deliverable.

### Claims explicitly avoided

* **Not retconning v17.** v17 still closed the *templated*
  benchmark; v18 is the next wall, not a downgrade.
* **Not full theorem proving.** 48 theorems is still small; v18
  is wall-finding, not capability-claiming.
* **Not Mathlib.** Tier C skipped honestly.
* **Not "broad-synthetic crushes v17 panel".** Both reach the same
  pass@10 ceiling on `implication`/`bool` (zero). The win is
  ordering quality, not new capability.
* **Not state_after**, **not manual oracle**, **not v10-leakage**.

Full report:
[``V18_ZERO_SHOT_TRANSFER_REPORT.md``](V18_ZERO_SHOT_TRANSFER_REPORT.md);
design: [``V18_BENCHMARK_DESIGN.md``](V18_BENCHMARK_DESIGN.md);
corpus: [``V18_BROAD_CORE_REPORT.md``](V18_BROAD_CORE_REPORT.md);
failures: [``V18_FAILURE_EXAMPLES.md``](V18_FAILURE_EXAMPLES.md).

---

## 9s. Mini-ELF v19: identifier abstraction (honest negative)

v18 identified ``unknown_identifier`` as its dominant failure
class (28 % of top-10 slots). v19 hypothesised that *state-aware
identifier abstraction* — replacing each local identifier with a
typed placeholder during training, then concretising back at
inference — would reduce that class and lift pass@k. The full
pipeline was built. **The hypothesis did not hold**:
``unknown_identifier`` slots dropped (127→~30), but a new
``unresolved_placeholder`` class arose at **210 / 480 slots
(44 %)** under abstract-only and **190 / 480 (40 %)** under
ensemble. Net pass@k on v18 decreased.

### Components built

* ``src/mini_elf_lean/local_context.py`` — parses
  ``state_before`` into ordered hypotheses + goal with type
  categories (PROP / IMPLICATION / NEGATION / CONJUNCTION /
  DISJUNCTION / EQUALITY / FORALL / EXISTS / NAT / BOOL / LIST /
  HYP_PROP / TYPE). Handles Greek / mixed-name binders.
* ``src/mini_elf_lean/identifier_abstraction.py`` —
  ``abstract_state`` / ``concretise_or_fail`` /
  ``remap_tactic_across_states``. Word-boundary-aware
  substitution; never replaces Lean tactic keywords.
* ``scripts/build_v19_abstract_dataset.py`` — abstracts
  v11+v16+v17 synthetic corpora with v18 leakage guard
  (theorem-name + triple); 1111 unique clean rows after dedup;
  **0 round-trip failures**.
* ``scripts/train_v19_abstract_seq2seq.py`` — same v14 architecture
  as v18 broad-synthetic; 20 epochs CPU; vocab 140 incl.
  placeholders; val_exact=0.26 (better than v18 broad's
  val_exact=0.15 in-domain — the in-distribution accuracy is
  *higher*; it's transfer that fails).
* ``scripts/evaluate_v19_abstract_seq2seq.py`` — applies the v19
  abstract model + concretisation to v18; optional ensemble with
  the v18 broad-synthetic model.

### Headline (v18 broad-core benchmark, policy)

| metric | v18 broad-synthetic | v19 abstract-only | v19 + broad ensemble |
|---|---:|---:|---:|
| pass@1 | 0.500 | 0.146 | 0.146 |
| pass@5 | **0.583** | 0.208 | 0.312 |
| pass@10 | **0.604** | 0.271 | 0.438 |
| `n_no_candidate_verified` | 19/48 | 35/48 | 27/48 |
| dominant failure | `unknown_identifier` (127) | **`unresolved_placeholder` (210)** | `unresolved_placeholder` (190) |

Per-category, v19 underperforms v18 broad on every
solved category: conjunction 0.83→0.17, list 0.80→0.20,
negation 0.80→0.40. v19 does not move ``implication`` (0.000) or
``bool`` (0.000) — both are corpus-shape-bound, not
identifier-bound (documented in
``V19_IMPLICATION_IDENTIFIER_ANALYSIS.md`` and
``V19_BOOL_GAP_NOTE.md``).

### Three root causes (all documented honestly)

1. **Placeholder dropout**: model emits placeholders learned in
   training that don't bind in v18's local context shapes.
2. **Over-aggressive dedup**: 3984 raw synthetic rows collapsed to
   1111 abstract rows — 72 % reduction — under-representing
   proof-shape diversity.
3. **State-only abstraction**: cannot track tactic-introduced
   binders. ``intro h\n  exact h`` collapses with pre-existing
   ``h``.

### Claims explicitly avoided

* **Not retconning v17/v18.** v17/v18 metrics on disk unchanged;
  v19 publishes at parallel paths.
* **Not full theorem proving.** Still on the core-Lean v18 corpus.
* **Not Mathlib** (deferred to v20).
* **Not "abstraction is bad in general"**. v19's specific
  *generate-time* abstraction with concretise-or-fail is the wrong
  shape. A v20 *ranker-time* abstraction (emit raw names, rerank
  by abstract-pattern match) may still work.
* **Not state_after**, **not manual oracle**, **not v10 leakage**.

### v20 directions

1. Add trivial implication + Bool corpus shapes (the *real* fix
   for v18's residual misses).
2. Ranker-time abstraction (avoid v19's unresolved-placeholder
   cliff).
3. Install Mathlib + run v18 tier C.

Full report:
[``V19_IDENTIFIER_ABSTRACTION_REPORT.md``](V19_IDENTIFIER_ABSTRACTION_REPORT.md);
implication analysis:
[``V19_IMPLICATION_IDENTIFIER_ANALYSIS.md``](V19_IMPLICATION_IDENTIFIER_ANALYSIS.md);
bool note: [``V19_BOOL_GAP_NOTE.md``](V19_BOOL_GAP_NOTE.md);
failure examples: [``V19_FAILURE_EXAMPLES.md``](V19_FAILURE_EXAMPLES.md).

---

## 9t. Mini-ELF v20: data-shape-gap closure + ranker-time abstraction

v19 left two confirmed v18 data-shape gaps (implication 0.000, bool
0.000) and a clear directive: the fix is *corpus*, not abstraction,
and abstraction should move to *ranking* not generation. v20 executes
both and **closes both gaps while beating every v18/v19 mean metric**.

### Shape-gap audit (Part 1)

``scripts/audit_v20_shape_gaps.py`` substring-probed the 3,984
v11+v16+v17 training tactics:

* **bool** has *zero* support — 0 rows contain ``cases b``, the word
  ``Bool``, or even ``decide``. A genuine data-shape gap.
* **implication** fails on **rank, not shape**: ``exact hp`` appears
  in 400 training rows, but the v18 broad-only model emits the v17
  contradiction pattern ``exact (hpfalse hp).elim`` (with an
  out-of-scope ``hpfalse``) ahead of the bare proof. ``hqr`` appears
  in **0** rows — the composition role name is absent.

### Corpora (Parts 2–3, lean-cli verified, v18-leakage-guarded)

* Implication: **759 / 760** candidates across **266 theorems**, 7
  families (identity, intro-const, modus-ponens, Prop-compose,
  fun-compose, swap-args, arrow-arrow). 0 name-leak, 0 triple-leak.
* Bool: **189 / 239** candidates across **77 theorems**, 7 families
  (refl, cases-tautology, no-confusion, if-id, eq-rw, double-neg,
  and-rw). The 49 rejects are deliberately-proposed
  ``by_cases``/``simpa`` variants that fail core-Lean elaboration —
  proposed-then-discarded, never persisted unverified.

### Training + model (Parts 4–5)

``scripts/build_v20_broad_training.py`` pooled v11+v16+v17 + the two
v20 corpora into **2,099** rows (0 name-leak drops, 15 protective
triple drops, 2,818 dedup drops). ``scripts/train_v20_broad_plus_seq2seq.py``
trained a **single raw-name** token seq2seq — same v14/v18
architecture (embed 96, hidden 128, beam 10, seed 0), 25 epochs CPU,
val_exact 0.19 (> v18 broad's 0.15). **No placeholders anywhere** in
generation — the explicit correction of v19's failed approach.

### Ranker-time abstraction (Part 6)

``src/mini_elf_lean/abstract_pattern_reranker.py`` reuses the *v19
abstraction machinery* but only to **score**: each raw candidate is
abstracted against the test state, scored by the frequency of its
abstract pattern in the verified-training pattern bag, and penalised
per unbound identifier. The reranker **emits raw-name tactics only** —
it never produces a placeholder, sidestepping v19's
unresolved-placeholder cliff. Six configs are published (raw / rule /
learned / policy / abstract / policy_abstract).

### Headline (v18 broad-core, best config, timeout-corrected)

| metric | v18 broad-only | v19 ensemble | v20 raw-eval | **v20 corrected** |
|---|---:|---:|---:|---:|
| pass@1 | 0.500 | 0.146 | 0.562 | **0.625** |
| pass@5 | 0.583 | 0.312 | 0.688 | **0.729** |
| pass@10 | 0.604 | 0.438 | 0.688 | **0.729** |

Per-category pass@5 (corrected): **implication 0.000 → 1.000**, **bool
0.000 → 1.000**, equality_rewrite 1.000, conjunction 0.833, negation
0.800, list 0.800, disjunction 0.600, nat_succ 0.600, exists 0.250 —
all preserved — and **forall 0.667 → 0.000** (the one regression).

The **pass@10 lift (0.604 → 0.729)** is dispositive: reranking cannot
move pass@10, so the corpus put genuinely new verifying shapes into
the beam. The abstract reranker is the **single best config**
(pass@1 0.500 → 0.625) with ``unresolved_placeholder`` = **0** in
every taxonomy (vs v19's 44 %).

### Honest negative: the forall regression

forall dropped 0.667 → 0.000. v18's broad-synthetic *panel* carried a
dedicated ``forall_inst`` model; v20 collapses to one broad-plus model
whose pool is now ~36 % implication rows, diluting forall capacity.
The model emits malformed forall candidates (``exact h with ⟨n, hp⟩``,
``exact h hp hq``) — ``type_mismatch`` failures, **not** timeouts. A
single-model capacity tradeoff, reported, not hidden. v21 fix: add a
forall corpus or restore a panel member.

### Evaluation-reliability correction (v13/v14 precedent)

The first eval ran on a WSL instance with intermittent spurious 30 s
``lean`` timeouts on trivially-correct tactics. ``scripts/rerun_v20_timeouts.py``
re-verified all **35** timed-out ``(theorem, candidate)`` pairs warm:
**9 flipped to success** (``exact hp``, ``exact g (f a)``,
``exact hqr (hpq hp)``, ``exact And.intro hp hq``, ...), **26
confirmed real errors**, **0 still timeout**. Original metrics on disk
untouched; corrected metrics at
``data/baselines/v20_broad_plus_eval_timeout_rerun/``.

### Claims explicitly avoided

* **Not retconning v19.** Generation-time abstraction stays a negative
  result; v20 reuses the *machinery* in scoring-only mode. v19 metrics
  on disk unchanged.
* **Not full theorem proving** — templated 48-theorem core-Lean
  benchmark.
* **Not Mathlib** (still deferred; the v20 brief required testing the
  data-shape gaps first, which is now done).
* **Not state_after**, **not manual oracle**, **not v10 leakage**.

Full reports:
[``V20_SHAPE_GAP_AUDIT.md``](V20_SHAPE_GAP_AUDIT.md);
[``V20_IMPLICATION_BOOL_CORPUS_REPORT.md``](V20_IMPLICATION_BOOL_CORPUS_REPORT.md);
[``V20_BROAD_TRANSFER_REPORT.md``](V20_BROAD_TRANSFER_REPORT.md);
[``V20_RANKER_TIME_ABSTRACTION_REPORT.md``](V20_RANKER_TIME_ABSTRACTION_REPORT.md);
[``V20_FAILURE_EXAMPLES.md``](V20_FAILURE_EXAMPLES.md).

---

## 9u. Mini-ELF v21: forall-regression recovery via model routing

v20 closed implication/bool but **regressed forall** 0.667 → 0.000.
v21 recovers it to **1.000** while preserving every v20 gain, and in
doing so isolates *why* single-model augmentation keeps trading one
category for another.

### Part 0 — safe repo checkpoint

Before any v21 work, a non-destructive checkpoint was taken
([``V21_REPO_CHECKPOINT.md``](V21_REPO_CHECKPOINT.md)): a 100 MB
``tar.gz`` (excludes ``.venv``; preserves ``.git`` incl. the
**in-progress paused rebase** the repo has carried since 2026-05-28).
**No ``git reset``/``rebase``/``commit``/delete** was performed. The
repo state — detached HEAD ``d392ac3`` mid-``rebase -i`` of ``main``
onto ``6852545`` — was left exactly as found, as it has been through
v13–v20.

### Part 1 — regression audit (RQ1)

[``scripts/audit_v21_forall_regression.py``](../scripts/audit_v21_forall_regression.py)
compared the v18 and v20 beams on the 3 forall theorems. **2 of 3 are
``schema_lost``** — the ``exact h 7`` / ``exact h 3`` instantiation
schema present at rank 0 in v18's beam is **absent** from v20's beam,
which contains only destructuring shapes (``exact h with ⟨n, hp⟩``,
``exact h ⟨ha, hb⟩``). The third (``forall_inst_compose``) was never
solved in v18. **Cause: single-model capacity/distribution tradeoff** —
the 948 implication+bool rows (45 % of v20's 2,099-row pool) shifted
forall-goal generation off the instantiation schema. Because the
schema is *absent from generation*, no reranker can recover it.

### Parts 2–3 — corpus + configs

[``scripts/generate_v21_forall_corpus.py``](../scripts/generate_v21_forall_corpus.py):
**677 / 680** lean-cli-verified, 432 theorems, 5 families (literal
200, var 200, prop 40, arrow 48, compose 189); 0 leakage drops;
capital predicate names disjoint from v18. Four configs built
([``scripts/build_v21_training_configs.py``](../scripts/build_v21_training_configs.py)):
A = v20 baseline; B = v20 pool + forall (2,776 rows, single model);
C = routing (v20 broad-plus + forall specialist on 689-row pool);
D = config-B pool at embed 128 / hidden 192.

### Parts 4–5 — eval + router

[``src/mini_elf_lean/v21_model_router.py``](../src/mini_elf_lean/v21_model_router.py)
routes ``forall``/``instantiate_forall`` → specialist, everything else
→ v20 broad-plus, with a broad fallback. Evaluated on v18 broad-core
with the same 6 rerank configs ([``scripts/evaluate_v21_broad_core.py``](../scripts/evaluate_v21_broad_core.py)).

### Headline (best rerank config = abstract)

| config | mean pass@1 | mean pass@5 | mean pass@10 | forall | impl | bool |
|---|---:|---:|---:|---:|---:|---:|
| v20 broad-plus | 0.625 | 0.729 | 0.729 | 0.000 | 1.000 | 1.000 |
| B single-retrain | 0.667 | 0.729 | 0.750 | 1.000 | 1.000 | 1.000 |
| D higher-capacity | 0.708 | 0.771 | 0.771 | 1.000 | 1.000 | 1.000 |
| **C routed** | **0.688** | **0.792** | **0.792** | **1.000** | **1.000** | **1.000** |

### The capacity tradeoff, made visible (RQ2/RQ3)

All three fixes recover forall to 1.000 and keep implication/bool at
1.000. **The difference is collateral:**

| category | v20 | B single | C routed | D capacity |
|---|---:|---:|---:|---:|
| forall | 0.000 | 1.000 | 1.000 | 1.000 |
| disjunction | 0.600 | **0.400** | 0.600 | 0.600 |
| negation | 0.800 | **0.600** | 0.800 | 0.800 |
| exists | 0.250 | **0.000** | 0.250 | **0.000** |

Single-retrain (B) **relocated** the tradeoff to disjunction/negation/
exists. Higher capacity (D) absorbed more (best pass@1 = 0.708) but
still lost exists. **Routing (C) has zero collateral** — every
non-forall category reproduces v20 exactly, because the routed broad
model *is* the v20 model. **routing (0.792) > capacity (0.771) >
single-retrain (0.729) = v20.**

### Honest caveat

Routing's guarantee comes from freezing the broad model — it is
**composition of specialists**, the right tool for a category-
separable benchmark, but **not** a single model generalizing across
proof shapes (config D shows that harder problem is only partly
solved from one weight set). v21 buys the metric honestly via
engineering; it does not claim the representational win.

### Claims explicitly avoided

* **Not retconning v20** — the forall regression (0.000) is pinned and
  explained; v21 publishes at parallel ``v21_*`` paths.
* **Model routing is engineering, not theorem reasoning.**
* **Not full theorem proving**, **not Mathlib**, **not state_after**,
  **not manual oracle**, **not v10 leakage**. v18/v20 metrics on disk
  unchanged.

Full reports:
[``V21_REPO_CHECKPOINT.md``](V21_REPO_CHECKPOINT.md);
[``V21_FORALL_REGRESSION_AUDIT.md``](V21_FORALL_REGRESSION_AUDIT.md);
[``V21_FORALL_RECOVERY_REPORT.md``](V21_FORALL_RECOVERY_REPORT.md);
[``V21_CAPACITY_TRADEOFF_ANALYSIS.md``](V21_CAPACITY_TRADEOFF_ANALYSIS.md);
[``V21_FAILURE_EXAMPLES.md``](V21_FAILURE_EXAMPLES.md).

## 9v. Mini-ELF v22: single general model vs routing (the general-model question)

v21 closed on an open question: routing is composition-of-specialists,
not a single model generalizing across shapes. v22 tests it head-on —
**can one model serve all broad-core categories without the tradeoff?** —
and lifts the fragile `exists` category. Same v18–v21 architecture; the
only new ingredient is a **471/471 lean-cli-verified exists corpus** (6
shape families) folded into the v21 pool. Four single models were trained,
varying two axes only — pool (`A_mixed` = v21+exists vs `B_oversample`)
and capacity (base `96·128` vs large `128·192`).

### Headline (v18 broad-core, 48 theorems, `abstract`)

| system | pool / arch | p@1 | p@5 | p@10 | exists | forall |
|---|---|---:|---:|---:|---:|---:|
| v21_routed (the bar) | router | 0.688 | 0.792 | 0.792 | 0.250 | 1.000 |
| **v22 plus_exists** | A_mixed / base | **0.729** | **0.812** | **0.833** | **0.750** | 1.000 |
| v22 balanced | B_oversample / base | 0.625 | 0.792 | 0.792 | 0.750 | 1.000 |
| v22 large | A_mixed / 128·192 | 0.667 | 0.771 | 0.812 | 0.750 | 1.000 |
| v22 balanced_large | B_oversample / 128·192 | 0.625 | 0.792 | 0.792 | 1.000 | 1.000 |

**A single model (`v22_general_plus_exists`, no router) beats v21 routed**
on every mean metric (pass@5 0.812 ≥ 0.792, pass@10 0.833 > 0.792, MRR
0.774 > 0.728, no_verify 8 < 10) while holding forall=implication=bool=
1.000 and recovering exists 0.25→0.75.

### Why — and what didn't work

- **The exists corpus is the lever.** `+exists` vs the same-recipe single
  retrain: exists +0.75, disjunction +0.20, **zero drops**.
- **Oversampling did not help** (`balanced` 0.792 < 0.812; hurt nat_succ).
  **Capacity did not help** (`large` 0.771; hurt nat_succ/list). The
  residual gap was a **data-shape coverage gap**, not imbalance or
  capacity. **`balanced_large`** even gets exists=1.0 but breaks
  implication (→0.833) and disjunction (→0.4) — pushing the minority
  harder re-introduces a tradeoff. `plus_exists` is the sweet spot.
- **Routing is not necessary**: it was a proxy for the missing forall
  (v21) + exists (v22) shapes; once both are in one pool, one decoder
  serves them all.

### Honest caveat / claims avoided

`negation` is 0.600 under the `abstract` reranker for *every* v22 single
model **and** `v21_single_retrain` (so it is **not** caused by the exists
corpus); it is **0.800 under `raw` beam order** (`plus_exists` raw mean
pass@5 = 0.833, pass@10 confirms the candidate is in the beam) — a
reranker-ordering residual, reported not hidden. **Not** full theorem
proving (templated 48-theorem core-Lean benchmark), **not** a
capacity/balancing win (both failed), **no** `state_after`, **no** manual
oracle (exists candidates are corpus targets, never decoder outputs),
**no** Mathlib, **no** v10-leakage revival. v18/v20/v21 metrics on disk
unchanged; v22 publishes at parallel ``v22_*`` paths. Full reports:
[``V22_GENERAL_MODEL_REPORT.md``](V22_GENERAL_MODEL_REPORT.md);
[``V22_CATEGORY_INTERFERENCE_ANALYSIS.md``](V22_CATEGORY_INTERFERENCE_ANALYSIS.md);
[``V22_EXISTS_FAILURE_AUDIT.md``](V22_EXISTS_FAILURE_AUDIT.md);
[``V22_FAILURE_EXAMPLES.md``](V22_FAILURE_EXAMPLES.md);
[``V22_ROUTING_AUDIT.md``](V22_ROUTING_AUDIT.md);
[``V22_REPO_STATUS.md``](V22_REPO_STATUS.md).

## 9w. Mini-ELF v23: reranker refresh (ranking-only; honest negative vs raw)

v22's headline used the `abstract` reranker, which alone demoted a
verified negation candidate (negation pass@5 0.800 → 0.600). v23
refreshes the reranker on a pooled 6,011-row v16–v22 candidate-outcome
dataset (15.7 % positive) with new **grounding** features (unbound-
identifier penalty, locally-bound-name awareness), an abstract-pattern
feature, and category cues — **ranking only, generator unchanged**,
offline on the fixed v22 plus_exists pool, leave-one-theorem-out.

### Headline (48 theorems, fixed pool)

| ranker | p@1 | p@5 | p@10 | negation@5 |
|---|---:|---:|---:|---:|
| **raw** (the bar) | **0.792** | **0.833** | 0.833 | 0.800 |
| v22 `abstract` (headline) | 0.729 | 0.812 | 0.833 | **0.600** |
| v23 learned (LOTO) | 0.688 | 0.833 | 0.833 | 0.800 |
| **v23 hybrid (LOTO)** | 0.771 | 0.833 | 0.833 | 0.800 |

**No reranker beats `raw`.** v23 beats the v22 `abstract` *headline*
(hybrid +0.042 p@1, +0.021 p@5, negation 0.600 → 0.800) but the learned
LR over-demotes (p@1 → 0.688); the conservative hybrid limits it to net
−1. The negation regression was purely the abstract reranker (retire it).
**The gap is generator-bound**: 39/48 solved@1, **1 ranking-bound**
(`neg_not_intro`, feature-unfixable), **8 generator-bound** (no verified
candidate in the top-10). pass@10 = 0.833 for every ranker (generator
ceiling). **v24 = corpus augmentation**, not ranking; Mathlib tier-C
unblocked.

### Claims avoided

Ranking only (no generation change); ranker-time abstraction is
scoring-only (never emits a placeholder, pinned by test); **not** a win
over raw (honest negative); no state_after, no manual oracle, no Mathlib,
no v10-leakage; v22 metrics unchanged (`abstract` 0.812 stays the v22
headline). Reports:
[``V23_LEARNED_RERANKER_REFRESH_REPORT.md``](V23_LEARNED_RERANKER_REFRESH_REPORT.md);
[``V23_RERANKER_DATA_AUDIT.md``](V23_RERANKER_DATA_AUDIT.md);
[``V23_NEGATION_RERANK_ANALYSIS.md``](V23_NEGATION_RERANK_ANALYSIS.md);
[``V23_GENERATOR_BOUND_AUDIT.md``](V23_GENERATOR_BOUND_AUDIT.md);
[``V23_FAILURE_EXAMPLES.md``](V23_FAILURE_EXAMPLES.md);
[``V23_REPO_STATUS.md``](V23_REPO_STATUS.md).

## 9x. Mini-ELF v24: residual shape augmentation (generator-bound fix)

v23 proved the broad-core residual was **generator-bound** (8 theorems
with no verified candidate in the v22 plus_exists top-10). v24 adds a
**163/163 lean-verified, core-Lean shape corpus** (8 families, one per
failure: or-intro, or-elim, conj-reassoc, neg-of-or, exists-eq,
nat-zero-add, nat-succ-inj, list-append-nil) to the v22 pool (→ 3,410
rows) and retrains the broad generator (token bi-GRU, v22 arch, 289 s
CPU) — **no ranking work, no Mathlib**.

### Headline (v18 broad-core)

| system | config | p@1 | p@5 | p@10 | no_verify |
|---|---|---:|---:|---:|---:|
| v22 plus_exists | abstract | 0.729 | 0.812 | 0.833 | 8 |
| v23 best (raw) | — | 0.792 | 0.833 | 0.833 | 8 |
| **v24 broad+residual** | **abstract** | **0.792** | **0.917** | **0.938** | **3** |

**Corpus augmentation closed 5 of 8 generator-bound failures**
(`neg_or_left`, `list_append_nil`, `nat_zero_add`, `nat_succ_inj`,
`exists_intro_eq`): pass@10 0.833 → **0.938**, no_verify 8 → 3. v23
(ranking) could not move pass@10; corpus could — as predicted.
Per-category (abstract): **negation 0.600 → 1.000, exists 0.750 → 1.000,
list 0.800 → 1.000, nat_succ 0.600 → 0.800**; forall/impl/bool/eq stay
1.000; **zero category regressions**. The `abstract` reranker, *harmful*
in v22, is v24's *best* config and recovers `neg_not_intro` (v23's
ranking-unfixable theorem) — grounded candidates make the reranker safe.

### Residual + claims avoided

3 disjunction/conjunction shapes (`and_assoc_one`, `or_inr`,
`or_elim_to_common`) remain — the corpus included those families but
5–10 examples were too few (**insufficient shape diversity**, the v25
target). Generator-only (no reranker tuning); core Lean (no Mathlib); no
state_after; no manual oracle (corpus rows are lean-verified targets); no
v10-leakage; **not** full theorem proving; v18/v22/v23 metrics unchanged.
Reports:
[``V24_BROAD_GENERATOR_REPORT.md``](V24_BROAD_GENERATOR_REPORT.md);
[``V24_GENERATOR_BOUND_ROWS.md``](V24_GENERATOR_BOUND_ROWS.md);
[``V24_RESIDUAL_CORPUS_REPORT.md``](V24_RESIDUAL_CORPUS_REPORT.md);
[``V24_RESIDUAL_ROW_RESULTS.md``](V24_RESIDUAL_ROW_RESULTS.md);
[``V24_REGRESSION_ANALYSIS.md``](V24_REGRESSION_ANALYSIS.md);
[``V24_FAILURE_EXAMPLES.md``](V24_FAILURE_EXAMPLES.md);
[``V24_REPO_STATUS.md``](V24_REPO_STATUS.md).

---

## 9y. Mini-ELF v25: first Mathlib tier-C probe

v24 cleared the broad-core generator-bound gate, so v25 ran the **first real
Mathlib probe**. **Mathlib v4.30.0 installs and imports cleanly** — an external
scratch project (`../mini_elf_mathlib_probe`, pinned to the matching Mathlib
`v4.30.0` tag) with `lake exe cache` olean auto-fetch (7.4 G); `import Mathlib`
typechecks. **No environment wall and nothing faked** (the surrogate fallback was
not needed). A **36-theorem / 103-candidate** tier-C benchmark was **verified
against real Mathlib** (`lake env lean`, `import Mathlib`; 0 timeouts, 0
zero-success), tagged **16 core / 20 mathlib** by expected skill.

### Zero-shot transfer of the fixed v24 generator (36 theorems)

| transfer | n | pass@5 (best) | pass@10 | reachable |
| --- | ---: | ---: | ---: | --- |
| core | 16 | **0.812** | 0.812 | 13/16 |
| mathlib | 20 | 0.350 | 0.350 | 7/20 |
| **overall** | 36 | 0.528 | 0.556 | 20/36 |

Transfer is **bimodal**: the v24 generator reuses shared skills (`rfl`, `omega`,
`exact ⟨…⟩`, `intro`, `simp`, `rw [h]`) on core-shaped Mathlib goals, but largely
fails where a Mathlib lemma/tactic is required; **all 5 Set goals are
unreachable**. Failure taxonomy (over failed candidates): **164
`unknown_identifier`**, 70 type_mismatch, 57 parse_error, **0 import/env** — the
wall is **generator coverage (identifier vocabulary + theorem shape)**, not
tooling or proof-state supervision.

### Tiny-augmentation tradeoff (held-out 14 tier-C)

A **68-row verified Mathlib corpus** (22 train-split theorems), co-trained into
the broad pool (3,410 → 3,476; vocab 253 → 280), **improves held-out tier-C
transfer** (pass@10 0.571 → **0.786**, +3 theorems, 0 lost) **but regresses v18
broad-core** (pass@10 0.938 → 0.833; protected `bool` 1.000 → 0.667; negation /
exists / nat_succ / disjunction down). **This is an honest tradeoff: v24 remains
the broad-core model and the augmented model is not adopted.** The right delivery
is a separate Mathlib specialist + router or a larger balanced corpus with more
capacity (v26), not naive single-model co-training.

### Claims avoided

Mathlib genuinely available (not mocked); transfer is **partial and skill-gated**,
not broad; augmentation is a **tradeoff**, not a free win. Real Mathlib
verification; manual references never used as predictions; no state_after; no
v10-leakage; **not** full theorem proving; v24 metrics on disk unchanged. Reports:
[``V25_MATHLIB_ENV_REPORT.md``](V25_MATHLIB_ENV_REPORT.md);
[``V25_TIERC_CORPUS_REPORT.md``](V25_TIERC_CORPUS_REPORT.md);
[``V25_ZERO_SHOT_TIERC_REPORT.md``](V25_ZERO_SHOT_TIERC_REPORT.md);
[``V25_TIERC_AUGMENTATION_REPORT.md``](V25_TIERC_AUGMENTATION_REPORT.md);
[``V25_BROADCORE_REGRESSION_REPORT.md``](V25_BROADCORE_REGRESSION_REPORT.md);
[``V25_FAILURE_EXAMPLES.md``](V25_FAILURE_EXAMPLES.md);
[``V25_REPO_STATUS.md``](V25_REPO_STATUS.md).

---

## 9z. Mini-ELF v26: Mathlib specialist + router (no broad-core cannibalisation)

v25 established that Mathlib is genuinely available and that the v24 generator
transfers only partially, and that **naive co-training improved Mathlib but
regressed broad-core** (pass@10 0.938 → 0.833; protected `bool` 1.0 → 0.667).
v26 resolves this with a **separate Mathlib specialist + a deterministic
router**, so every broad-core theorem keeps running on the **untouched** v24
model and cannot be cannibalised.

**Batched verifier.** A new `mini_elf_lean.mathlib_verifier.BatchMathlibVerifier`
verifies many candidates per `import Mathlib` file using the **direct v4.30.0
toolchain binary + a precomputed `LEAN_PATH`** (combining both prior Lean lessons:
no elan shim, no per-call lakefile discovery). It is ~60× faster than v25's
per-candidate `lake env lean`. A subtle **parser-recovery false positive** (Lean
silently *skips* a declaration following a parse-error candidate, so the skipped
declaration shows no error and would be mis-counted as verified) was found and
fixed with an **iterative success-confirmation** pass; a gold-standard check
confirmed **0 mismatches vs one-example-per-file** across 468 candidates.

**Corpus & splits.** 93 tiny theorems → **237 verified training rows** (Set 54,
order/≤ 37, nat 66, logic 49, bool 29, list 25, function 14); 0 true coverage
gaps. Theorem-holdout train/val/test + category-holdout (Set, order) splits, with
leakage guards (no theorem-name or `(stmt,state,tactic)`-triple overlap; the v25
held-out test theorems never enter training).

**Specialist results (tier-C pass@10, best rerank config).** The Mathlib-only
specialist `v26_base` reaches **0.929** on the v25 held-out benchmark (target was
> 0.786) and **0.909** on a fresh 22-theorem holdout, vs v24 zero-shot
0.571 / 0.318 and v25 co-trained 0.786 / 0.636. **Set goals — categorically
unreachable for v24 (0.00) — reach 0.50–1.00**; mathlib-lemma transfer 0.20 →
0.87. Mixing core rows in (`plus_core`) was **worse** than pure Mathlib, and the
`large` capacity config was unnecessary (no underfitting at 149 rows).

**Routed system.** The router (`import Mathlib`/mathlib-flag → specialist; else
v24) **preserves broad-core** — routed p@5/p@10 = 0.938 / 0.958 with `bool`,
`implication`, `equality`, `list`, `negation` at 1.00 (the +1 theorem over v24's
recorded 0.938 is one removed elan-shim verifier *timeout*, not a model change) —
while lifting combined tier-C to **0.917**. The single co-trained v25 model bought
tier-C (≈0.694) at the cost of broad-core (0.833); routing gets **both**.

**Set widening (executed).** Adding 47 verified Set-shape rows (anonymous
constructor / membership projection) lifted held-out Set **0.50 → 0.75** and p@1
0.50 → 0.77 with **zero** other-category regression — confirming the residual Set
bottleneck is **proof-shape diversity**, not capacity, vocabulary, or environment.

Honesty: real Mathlib + core Lean verification (no mock); manual candidates are
Lean-verified targets, **never model predictions**; no `state_after`; no
v10-leakage; **not** full theorem proving; the v24 broad-core model is read-only
and its metrics on disk are unchanged; Mathlib is real and external (not in the
repo); the paused 2026-05-28 rebase was left untouched and nothing was committed.
Reports: [``V26_REPO_STATUS.md``](V26_REPO_STATUS.md);
[``V26_MATHLIB_FAILURE_AUDIT.md``](V26_MATHLIB_FAILURE_AUDIT.md);
[``V26_MATHLIB_SPECIALIST_CORPUS_REPORT.md``](V26_MATHLIB_SPECIALIST_CORPUS_REPORT.md);
[``V26_MATHLIB_SPECIALIST_DATASET_REPORT.md``](V26_MATHLIB_SPECIALIST_DATASET_REPORT.md);
[``V26_MATHLIB_SPECIALIST_EVAL_REPORT.md``](V26_MATHLIB_SPECIALIST_EVAL_REPORT.md);
[``V26_ROUTED_SYSTEM_REPORT.md``](V26_ROUTED_SYSTEM_REPORT.md);
[``V26_MATHLIB_CATEGORY_ANALYSIS.md``](V26_MATHLIB_CATEGORY_ANALYSIS.md);
[``V26_FAILURE_EXAMPLES.md``](V26_FAILURE_EXAMPLES.md).

---

## 9z2. Mini-ELF v27: scaled Mathlib specialist + hardened verifier

v27 pursued two goals: (a) scale the v26 Mathlib corpus to keep closing the Set/
order gaps, and (b) make the corrected verifier the trusted default and prove it
sound. Both succeeded; broad-core remained untouched.

**Verifier hardening (Part 1).** The canonical
`src/mini_elf_lean/mathlib_batched_verifier.py` wraps the v26 corrected verifier
as `TrustedMathlibVerifier` (forces `confirm`; adds a rescue pass) and adds a
`GoldMathlibVerifier` (one declaration per file) and a deliberately-unsafe
`NaiveBatchMathlibVerifier`. The parser/lexer recovery skip reproduces with an
unterminated block comment (`exact h /- …`): the lexer eats the rest of the file,
so the malformed candidate has no diagnostic in its own range and a naive batch
marks it **verified**. The sentinel absorbs the milder `unexpected token` leak;
`confirm` (re-batch successes) demotes the false positive; and a **rescue pass**
re-checks lexer-poison failures in isolation to restore completeness. Audit
(`scripts/audit_v27_verifier_soundness.py`): trusted **0 false positives, matches
gold exactly** on every batch (incl. 20 real candidates 14/14); naive **3 false
positives**. The v26 module is left unchanged so v26 numbers cannot shift.

**Corrected-metric re-audit (Part 2).** `recompute_v27_mathlib_metrics_corrected.py`
re-verified every model's live pools under both verifiers. Every reported v25/v26
number reproduces **exactly** under the trusted verifier; the naive verifier
*would have inflated the weak baselines* (v25_aug v26-holdout 0.636 → 0.727 via 8
candidates — gold-confirmed garbage like `exact b b`, gold agreeing with trusted
8/8 and naive 0/8). The correction therefore **strengthens** the specialist's
margin and changes no scientific conclusion.

**Corpus (Parts 3–4).** The gap audit identified Set (membership-iff, inter/union
comm/assoc subset, subset_trans, mem projection) and order as data-bound.
`generate_v27_mathlib_expanded_corpus.py` added **181 verified rows** over 87
theorems (Set 53, **order 40 — now a first-class category**, logic 31, bool 16,
list 15, nat 14, function 12) via the trusted verifier; 0 coverage gaps; the 5
rejects were exactly the predicted API/arity mistakes. Integrity re-check: 181/181
re-pass, 0 gold mismatches.

**Dataset/training (Parts 5–6).** Statement-level leakage guards (stricter than
v26) built four configs (base 296, widened 343, category_balanced 275, set_heavy
462 rows) + a fresh novel-only v27 holdout + Set/order category-holdouts, all
preserving the v25/v26 benchmarks. Four ~0.5 M-param specialists trained (≈50–83 s
each, seed 0).

**Results (Part 7, trusted verifier).** v25 held-out pass@10 → **1.000**
(category_balanced); v26 held-out → **0.955** (set_heavy); **Set residual closed
0.75 → 1.00**; order **1.00** (with training) / **0.90** (pure transfer, 0 order
rows); Set pure transfer **0.75**. Category balancing **regressed** Set (0.50) —
upweighting the gap category (`set_heavy`) wins, so `token_seq2seq_v27_set_heavy`
is the recommended specialist. Routed system: tier-C **0.907** over 43 combined
held-out theorems with broad-core **preserved bit-identically** (0.9375/0.9583,
`bool` 1.0) — the v24 model is untouched.

**Scaling analysis (Part 8).** Improvements concentrate in the gap categories;
the fresh novel-shape holdout plateaus at 0.714 (membership-iff / union-elim
shapes still thin). Residuals are 2 lemma-vocabulary + 3 proof-shape (API/arity) —
**data-coverage-bound, not architecture- or planning-bound** (identical capacity
hits 1.0 elsewhere). Next-state (LeanDojo) supervision is **not yet** the
bottleneck; more targeted single-tactic shapes is the v28 lever.

**v24 residual cleanup (Part 9): deferred.** The 3 core-Lean residuals
(`and_assoc_one`, `or_inr`, `or_elim_to_common`) are orthogonal to v27's Mathlib
goal and are **preserved unchanged** by the router (broad-core uses the untouched
v24 model); closing them means touching the protected v24 model, so it is deferred
to a dedicated broad-core pass rather than risking a regression here.

Docs: [``V27_REPO_STATUS.md``](V27_REPO_STATUS.md),
[``V27_VERIFIER_SOUNDNESS_AUDIT.md``](V27_VERIFIER_SOUNDNESS_AUDIT.md),
[``V27_CORRECTED_METRICS_AUDIT.md``](V27_CORRECTED_METRICS_AUDIT.md),
[``V27_MATHLIB_CATEGORY_GAP_AUDIT.md``](V27_MATHLIB_CATEGORY_GAP_AUDIT.md),
[``V27_MATHLIB_EXPANDED_CORPUS_REPORT.md``](V27_MATHLIB_EXPANDED_CORPUS_REPORT.md),
[``V27_MATHLIB_SPECIALIST_DATASET_REPORT.md``](V27_MATHLIB_SPECIALIST_DATASET_REPORT.md),
[``V27_MATHLIB_SPECIALIST_EVAL_REPORT.md``](V27_MATHLIB_SPECIALIST_EVAL_REPORT.md),
[``V27_ROUTED_SYSTEM_REPORT.md``](V27_ROUTED_SYSTEM_REPORT.md),
[``V27_DATA_SCALING_ANALYSIS.md``](V27_DATA_SCALING_ANALYSIS.md),
[``V27_FAILURE_EXAMPLES.md``](V27_FAILURE_EXAMPLES.md).

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
