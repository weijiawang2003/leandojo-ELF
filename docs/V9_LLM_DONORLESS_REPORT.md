# Mini-ELF v9 — LLM donorless pilot — SKIPPED (no API key)

**Why skipped.** Neither `ANTHROPIC_API_KEY` nor `OPENAI_API_KEY` was set in
the v9 environment. The pilot would have called a real LLM endpoint, and the
v8/v9 briefs explicitly forbid faking a result. The pilot is therefore
reported as `skipped` rather than as `pass@k = 0.00` — fabricating a zero
would conflate *not-tested* with *tested-and-failed*, which the project has
been careful to avoid since v5.

## What would have run if a key were present

Targets (the v9 brief's focus list — every regime where the v8 seq2seq scored
`pass@5 = 0.000`):

1. `family_holdout/forall_inst` (7 unique theorems)
2. `operation_holdout/instantiate_forall` (7 unique theorems)
3. `family_holdout/rewrite_succ`
4. `family_holdout/neg_imp_exfalso` (5 unique theorems)
5. `donorless_eval` strict rows (61 unique theorems; train pool excludes every
   planner-blind family)

Per theorem: 10 candidates from `LLMProposer` (the v5/v8 wrapper, source label
`llm_proposer`). Each candidate is cleaned by
`proof_block_cleaner.clean_candidates` and verified by
`make_lean_cli_verifier` against a shared cache.

Metrics: `pass@1`, `pass@5`, `pass@10`, per-group, `novel_verified`,
`donorless_verified`, `cross_family_verified`, `cross_operation_verified`.

## How to run when a key is available

```bash
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY
./.venv/bin/python scripts/run_v9_llm_donorless_pilot.py
```

## Honesty caveats the brief mandates (and the script enforces)

- The pilot is API-billed and intentionally focused (≤80 theorems total).
- The LLM never sees the `shortest_verified_tactic` field from
  `docs/V8_DONORLESS_TARGETS.md` — that field is for human analysis only.
- LLM-emitted multi-line `state_after`-shaped strings are rejected by the
  cleaner before they reach Lean.
- The pilot does not count manual oracle candidates as LLM results.
- The script's empty SKIPPED path is preserved; running it without a key
  re-emits this document rather than progressing silently.
