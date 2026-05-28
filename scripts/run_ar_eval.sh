#!/usr/bin/env bash
# Evaluate the trained AR seq2seq model with real lean-cli pass@k on val + test.
# Uses the concrete toolchain binary (not the elan shim) to avoid the WSL2
# network-resolution stall. Run from anywhere:
#   wsl -d Ubuntu -- bash -lc 'bash "$HOME/code/ELFMath/scripts/run_ar_eval.sh"'
set -euo pipefail

cd "$HOME/code/ELFMath"
export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
PY=./.venv/bin/python

echo "lean: $("$MINI_ELF_LEAN_COMMAND" --version 2>&1 | head -1)"

for split in val test; do
  echo "=== EVAL $split ==="
  "$PY" scripts/evaluate_ar_model.py \
    --model-dir data/models/basic_lean_cli_ar \
    --dataset data/processed/basic_lean_cli/next_tactic.jsonl \
    --output-dir "data/baselines/basic_lean_cli_ar_${split}" \
    --split "$split" --top-k 5 --beam-width 5 \
    --verify-with-lean-cli --cache \
    --seeds data/seeds/basic_lean_seeds.jsonl \
    > "/tmp/ar_eval_${split}.log" 2>&1
  echo "done $split -> data/baselines/basic_lean_cli_ar_${split}"
done
echo "ALL DONE"
