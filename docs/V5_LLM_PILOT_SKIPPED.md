# Mini-ELF v5 — LLM proposer pilot (SKIPPED)

The LLM proof-block proposer pilot was **not run**: no API key is configured in this environment.

- `available`: False
- `backend`: None
- reason: no API key (ANTHROPIC_API_KEY / OPENAI_API_KEY unset)

No output was faked. The proposer (`src/mini_elf_lean/llm_proposer.py`) and this runner (`scripts/run_llm_proposer_pilot.py`) are implemented and unit-tested for the skip path; set `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) and re-run:

```
wsl -d Ubuntu -- bash -lc 'cd ~/code/ELFMath && \
  ANTHROPIC_API_KEY=... MINI_ELF_LEAN_COMMAND=<lean> \
  ./.venv/bin/python scripts/run_llm_proposer_pilot.py \
    --dataset data/processed/planner_blind_split_lean_cli/next_tactic.jsonl \
    --seeds data/seeds/planner_blind_seeds.jsonl --verify-with-lean-cli'
```

Expected result if run: the LLM is the only source that could solve the template-less families with **no** same-shape donor; the pilot would measure candidates/theorem, unique/verified, pass@1/5, per-family pass@5, `novel_verified`, and an error taxonomy. See `docs/V5_TARGET_FAMILIES.md`.
