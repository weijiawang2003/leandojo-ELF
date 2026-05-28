# Real LeanDojo smoke test — setup & status

This document explains how to run the **real** LeanDojo backend (`leandojo`)
that produces true `state_before → tactic → state_after` transitions, and
records exactly what blocked a live run in this repo's current environment.

`LeanDojoRunner` is already implemented (see `src/mini_elf_lean/lean_runner.py`)
and validated against a **mocked** LeanDojo module in
`tests/test_leandojo_runner.py`. What remains is exercising it against a real
LeanDojo install — which requires a supported OS.

---

## 0. Status in THIS environment (honest)

A real LeanDojo run was **not possible here**, and was not faked.

| check | result |
| ----- | ------ |
| OS | **native Windows 11** (not WSL) |
| Python | 3.12.7 |
| Lean / Lake | 4.30.0 / 5.0.0 (present) |
| `lean_dojo` installed | **no** |
| `GITHUB_ACCESS_TOKEN` set | **yes** (value not printed) |
| `pip install --dry-run lean-dojo` | resolves `lean-dojo 4.20.0` (+ `pexpect`, `ptyprocess`, `ray`, ...) |

**Blocker: LeanDojo does not run on native Windows.** It drives the Lean REPL
through `pexpect` / `ptyprocess`, which need a Unix pseudo-terminal. The
underlying Unix-only stdlib modules are simply absent on this Python:

```text
pty        MISSING -> ModuleNotFoundError: No module named 'termios'
termios    MISSING
fcntl      MISSING
tty        MISSING -> (needs termios)
resource   MISSING
```

So even though `pip` *would* install the (pure-Python) wheels, opening a
`Dojo(theorem)` session would fail at runtime. Installing the heavy ~hundreds-of-MB
dependency stack (`ray`, `grpcio`, `lxml`, `py-spy`, `cryptography`, ...) that
cannot run here would only pollute the environment, so it was intentionally not
installed.

**To run the real smoke test, use Linux, macOS, or Windows WSL 2.** The rest of
this doc is the turnkey procedure; all artifacts are already in the repo.

---

## 1. Prerequisites (Linux / macOS / WSL 2)

```bash
# 1. Lean toolchain via elan
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh
# 2. A GitHub token (LeanDojo uses it to fetch/trace repos). Do NOT commit it.
export GITHUB_ACCESS_TOKEN=ghp_xxx
# 3. LeanDojo into this project's venv
python -m pip install lean-dojo        # optional convenience extra: pip install -e .[leandojo]
```

Notes / compatibility risks:

- **Platform:** Linux/macOS/WSL only. Native Windows is unsupported (see §0).
- **Lean version:** the repo you trace pins a toolchain via its `lean-toolchain`
  file (`examples/leandojo_mini_repo` uses `leanprover/lean4:v4.30.0`). LeanDojo
  must support that version; if tracing complains, switch the repo's
  `lean-toolchain` to a version your LeanDojo supports and re-commit.
- **LeanDojo version:** the dry-run here resolved `4.20.0`. `LeanDojoRunner`
  maps results by duck-typing (`.pp` ⇒ ongoing `TacticState`; class named
  `ProofFinished` ⇒ done; else ⇒ error), so minor version differences should be
  tolerated — but confirm the real attribute names on first run (see §5). If
  they differ, patch the small `_map_result` / `_pp` / `_goal_count` helpers.
- **First trace is slow:** tracing compiles the repo with instrumentation.
  Keep the repo tiny (we do).

---

## 1a. WSL2 quick start (recommended for Windows users)

The project lives on Windows, but LeanDojo needs a Unix-like OS. WSL2 (Ubuntu)
is the easiest route. **Work inside the Linux filesystem (`~/...`), not under
`/mnt/c/...` or OneDrive** — running LeanDojo over the `/mnt/c` bridge is slow
and the OneDrive sync layer corrupts the trace cache.

