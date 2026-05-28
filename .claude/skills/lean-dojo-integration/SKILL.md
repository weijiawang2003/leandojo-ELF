---
name: lean-dojo-integration
description: Use when connecting LeanDojo, debugging Lean execution, or extracting proof states. Keeps LeanDojo-specific code isolated behind a stable LeanRunner interface and prevents hallucinated LeanDojo APIs.
---

# Lean Dojo Integration Skill

Use this skill when wiring LeanDojo into the trace collector, debugging tactic execution, or extracting proof states from Lean.

## Core Principle

All Lean execution must sit behind a single `LeanRunner` interface. LeanDojo-specific code lives in exactly one module (`lean_runner.py`) and is never imported elsewhere.

## Interface Contract

A `LeanRunner` exposes:

- `start(theorem)` -> opens a proof session and returns an initial `state`.
- `run_tactic(state, tactic, timeout)` -> returns a result with:
  - `next_state` (or `None` on failure)
  - `proof_finished: bool`
  - `error: Optional[str]`
  - `num_goals: int` (for the returned state)
- `close()` -> releases resources.

`MockLeanRunner`, `LeanCliRunner`, and `LeanDojoRunner` must all satisfy this contract identically. Pipeline code MUST work unchanged when swapping backends. Adding or wiring up LeanDojo must NOT break the mock or lean-cli backends.

## Why LeanDojo (later)

`lean-cli` verifies a whole template file: success means the file typechecks, so its `state_after` is only a placeholder (`<verified by lean-cli>`). LeanDojo is what gives true `state_before → tactic → state_after` transitions and accurate per-step goal counts. Until LeanDojo is actually wired, do not pretend lean-cli output contains real intermediate states.

## Implementation status

`LeanDojoRunner` in `lean_runner.py` is implemented (not a scaffold). Key design
decisions to preserve:

- The `LeanRunner` protocol passes proof states as **strings**, but LeanDojo
  needs the live `TacticState` **object**. The runner keeps a registry mapping
  each state's pretty-printed string back to its `TacticState`; `start()` seeds
  the initial state and every ongoing success registers its result. This makes
  per-state fan-out (many candidates from one state) and multi-step search work
  without changing the interface. Do not collapse this into a single mutable
  "current state".
- Result mapping is **duck-typed**, not `isinstance`-based: a result with `.pp`
  is an ongoing `TacticState`; a class named `ProofFinished` closes the goal;
  anything else is an error. This tolerates LeanDojo version churn — but the
  exact attribute names must be confirmed on first real run.
- The constructor accepts an injected module (`lean_dojo_module=`) so tests use a
  fake; production passes nothing and imports the real package.
- It has NOT yet been validated against real LeanDojo (package not installed in
  this environment). Do not claim a real LeanDojo smoke success until it runs.

## LeanDojo Usage Rules

- Import `lean_dojo` lazily inside the LeanDojoRunner constructor.
- If the import fails, raise a clear error telling the user to install LeanDojo, but do NOT crash the whole package on import.
- Use `Dojo(theorem)` as a context manager; never leak Dojo sessions.
- Use `TacticState` / `ProofFinished` / `LeanError` types; map them into the unified result schema above.
- Never assume a specific Lean toolchain version. Read versions from the seed/config, not from hardcoded strings.

## Robustness Requirements

- Every `run_tactic` call must be wrapped in a timeout (default 60s). On timeout, return `error="timeout"` and `next_state=None`.
- Catch all exceptions from LeanDojo and surface them as `error=str(e)`; never let an exception kill the collector loop.
- Log every tactic execution at DEBUG level with: theorem_name, tactic (truncated), result kind, elapsed_ms.
- Record `state_before`, `tactic`, `state_after`, and `error` for every attempt so failures are inspectable later.

## Configuration

- Repo URL, commit, and theorem file path come from the seed record or a config file - never hard-coded inside the runner.
- Local cache paths come from environment variables (`LEAN_DOJO_CACHE_DIR`, etc.), never absolute user paths.

## Do Not

- Do not import `lean_dojo` at module top-level outside `lean_runner.py`.
- Do not silently swallow LeanDojo errors - record them.
- Do not assume LeanDojo is installed in tests; tests must use `MockLeanRunner`.
- Do not duplicate Lean parsing logic outside the runner.
