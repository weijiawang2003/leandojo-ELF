#!/usr/bin/env bash
# V4 Part 4: evaluate the EXISTING systems (AR, Mini-ELF v1, v2, v3) on the
# planner-blind corpus with real lean-cli pass@k. The v3 planner is used
# UNCHANGED (no new templates) — its fallback to the learned generator +
# witness-copy on shapes it cannot construct is the real robustness test.
#   wsl -d Ubuntu -- bash -lc 'bash "$HOME/code/ELFMath/scripts/run_planner_blind_eval.sh"'
set -euo pipefail
cd "$HOME/code/ELFMath"
export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
PY=./.venv/bin/python
DS=data/processed/planner_blind_lean_cli/next_tactic.jsonl
SEEDS=data/seeds/planner_blind_seeds.jsonl

seed_cache() {  # merge all prior caches incl. the corpus collection probe
  local target="$1"; mkdir -p "$target"
  "$PY" - "$target/verification_cache.json" <<'PYEOF'
import glob, json, sys
merged = {}
for f in glob.glob("data/baselines/*/verification_cache.json") + ["/tmp/blind_probe_cache.json"]:
    try: merged.update(json.load(open(f)))
    except Exception: pass
json.dump(merged, open(sys.argv[1], "w"), indent=2, sort_keys=True)
PYEOF
}

eval_ar() {
  local out="data/baselines/planner_blind_ar_test"
  echo "=== EVAL AR ==="; seed_cache "$out"
  "$PY" scripts/evaluate_ar_model.py --model-dir data/models/basic_lean_cli_ar \
    --dataset "$DS" --output-dir "$out" --split test --top-k 5 \
    --verify-with-lean-cli --cache --seeds "$SEEDS" > /tmp/blind_ar.log 2>&1
  echo "done AR"
}

eval_v12() {  # model_dir out_suffix
  local model="$1" suffix="$2"
  local out="data/baselines/planner_blind_${suffix}"
  echo "=== EVAL $suffix ($model) ==="; seed_cache "$out"
  "$PY" scripts/evaluate_mini_elf_v1.py --model-dir "$model" \
    --dataset "$DS" --output-dir "$out" --split test --mode decoder_rerank_witness \
    --top-k 5 --n-samples 64 --flow-steps 10 --verify-with-lean-cli --cache --seeds "$SEEDS" \
    > "/tmp/blind_${suffix}.log" 2>&1
  echo "done $suffix"
}

eval_v3() {  # planner ON, unchanged
  local out="data/baselines/planner_blind_v3_test"
  echo "=== EVAL v3 (planner unchanged) ==="; seed_cache "$out"
  "$PY" scripts/evaluate_mini_elf_v3.py --model-dir data/models/combined_lean_cli_mini_elf_v2 \
    --dataset "$DS" --output-dir "$out" --split test --top-k 5 --n-samples 64 --flow-steps 10 \
    --verify-with-lean-cli --cache --seeds "$SEEDS" > /tmp/blind_v3.log 2>&1
  echo "done v3"
}

eval_ar
eval_v12 data/models/basic_lean_cli_mini_elf_v1     v1_test
eval_v12 data/models/combined_lean_cli_mini_elf_v2  v2_test
eval_v3
echo "ALL DONE"
