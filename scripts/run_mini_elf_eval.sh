#!/usr/bin/env bash
# Evaluate Mini-ELF v0 with real lean-cli pass@k on val + test, in both decode
# modes (decoder = generative; nn = nearest-neighbour ablation). Uses the
# concrete toolchain binary to avoid the WSL2 elan-shim stall.
#   wsl -d Ubuntu -- bash -lc 'bash "$HOME/code/ELFMath/scripts/run_mini_elf_eval.sh"'
set -euo pipefail

cd "$HOME/code/ELFMath"
export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
PY=./.venv/bin/python

echo "lean: $("$MINI_ELF_LEAN_COMMAND" --version 2>&1 | head -1)"

for decode in decoder nn; do
  suffix=""
  if [ "$decode" = "nn" ]; then suffix="_nn"; fi
  for split in val test; do
    echo "=== EVAL decode=$decode split=$split ==="
    "$PY" scripts/evaluate_mini_elf.py \
      --model-dir data/models/basic_lean_cli_mini_elf \
      --dataset data/processed/basic_lean_cli/next_tactic.jsonl \
      --output-dir "data/baselines/basic_lean_cli_mini_elf_${split}${suffix}" \
      --split "$split" --top-k 5 --n-samples 32 --flow-steps 10 --decode "$decode" \
      --verify-with-lean-cli --cache \
      --seeds data/seeds/basic_lean_seeds.jsonl \
      > "/tmp/mini_elf_eval_${decode}_${split}.log" 2>&1
    echo "done decode=$decode split=$split"
  done
done
echo "ALL DONE"