```bash
# --- in Windows PowerShell (one time) ---
wsl --install -d Ubuntu        # then reboot if prompted; open the "Ubuntu" app

# --- everything below runs INSIDE the Ubuntu (WSL2) shell ---

# 0. base tooling
sudo apt-get update && sudo apt-get install -y git curl build-essential python3-venv

# 1. copy the project into the LINUX filesystem (NOT /mnt/c, NOT OneDrive)
mkdir -p ~/code && cp -r "/mnt/c/Users/<YOU>/OneDrive/Desktop/CSProject/ELFMath" ~/code/ELFMath
cd ~/code/ELFMath
# (or: git clone <your-remote> ~/code/ELFMath)

# 2. Python venv + project (mock/lean-cli deps only)
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]

# 3. Lean toolchain via elan (provides lean + lake)
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh -s -- -y
source "$HOME/.elan/env"
lean --version && lake --version

# 4. sanity: the suite passes WITHOUT LeanDojo (the real smoke test auto-skips)
pytest -q

# 5. LeanDojo + GitHub token (token stays in the shell; never commit it)
pip install lean-dojo
export GITHUB_ACCESS_TOKEN=ghp_xxx

# 6. publish the tiny repo and capture its commit (see §2), fill §3's seed, then:
export MINI_ELF_LEANDOJO_SMOKE=1
pytest tests/test_leandojo_smoke_real.py -q

# 7. (optional) full collector run on the leandojo backend
python scripts/collect_traces.py \
    --seeds data/seeds/leandojo_seeds.jsonl \
    --out data/traces/leandojo_verified.jsonl \
    --failed-out data/traces/leandojo_failed.jsonl \
    --llm-backend manual-file \
    --manual-candidates data/manual/leandojo_candidates.jsonl \
    --lean-backend leandojo --max-seeds 1
```

Step 6 verifies one real success transition (`exact h`) and one real failure
transition; steps 2–4 work even before LeanDojo is installed.

---

## 2. The tiny repo to trace

`examples/leandojo_mini_repo/` is the smallest useful target: a no-Mathlib Lean
package with three **named** theorems (LeanDojo cannot target an anonymous
`example`). It already builds locally:

```bash
cd examples/leandojo_mini_repo && lake build      # verified OK (works even on Windows)
```

| full_name      | statement                          | file_path        |
| -------------- | ---------------------------------- | ---------------- |
| `id_of_p`      | `(p : Prop) (h : p) : p`           | `MiniDojo.lean`  |
| `and_comm_toy` | `(p q : Prop) (h : p ∧ q) : q ∧ p` | `MiniDojo.lean`  |
| `nat_refl`     | `(n : Nat) : n = n`                | `MiniDojo.lean`  |

LeanDojo traces a **git repo at a specific commit**, so publish this directory
as its own repository:

```bash
cp -r examples/leandojo_mini_repo /tmp/leandojo_mini_repo
cd /tmp/leandojo_mini_repo
git init && git add -A && git commit -m "mini dojo repo"
git branch -M main
git remote add origin https://github.com/<YOU>/leandojo_mini_repo
git push -u origin main
git rev-parse HEAD            # <-- this is the COMMIT_SHA for the seed
```

(LeanDojo can also trace a local repo depending on version; the GitHub path is
the best-documented. Use whichever your installed LeanDojo supports.)

---

## 3. Fill in the seed

Edit `data/seeds/leandojo_seeds.jsonl` and replace the placeholders for at least
`id_of_p`:

```json
{"theorem_name": "id_of_p", "theorem_statement": "(p : Prop) (h : p) : p",
 "full_name": "id_of_p",
 "repo_url": "https://github.com/<YOU>/leandojo_mini_repo",
 "commit": "<COMMIT_SHA>",
 "file_path": "MiniDojo.lean"}
```

`LeanDojoRunner.start()` requires `repo_url`, `commit`, and `file_path`; it uses
`full_name` (falling back to `theorem_name`) for `Theorem(repo, file_path,
full_name)`. `initial_state` in the seed is advisory — the real one comes from
LeanDojo.

---

## 4. Run the real smoke test

### Option A — the gated pytest (recommended)

