#!/usr/bin/env bash
# Train one v11 per-family seq2seq per held family. Same architecture as v8/v10
# (CPU bi-GRU + attention; seed 0; 30 epochs; beam@10). Skips folds whose
# model.pt already exists.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/bin/python

for fold_dir in data/processed/proof_blocks_v11_family_lofo/*/; do
    [ -d "$fold_dir" ] || continue
    fam=$(basename "$fold_dir")
    out="data/models/proof_block_seq2seq_v11_family_${fam}"
    if [ -f "$out/model.pt" ]; then
        echo "SKIP $out (already trained)"
        continue
    fi
    echo "TRAIN v11/$fam"
    "$PY" scripts/train_proof_block_seq2seq.py \
        --regime-dir "$fold_dir" --out-dir "$out" \
        --epochs 30 --seed 0 2>&1 | tail -3
done
echo "ALL V11 PER-FAMILY MODELS TRAINED"
