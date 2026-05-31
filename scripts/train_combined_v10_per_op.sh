#!/usr/bin/env bash
# Train one combined_v10 seq2seq per held operation, each with the v10 cells of
# that operation removed from train. Used to produce clean op_holdout metrics
# (the legacy combined_v10 was trained on all v10 cells and leaked into test).
set -uo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/bin/python

for op_dir in data/processed/proof_blocks_combined_v10_per_op/*/; do
    [ -d "$op_dir" ] || continue
    op=$(basename "$op_dir")
    out="data/models/proof_block_seq2seq_combined_v10_per_op/$op"
    if [ -f "$out/model.pt" ]; then
        echo "SKIP $out (already trained)"
        continue
    fi
    echo "TRAIN per_op/$op"
    "$PY" scripts/train_proof_block_seq2seq.py \
        --regime-dir "$op_dir" --out-dir "$out" \
        --epochs 30 --seed 0 2>&1 | tail -3
done
echo "ALL PER-OP MODELS TRAINED"