```bash
export MINI_ELF_LEANDOJO_SMOKE=1            # opt-in
pytest tests/test_leandojo_smoke_real.py -rs -v
```

It auto-skips unless `lean_dojo` is importable, the opt-in env is set, and the
seed has real (non-placeholder) coordinates. When it runs it asserts a real
**success** transition (`exact h` closes `id_of_p`) and a real **failure**
transition (a bogus tactic).

### Option B — the collector CLI (writes verified + failed JSONL)

```bash
python scripts/collect_traces.py \
    --seeds data/seeds/leandojo_seeds.jsonl \
    --out data/traces/leandojo_verified.jsonl \
    --failed-out data/traces/leandojo_failed.jsonl \
    --llm-backend manual-file \
    --manual-candidates data/manual/leandojo_candidates.jsonl \
    --lean-backend leandojo --max-seeds 1

python scripts/evaluate_traces.py --path data/traces/leandojo_verified.jsonl
```

`data/manual/leandojo_candidates.jsonl` proposes correct tactics plus one bogus
tactic per theorem, so the verified file and the failed file both get rows.

---

## 5. Verify the TraceRecord (acceptance checklist)

A verified `id_of_p` / `exact h` record (in `leandojo_verified.jsonl`) should
show:

- `backend` = `"leandojo"`
- `success` = `true`
- `state_before` = the **real** initial state from LeanDojo (e.g. `p : Prop\nh : p\n⊢ p`)
- `state_after` = `"no goals"` (because `exact h` closes the goal)
- `proof_finished` = `true`
- `num_goals_before` = `1`  (true count, from the live `TacticState`)
- `num_goals_after` = `0`
- `state_changed` = `true`
- `metadata.result_type` present (e.g. `"ProofFinished"`); `metadata.tactic_state_id` when LeanDojo exposes an id

For a real **intermediate** (non-finishing) transition, target `and_comm_toy`
with `constructor`: expect `success=true`, `proof_finished=false`, a real
multi-goal `state_after`, and `num_goals_after = 2`.

The bogus tactic (e.g. `this_is_not_a_tactic`) should land in
`leandojo_failed.jsonl` with `success=false`, a populated `error`, and the
collector must not crash.

If any **field/attribute mismatch** appears (e.g. LeanDojo uses a different name
than `.pp` / `.num_goals` / `ProofFinished`), adjust the small helpers in
`LeanDojoRunner` (`_pp`, `_goal_count`, `_map_result`) and update
`tests/test_leandojo_runner.py` to match the real shapes. Keep the duck-typing.

---

## 6. What remains (after this doc)

1. Run §1–§5 on Linux/macOS/WSL and capture the real output.
2. Confirm the real LeanDojo result attribute names; patch `_map_result` if
   needed.
3. Record the real `id_of_p` TraceRecord in the project notes as the first
   genuine proof-state transition.

---

## 7. Troubleshooting

| symptom | cause & fix |
| --- | --- |
| `ModuleNotFoundError: No module named 'termios'` / `'fcntl'`; `pty` import fails | You are on **native Windows**. LeanDojo needs a Unix PTY (`pexpect`/`ptyprocess`). Use WSL2/Linux/macOS (§1a). Not fixable on native Windows. |
| Tracing is extremely slow, or cache files vanish/corrupt | Repo is under `/mnt/c/...` or OneDrive. **Move it into the Linux home (`~/code/...`).** Avoid OneDrive-synced paths for the LeanDojo cache. |
| Tracing/`Dojo` errors about toolchain or `lean-toolchain` | **Lean version mismatch.** The traced repo pins `examples/leandojo_mini_repo/lean-toolchain` (`v4.30.0`). Set it to a version your installed LeanDojo supports, re-commit, and use that new commit in the seed. |
| `Could not ... GitHub` / rate-limit / private-repo errors | **Missing or unprivileged `GITHUB_ACCESS_TOKEN`.** `export GITHUB_ACCESS_TOKEN=ghp_...` with repo read scope. Never commit or print it. |
| `LeanDojoRunner: start() ... missing repo_url/commit/file_path` | The seed still has `<YOU>` / `<COMMIT_SHA>` placeholders. Fill them (§3). |
| Stale or partial traces after a failed run | Clear LeanDojo's cache (default `~/.cache/lean_dojo`, override with `CACHE_DIR`) and re-run; ensure the repo builds with `lake build` first. |
| Test asserts fail on `.pp` / `.num_goals` / `ProofFinished` | **LeanDojo API drift.** The runner is duck-typed; confirm the real attribute names and patch `_pp` / `_goal_count` / `_map_result` in `lean_runner.py`, then update `tests/test_leandojo_runner.py`. Keep the duck-typing fallbacks. |
| `error: lean-dojo is not installed` from the CLI | Expected when `lean_dojo` isn't importable. Install it (§1) on a supported OS. The collector exits cleanly (rc=1); it never fakes success. |

