#!/usr/bin/env bash
# Part 5: train Mini-ELF v2 on the combined (basic+hard) corpus under three split
# strategies and evaluate with real lean-cli pass@k. Answers: does adding hard,
# less-templated training data recover the generalization v1 lost (Part 4)?
#   wsl -d Ubuntu -- bash -lc 'bash "$HOME/code/ELFMath/scripts/run_mini_elf_v2_eval.sh"'
set -euo pipefail
cd "$HOME/code/ELFMath"
export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
PY=./.venv/bin/python
VTRACES="data/traces/basic_lean_cli_verified.jsonl data/traces/hard_lean_cli_verified.jsonl"
FTRACES="data/traces/basic_lean_cli_failed.jsonl data/traces/hard_lean_cli_failed.jsonl"
SEEDS="data/seeds/basic_lean_seeds.jsonl data/seeds/hard_lean_seeds.jsonl"
CSEEDS=data/seeds/combined_lean_seeds.jsonl

train_v2() {  # dataset_dir model_dir
  local ds="$1" model="$2"
  echo "=== TRAIN v2 -> $model (dataset $ds) ==="
  $PY scripts/train_mini_elf_v2.py \
    --dataset "data/processed/${ds}/next_tactic.jsonl" --output-dir "$model" \
    --verified-traces $VTRACES --failed-traces $FTRACES \
    --splits "data/processed/${ds}/theorem_splits.json" --seeds $SEEDS \
    --ae-epochs 100 --flow-epochs 500 --rerank-epochs 100 \
    --self-train-rerank --self-train-max 10 --latent-dim 64 --n-samples 64 --seed 0 \
    > "/tmp/train_${model//\//_}.log" 2>&1
  echo "trained $model"
}

seed_cache() {
  local target="$1"; mkdir -p "$target"
  "$PY" - "$target/verification_cache.json" <<'PYEOF'
import glob, json, sys
merged = {}
for f in glob.glob("data/baselines/*/verification_cache.json"):
    try: merged.update(json.load(open(f)))
    except Exception: pass
json.dump(merged, open(sys.argv[1], "w"), indent=2, sort_keys=True)
PYEOF
}

eval_v2() {  # model_dir dataset_dir split out_suffix
  local model="$1" ds="$2" split="$3" suffix="$4"
  local out="data/baselines/combined_lean_cli_mini_elf_v2_${suffix}"
  echo "=== EVAL v2 $suffix ($model on $ds:$split) ==="
  seed_cache "$out"
  "$PY" scripts/evaluate_mini_elf_v2.py \
    --model-dir "$model" --dataset "data/processed/${ds}/next_tactic.jsonl" \
    --output-dir "$out" --split "$split" --mode decoder_rerank_witness \
    --top-k 5 --n-samples 64 --flow-steps 10 --verify-with-lean-cli --cache --seeds "$CSEEDS" \
    > "/tmp/eval_v2_${suffix}.log" 2>&1
  echo "done $suffix"
}

if [ "${SKIP_TRAIN:-0}" != "1" ]; then
  train_v2 combined_lean_cli                      data/models/combined_lean_cli_mini_elf_v2
  train_v2 combined_lean_cli_difficulty_holdout   data/models/combined_lean_cli_mini_elf_v2_difficulty
  train_v2 combined_lean_cli_adversarial_sibling  data/models/combined_lean_cli_mini_elf_v2_adversarial
fi

# Regression check + main generalization results (all leakage-free per strategy).
eval_v2 data/models/combined_lean_cli_mini_elf_v2             basic_lean_cli                       test basic_test
eval_v2 data/models/combined_lean_cli_mini_elf_v2             hard_lean_cli_hash                   test hard_hash_test
eval_v2 data/models/combined_lean_cli_mini_elf_v2_difficulty  combined_lean_cli_difficulty_holdout test hard_difficulty_test
eval_v2 data/models/combined_lean_cli_mini_elf_v2_adversarial combined_lean_cli_adversarial_sibling test hard_adversarial_test

echo
echo "=== v2 comparison ==="
"$PY" scripts/summarize_v2.py
echo "ALL DONE"
