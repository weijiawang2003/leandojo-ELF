#!/usr/bin/env bash
# Part 4: evaluate the *basic-corpus* Mini-ELF v1 model on the HARD corpus
# (4 split strategies, test split) WITHOUT retraining — does v1 transfer under
# distribution shift? Leakage-free: v1 never saw any hard theorem.
#   wsl -d Ubuntu -- bash -lc 'bash "$HOME/code/ELFMath/scripts/run_v1_transfer_eval.sh"'
set -euo pipefail
cd "$HOME/code/ELFMath"
export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
PY=./.venv/bin/python
MODEL=data/models/basic_lean_cli_mini_elf_v1
SEEDS=data/seeds/hard_lean_seeds.jsonl

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

transfer_eval() {  # strategy mode out_suffix
  local strat="$1" mode="$2" suffix="$3"
  local out="data/baselines/hard_lean_cli_transfer_v1_${suffix}"
  echo "=== TRANSFER v1 strategy=$strat mode=$mode -> $out ==="
  seed_cache "$out"
  "$PY" scripts/evaluate_mini_elf_v1.py \
    --model-dir "$MODEL" \
    --dataset "data/processed/hard_lean_cli_${strat}/next_tactic.jsonl" \
    --output-dir "$out" --split test --mode "$mode" --top-k 5 --n-samples 64 --flow-steps 10 \
    --verify-with-lean-cli --cache --seeds "$SEEDS" \
    > "/tmp/transfer_${suffix}.log" 2>&1
  echo "done $suffix"
}

transfer_eval hash                decoder_rerank_witness hash_test
transfer_eval family_holdout      decoder_rerank_witness family_holdout_test
transfer_eval difficulty_holdout  decoder_rerank_witness difficulty_holdout_test
transfer_eval adversarial_sibling decoder_rerank_witness adversarial_sibling_test
# reranker-contribution probe on the in-distribution-shape hash split:
transfer_eval hash                decoder_no_rerank      hash_test_norerank
echo "ALL DONE"
