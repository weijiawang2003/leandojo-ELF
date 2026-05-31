#!/usr/bin/env bash
# V7 Part 3: evaluate retrieval under donor scarcity with real lean-cli pass@k.
# Builds the splits (idempotent), seeds the shared verification cache from every
# prior baseline (so known (theorem,tactic) pairs are reused), then runs the
# config x split matrix. Retrieval-only (v3 off). No state_after; no new templates.
#   wsl -d Ubuntu -- bash -lc 'bash "$HOME/code/ELFMath/scripts/run_mini_elf_v7_eval.sh"'
set -euo pipefail
cd "$HOME/code/ELFMath"
export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
PY=./.venv/bin/python

echo "=== build splits ==="
"$PY" scripts/build_planner_blind_retrieval_splits.py

echo "=== seed shared verification cache ==="
mkdir -p data/baselines/v7_eval
"$PY" scripts/_seed_cache.py data/baselines/v7_eval/verification_cache.json

echo "=== evaluate matrix ==="
"$PY" scripts/evaluate_retrieval_v7.py \
  --output-dir data/baselines/v7_eval \
  --cache data/baselines/v7_eval/verification_cache.json \
  --top-k 5

echo "=== summarize ==="
"$PY" scripts/summarize_v7.py --summary data/baselines/v7_eval/v7_summary.json
echo "ALL DONE"
