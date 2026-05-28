---
name: lean-trace-collector
description: Use when building or modifying the LLM-proposes / Lean-verifies / JSONL-trace pipeline. Triggers include "collect Lean traces", "run LLM proposed tactics", "verify tactics", "build trace dataset".
---

# Lean Trace Collector Skill

Use this skill when working on LLM-proposed, Lean-verified tactic trace collection.

## Core Principle

Candidate generators propose. Lean verifies. (LLM proposes. Lean verifies.)

Never treat a raw candidate tactic as ground truth, regardless of where it came from. Save a tactic as a positive training transition only if Lean successfully executes it (`success=True`). Failed attempts go to a separate file, never into the verified set.

## Candidate Sources (all behind `LLMClient`)

A candidate source only proposes; it never decides correctness. Supported sources:

- `mock` — deterministic, no API key, used by tests and smoke runs.
- `manual-file` — read candidates from a hand-written / agent-authored JSONL
  under `data/manual/` (CLI: `--manual-candidates PATH`). This is how you use
  Claude (or any tool) as the proposer and still have Lean verify.
- `anthropic` / `openai` — real API clients (lazy import, env-var keys, disk cache).

`get_llm_client(settings, cache=, manual_candidates_path=)` is the factory.

## Lean Verification Backends (all behind `LeanRunner`)

- `mock` — pipeline tests only; NOT real verification.
- `lean-cli` — real Lean subprocess; verifies a whole template file (success ⇔
  file typechecks). Does **not** yet yield true intermediate `state_after`.
- `leandojo` — scaffold/future; needed for real `state_before → tactic →
  state_after` transitions.

`get_lean_runner(settings)` is the factory. Mock and lean-cli must keep working
even when LeanDojo is not installed.

## Prompt Styles

`conservative`, `diverse` (default), `no_automation`, `tactic_block`. The style
is recorded on each record (`prompt_style`) so the auditor can report its
distribution.

## Target Transition Schema

Each successful transition should include:

- theorem_name
- theorem_statement
- state_before
- tactic
- state_after
- proof_finished
- num_goals_before
- num_goals_after
- state_changed
- success
- source
- model
- backend
- prompt_style
- temperature
- timeout
- timestamp

Failed attempts may be saved separately, but must not be mixed into verified training labels.

## Pipeline

1. Load theorem seeds from JSONL.
2. Build an LLM prompt from theorem statement and current proof state.
3. Ask for K candidate tactics, one per line.
4. Sanitize candidates.
5. Deduplicate candidates.
6. Reject forbidden tactics:
   - sorry
   - admit
   - unsafe
7. Execute each tactic through a LeanRunner backend.
8. Save successful transitions to JSONL.
9. Optionally save failed attempts to a separate JSONL.
10. Print collection statistics.

## Engineering Rules

- Keep Lean execution behind a `LeanRunner` interface.
- Keep LLM calls behind an `LLMClient` interface.
- Support a mock backend for tests.
- Do not hard-code API keys.
- Use environment variables for API keys.
- Add timeout handling.
- Add logging.
- Make scripts runnable from the repository root.
- Prefer small reliable end-to-end prototypes over large incomplete systems.

## Do Not

- Do not implement or train Mini-ELF in this stage (this is the data-factory stage).
- Do not assume LeanDojo is installed; mock and lean-cli must work without it.
- Do not mix raw candidates with verified traces.
- Do not discard failed attempts silently — log missing manual candidates, count dropped duplicates/forbidden.
- Do not split train/test by transition if theorem names are available.
- Do not write tactics that contain `sorry`, `admit`, or `unsafe` into the verified trace file.
