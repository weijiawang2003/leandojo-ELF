#!/usr/bin/env bash
# Part 5: evaluate Mini-ELF v3 (structured proof-block planner ⊕ the v2 model +
# reranker + witness-copy) with real lean-cli pass@k. Reuses the per-split v2
# models (the planner is symbolic, so no retraining); the main target metric is
# the hard difficulty_holdout pass@5 that v1-transfer and v2 both leave at 0.06.
#   wsl -d Ubuntu -- bash -lc 'bash "$HOME/code/ELFMath/scripts/run_mini_elf_v3_eval.sh"'
set -euo pipefail
cd "$HOME/code/ELFMath"
export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
PY=./.venv/bin/python
CSEEDS=data/seeds/combined_lean_seeds.jsonl

seed_cache() {  # merge every prior verification cache (incl. the planner probe) so reruns are cheap
  local target="$1"; mkdir -p "$target"
  "$PY" - "$target/verification_cache.json" <<'PYEOF'
import glob, json, sys
merged = {}
for f in glob.glob("data/baselines/*/verification_cache.json") + ["/tmp/planner_probe_cache.json"]:
    try: merged.update(json.load(open(f)))
    except Exception: pass
json.dump(merged, open(sys.argv[1], "w"), indent=2, sort_keys=True)
PYEOF
}

eval_v3() {  # model_dir dataset_dir split out_suffix [extra flags...]
  local model="$1" ds="$2" split="$3" suffix="$4"; shift 4
  local out="data/baselines/mini_elf_v3_${suffix}"
  echo "=== EVAL v3 $suffix ($model on $ds:$split) ==="
  seed_cache "$out"
  "$PY" scripts/evaluate_mini_elf_v3.py \
    --model-dir "$model" --dataset "data/processed/${ds}/next_tactic.jsonl" \
    --output-dir "$out" --split "$split" --top-k 5 --n-samples 64 --flow-steps 10 \
    --verify-with-lean-cli --cache --seeds "$CSEEDS" "$@" \
    > "/tmp/eval_v3_${suffix}.log" 2>&1
  echo "done $suffix"
}

# Main generalization results (all leakage-free: planner is symbolic; v2 models per strategy).
eval_v3 data/models/combined_lean_cli_mini_elf_v2_difficulty  combined_lean_cli_difficulty_holdout  test hard_difficulty_test
eval_v3 data/models/combined_lean_cli_mini_elf_v2_adversarial combined_lean_cli_adversarial_sibling test hard_adversarial_test
eval_v3 data/models/combined_lean_cli_mini_elf_v2             hard_lean_cli_hash                    test hard_hash_test
eval_v3 data/models/combined_lean_cli_mini_elf_v2             basic_lean_cli                        test basic_test

# Ablation on the target split: planner OFF == pure v2 through the same harness.
eval_v3 data/models/combined_lean_cli_mini_elf_v2_difficulty  combined_lean_cli_difficulty_holdout  test hard_difficulty_test_noplanner --no-planner

echo "ALL DONE"
