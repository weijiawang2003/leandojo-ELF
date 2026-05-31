#!/usr/bin/env bash
# V5 Part 6: unified evaluation of the candidate-proposer configurations on the
# planner-blind *within-family split* test set (family_interpolation: each family
# has held-out test theorems + same-family train donors, no theorem leaks).
#
# Compares, on the SAME 32-theorem test split (so numbers are apples-to-apples):
#   v3 unchanged | v4 templates (both, labelled) | retrieval | retrieval-verbatim
#   | v3 + retrieval | v3 + retrieval + v4 templates | LLM (skips w/o key)
#
# The all-test v4 numbers (61 theorems) remain the separate off-library headline.
# Manual-oracle candidates are NEVER wired in. Theorem-level lean-cli only.
#   wsl -d Ubuntu -- bash -lc 'bash "$HOME/code/ELFMath/scripts/run_mini_elf_v5_eval.sh"'
set -euo pipefail
cd "$HOME/code/ELFMath"
export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
PY=./.venv/bin/python
DS=data/processed/planner_blind_split_lean_cli/next_tactic.jsonl
SEEDS=data/seeds/planner_blind_seeds.jsonl
MODEL=data/models/combined_lean_cli_mini_elf_v2

run() {  # config out_suffix [extra flags...]
  local config="$1" suffix="$2"; shift 2
  local out="data/baselines/${suffix}"
  echo "=== V5 EVAL ${config} -> ${out} ==="
  mkdir -p "$out"
  "$PY" scripts/_seed_cache.py "$out/verification_cache.json"
  "$PY" scripts/evaluate_mini_elf_v5.py --config "$config" \
    --dataset "$DS" --output-dir "$out" --split test --top-k 5 \
    --seeds "$SEEDS" --verify-with-lean-cli --cache "$@" \
    > "/tmp/v5_${suffix}.log" 2>&1
  echo "done ${config}"
}

# v3-based configs need the v2 model dir.
run v3                       planner_blind_split_v3_test                       --model-dir "$MODEL"
run v4_templates             planner_blind_split_v4templates_test              --model-dir "$MODEL"
run retrieval                planner_blind_retrieval_proposer_test
run retrieval_verbatim       planner_blind_retrieval_verbatim_test
run v3_retrieval             planner_blind_v5_retrieval_fusion_test            --model-dir "$MODEL"
run v3_retrieval_v4templates planner_blind_v5_retrieval_fusion_v4templates_test --model-dir "$MODEL"
run llm                      planner_blind_v5_llm_test
echo "ALL DONE"
