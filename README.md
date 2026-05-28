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
      reranker** + **witness-copy** — test `pass@1` 0.89, `pass@5` 0.95, with
      verifiable *novel* generation and the first model to crack `and_elim`
- [ ] Real next-state supervision (needs LeanDojo `run_tac` unblock)
- [ ] `or_self_elim` (multi-step case split) + true open-vocab beyond witnesses
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
