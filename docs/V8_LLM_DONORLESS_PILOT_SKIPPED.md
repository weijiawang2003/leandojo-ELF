# Mini-ELF v8 — LLM donorless pilot — SKIPPED (no API key)

**Why skipped.** Neither `ANTHROPIC_API_KEY` nor `OPENAI_API_KEY` was set in the v8 evaluation environment. The pilot would have called a real LLM endpoint, and the v8 brief explicitly forbids faking a result. The pilot is therefore reported as `skipped` rather than as a zero — fabricating `pass@k=0.00` would conflate *not-tested* with *tested-and-failed*, which the project has been careful to avoid since v5.

**What would have run if a key were present.**

- `scripts/run_llm_donorless_pilot.py` picks a pilot set of 20 donorless   theorems sampled across all v8 donorless groups   (negation/contradiction, contrapositive, exists_elim, forall_inst,   rewrite, exists_reconstruct), one per group when possible.
- It asks `LLMProposer` (the same v5 wrapper, source label   `llm_proposer`) for 10 core-Lean candidates per theorem, system   prompt requiring JSON list, no Mathlib, no prose.
- Each candidate is cleaned by `proof_block_cleaner.clean_candidates`   and verified by `make_lean_cli_verifier` with a shared cache.
- Metrics: `pass@1`, `pass@5`, `pass@10`, per-group, `novel_verified`,   `donorless_verified`, `cross_family_verified`,   `cross_operation_verified`.

**How to run when a key is available.**

```bash
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY
./.venv/bin/python scripts/run_llm_donorless_pilot.py --n-per-set 20
```

**Honesty caveats** the brief mandates and the pilot script enforces:

- The pilot is API-billed and intentionally tiny (20 theorems);   the result is a pilot signal, not a production number.
- LLM-emitted multi-line `state_after`-shaped strings are rejected by   the cleaner before they reach Lean (no state_after, even by accident).
- The pilot never reads the `shortest_verified_tactic` field from   `docs/V8_DONORLESS_TARGETS.md`. That tactic is documented for   human analysis of the proof shape; it is **not** in the LLM prompt.
- The pilot does not count manual oracle candidates as LLM results.
