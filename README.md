# mini-elf-lean: verifier-filtered Lean tactic trace collector

A small, modular **data factory** for Lean 4 tactic traces. It turns candidate
tactics (from a mock, a hand-written/agent JSONL file, or a real LLM) into a
clean, Lean-verified dataset of `(state_before, tactic, state_after)` records.

## Backend status

| Lean backend | status |
| --- | --- |
| `mock` | **working** (no Lean needed; pipeline tests only — not real verification) |
| `lean-cli` | **working on Windows** and Unix; real whole-file Lean verification |
| `leandojo` | **implemented** behind the interface + mock-tested; **a live run needs a Unix-like OS** (Linux/macOS/WSL2) — LeanDojo can't run on native Windows |

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

> **Status here:** the leandojo backend is validated with a **mocked** LeanDojo
> module in the test suite, **not** against real LeanDojo. A real run was **not
> possible in this environment because it is native Windows** — LeanDojo drives
> the Lean REPL through `pexpect`/`ptyprocess`, which need a Unix pseudo-terminal
> (the `pty`/`termios`/`fcntl` stdlib modules are absent on Windows). Use Linux,
> macOS, or WSL 2. Full turnkey procedure (tiny traceable repo + seed + commands
> + acceptance checklist): **[`docs/LEANDOJO_SETUP.md`](docs/LEANDOJO_SETUP.md)**.

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
- The **LeanDojo** backend is fully implemented behind the `LeanRunner`
  interface and returns real `state_before → tactic → state_after` transitions,
  **but it has only been exercised against a mocked LeanDojo module**. A real
  run was **not possible in this environment because it is native Windows**:
  LeanDojo needs a Unix pseudo-terminal (`pexpect`/`ptyprocess`), and `pty` /
  `termios` / `fcntl` do not exist on Windows. So **no real LeanDojo smoke run
  has been done here**; do it on Linux/macOS/WSL per
  [`docs/LEANDOJO_SETUP.md`](docs/LEANDOJO_SETUP.md). The result-mapping is
  duck-typed to tolerate version differences, but the exact LeanDojo attribute
  names should be confirmed on first real use.
- The `mock` backend is **not** real verification; treat mock datasets as
  plumbing tests only.
- LLM / manual candidates may be biased (e.g. toward automation tactics) — the
  evaluator's automation ratio is there to keep you honest.
- **No Mini-ELF model exists.** No diffusion/flow training. No model results.

## 12. Next steps

1. **Validate the LeanDojo backend against a real traced repo** (install
   `lean-dojo`, confirm the actual `TacticState` / `ProofFinished` / error
   attribute names, run a real smoke test).
2. Real LLM proposals at scale (anthropic/openai) with prompt-style comparison.
3. Extract human Mathlib / LeanDojo traces as a candidate source.
4. Build a next-tactic dataset (split by `theorem_name`).
5. An autoregressive next-tactic baseline with verifier-aware metrics (Lean
   parse rate, Lean execution rate).
6. *Only then* the Mini-ELF embedded-flow model.

## Project layout

```
ELPMath/
  data/{seeds,manual,traces}/      seeds, manual candidates, verified output
  examples/*.lean                  reference Lean source for the seeds
  scripts/                         collect_traces, evaluate_traces, generate_manual_candidates
  src/mini_elf_lean/               schemas, config, io_utils, prompt_templates,
                                   tactic_sanitizer, llm_client, lean_runner,
                                   collector, evaluate_traces
  tests/                           pytest suite (mock backends only)
  .claude/skills/                  lean-trace-collector, lean-dojo-integration,
                                   tactic-data-quality, mini-elf-modeling (deferred)
  .claude/agents/                  tactic-proposer, trace-auditor
```
