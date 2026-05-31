#!/usr/bin/env bash
# Evaluate each per-op combined_v10 model on its matching held-operation test
# set. This is the CLEAN replacement for the legacy combined_v10's leaked
# op_holdout metrics.
#
# baseline_v8 (proof_block_seq2seq_interpolation) is also re-evaluated on the
# same per-op test sets for direct comparison. The baseline never saw any
# v10 cell, so its metrics are zero-shot and remain valid.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/bin/python
PER_FOLD_TIMEOUT="${PER_FOLD_TIMEOUT:-300}"
OUT_ROOT="data/baselines/v10_eval_clean"

run_one () {
    local regime_dir="$1"; local model_dir="$2"; local out_dir="$3"
    if [ -f "$out_dir/metrics.json" ]; then
        echo "SKIP   $out_dir"
        return
    fi
    if [ ! -f "$model_dir/model.pt" ]; then
        echo "MISS_MODEL $model_dir"
        return
    fi
    if [ ! -d "$regime_dir" ]; then
        echo "MISS_REGIME $regime_dir"
        return
    fi
    echo "EVAL   $out_dir"
    timeout "$PER_FOLD_TIMEOUT" "$PY" scripts/evaluate_proof_block_seq2seq.py \
        --regime-dir "$regime_dir" --model-dir "$model_dir" --out-dir "$out_dir" \
        --top-k 10 --beam-width 10 \
        --verifier-timeout 20 \
        --cache data/lean_cache/v10_clean_seq2seq_cache.json
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "  -> exit $rc (likely timeout; cell marked missing)"
    fi
}

for op_dir in data/processed/proof_blocks_combined_v10_per_op/*/; do
    [ -d "$op_dir" ] || continue
    op=$(basename "$op_dir")
    # combined_v10 per-op model (CLEAN: trained without this op's v10 cells)
    run_one "$op_dir" \
        "data/models/proof_block_seq2seq_combined_v10_per_op/$op" \
        "$OUT_ROOT/per_op/$op/combined_v10_per_op"
    # baseline_v8 re-evaluation on the same test set (the v8 model never saw
    # any v10 cell, so this is its honest zero-shot result on the same rows)
    run_one "$op_dir" \
        "data/models/proof_block_seq2seq_interpolation" \
        "$OUT_ROOT/per_op/$op/baseline_v8"
done

echo "ALL CLEAN PER-OP EVAL DONE"