---

## 8. Optional CI: GitHub Actions

A manual workflow is provided at `.github/workflows/leandojo-smoke.yml`. It is
**opt-in** (`workflow_dispatch` only — it does not run on push) and honest:

- `ubuntu-latest`, Python set up, `pip install -e .[dev]` then `pip install lean-dojo`.
- Installs `elan` (Lean + Lake) and caches `~/.elan` + pip.
- Always runs the normal suite (`pytest -q`), which works without LeanDojo.
- Runs the real smoke test **only if** the `GH_PAT_FOR_LEANDOJO` secret and the
  `repo_url` / `commit` inputs are provided; otherwise it prints why it skipped
  and still succeeds. The token is passed via env from a secret and never echoed.

**Required to actually exercise LeanDojo in CI:**

- Repository **secret** `GH_PAT_FOR_LEANDOJO` — a GitHub token LeanDojo uses to
  fetch/trace the mini repo (read scope on that repo). Exposed to the job only as
  `GITHUB_ACCESS_TOKEN`; never logged.
- Workflow **inputs** `repo_url` and `commit` — coordinates of your published
  `leandojo_mini_repo` (see §2). Without them the smoke step is skipped, not failed.

Caveat: LeanDojo tracing on hosted runners can be slow and version-sensitive; the
workflow is best-effort and may need toolchain tweaks (§7) on first use. It has
**not** been executed from this environment — treat its first green run as the
real validation.

---

## 8. Known limitation: elaboration-time stdin (2026-05-27, WSL2 Ubuntu)

We got **one step further** than the §0 snapshot: lean-dojo 4.20.0 installed
cleanly in a WSL2 venv, the mini repo at `weijiawang2003/leandojo-ELF`
(commit `15c3599…`) traced successfully, and `runner.start(seed)` returns a
**real** initial tactic state for `id_of_p`:

```
TacticState(pp='p : Prop\nh : p\n⊢ p', id=0, message=None)  num_goals=1
```

The very first `runner.run_tactic(state0, "assumption")` then raises
`DojoCrashError: Unexpected EOF`. The runner is **not** at fault. Direct probes
in `scripts/` pin the cause inside Lean itself, two layers below the Python:

### Symptom (faithful pexpect repro of LeanDojo's exact REPL launch)
`scripts/debug_leandojo_pexpect.py` spawns `lake env lean --threads=1 …` on
LeanDojo's modified file and dumps the raw bytes. Before *any* request is sent:

```
init match : 'REPL> {"tacticState": "p : Prop\nh : p\n⊢ p", "sid": 0, "error": null}'
init before: 'MiniDojoPexpectRepl.lean:7:2: error: [fatal] failed to parse JSON
              offset 0: unexpected end of input'
post-send  : ''         # process already gone
exitstatus : 1
```

The `[fatal] failed to parse JSON offset 0: unexpected end of input` comes from
`Lean4Repl.lean`'s `loop`:

```lean
let line := (← (← IO.getStdin).getLine).trim
match (Json.parse line) with
| .error err => throwError s!"[fatal] failed to parse JSON {err}"
```

