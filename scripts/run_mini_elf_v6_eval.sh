#!/usr/bin/env bash
# V6 Part 6: structure-aware retrieval evaluation on the same planner-blind
# within-family split as v5 (family_interpolation, 32 test / 29 train theorems),
# so v5 vs v6 is apples-to-apples.
#
# Compares: v5 retrieval | v6 retrieval | v5 fusion | v6 fusion | v6 fusion w/o
# structural terms | v6 fusion w/o adapted-preference. v6 changes retrieval
# RANKING only — no new proof templates; v4 template ablations stay separate.
#   wsl -d Ubuntu -- bash -lc 'bash "$HOME/code/ELFMath/scripts/run_mini_elf_v6_eval.sh"'
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
  echo "=== V6 EVAL ${config} -> ${out} ==="
  mkdir -p "$out"
  "$PY" scripts/_seed_cache.py "$out/verification_cache.json"
  "$PY" scripts/evaluate_mini_elf_v6.py --config "$config" \
    --dataset "$DS" --output-dir "$out" --split test --top-k 5 \
    --seeds "$SEEDS" --verify-with-lean-cli --cache "$@" \
    > "/tmp/v6_${suffix}.log" 2>&1
  echo "done ${config}"
}

run v5_retrieval     planner_blind_v6_v5retrieval_test
run v6_retrieval     planner_blind_v6_retrieval_test
run v5_fusion        planner_blind_v6_v5fusion_test               --model-dir "$MODEL"
run v6_fusion        planner_blind_v6_fusion_test                 --model-dir "$MODEL"
run v6_no_structure  planner_blind_v6_ablation_no_structure_test  --model-dir "$MODEL"
run v6_no_adapt_pref planner_blind_v6_ablation_no_adapt_pref_test --model-dir "$MODEL"
echo "ALL DONE"