Reading offset 0 of an empty string means `getLine` returned `""`, i.e. EOF.
The REPL prints the init state, then dies on its very first `getLine` — long
before our code can call `dojo.run_tac`. `Dojo._read_next_line` happens to
scrape the printed `REPL>` line (treating the error line as a "message"), so
`start()` looks successful.

### Root cause (verified across Lean toolchains)
`scripts/probe_async.sh` runs a minimal custom **elab tactic** (not `#eval`,
which is documented to lack stdin) that does
`let line ← (← IO.getStdin).getLine` and prints it. With piped/`<`-redirected
input and a pty, on Lean **4.20.0** *and* **4.30.0**, with `Elab.async` on *and*
off, the result is always:

```
PROBE_GOT[] len=0
```

i.e. `getLine` returns immediately with EOF — `IO.getStdin` during file
elaboration is **not** the process stdin in either toolchain. This is the same
limitation the Lean docs call out for `#eval` ("reading from standard input
simply returns empty input"), now confirmed to apply to elab tactics in
`lean file.lean` batch mode too. LeanDojo's `Lean4Repl` interactive design
depends on that channel.

### What it means for this repo

- The mock and lean-cli backends are unaffected and remain the default.
- `LeanDojoRunner` is API-correct: `Dojo.run_tac(state: TacticState, tactic:
  str)` matches `inspect.signature`, `ProofFinished.tactic_state_id` is now
  captured in metadata (previously only `.id` was tried — see
  `tests/test_leandojo_runner_real_api.py::test_proof_finished_captures_real_tactic_state_id`),
  and `DojoCrashError("Unexpected EOF")` gets an actionable hint appended
  without swallowing the original message.
- `tests/test_leandojo_smoke_real.py` is marked `xfail(strict=True)` so it
  still runs end-to-end against the real LeanDojo (when `MINI_ELF_LEANDOJO_SMOKE=1`)
  but documents the toolchain gap. If a future Lean release restores
  elaboration-time stdin, the test will XPASS and fail loudly — that's our
  signal to flip the marker back to a hard assertion.

### Things we ruled out
- `--memory` flag (already removed from the installed `dojo.py`): unrelated;
  `--memory=N` *is* a valid `lean` flag, but its removal made init succeed and
  isn't tied to the per-tactic crash (probes without `--memory` show the same EOF).
- Wrong `run_tac` argument order / wrong state object: signature is
  `(state: TacticState, tactic: str)`, runner stores the live TacticState in
  its registry and retrieves it (test: `test_initial_state_pp_and_id_round_trip`,
  `test_run_tac_called_with_object_not_pp_string`).
- Tactic payload format: `run_tac(state, "assumption")` with the real state
  hits the same EOF — the JSON request never gets read because the REPL is
  already gone.
- `Elab.async`: setting it `false` via `set_option` *or* CLI `-D Elab.async=false`
  does not restore stdin (`probe_async.sh` step 1 and 2 still get `len=0`).
- Lean version: same EOF on 4.20.0 (repo toolchain via `lake env`) and 4.30.0
  (default PATH).

### Reproducers (all in `scripts/`)
- `debug_leandojo_direct.py` — minimal `Dojo(theorem)` + `dojo.run_tac` with
  the real seed, with `dojo.proc.logfile_read = sys.stdout`. Shows the
  `DojoCrashError: Unexpected EOF` exactly as the runner sees it.
- `debug_leandojo_pexpect.py` — spawns LeanDojo's exact command directly via
  `pexpect`, reads init, then drains everything until EOF so you can see
  Lean's pre-crash output (the `[fatal] failed to parse JSON` line above).
- `debug_leandojo_manual_repl.py` — copies the modified file to a persistent
  location and runs `lake env lean` on it via `subprocess`, with stdout and
  stderr captured separately, confirming the crash is independent of `pexpect`.
- `probe.lean` + `probe_versions.sh` — self-contained elab-tactic stdin probe
  run across Lean 4.20.0 / 4.30.0 via `elan run`.
- `probe_async.sh` — same probe with `set_option Elab.async false` and
  `-D Elab.async=false` to rule out async elaboration.
