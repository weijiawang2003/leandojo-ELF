#!/usr/bin/env bash
# Mini-ELF v10 — evaluation loop across (model × regime) pairs.
#
# Reuses scripts/evaluate_proof_block_seq2seq.py to compute lean-cli pass@k on
# the v10 redundancy regimes plus key v8/v9 cells. Per-fold runs are wrapped in
# a timeout so a single misbehaving fold does not stall the matrix.
#
# Honest reporting contract (inherited from the v8 eval loop):
#   * a fold's metrics.json appears only if the evaluation completed
#   * scripts/build_v10_full_matrix.py reports missing folds as `—`, never as 0
#   * negative-control cells are evaluated identically to the positive cells

set -uo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/bin/python
PER_FOLD_TIMEOUT="${PER_FOLD_TIMEOUT:-300}"   # seconds per evaluate_* run
OUT_ROOT="data/baselines/v10_eval"

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
        --cache data/lean_cache/v10_seq2seq_cache.json
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "  -> exit $rc (likely timeout; cell marked missing in v10 matrix)"
    fi
}

# Models to evaluate (the three v10 brief deliverables)
declare -A MODELS=(
    [baseline_v8]="data/models/proof_block_seq2seq_interpolation"
    [redundancy_only]="data/models/proof_block_seq2seq_redundancy"
    [combined_v10]="data/models/proof_block_seq2seq_combined_v10"
)

# Regimes — held-out cells where redundancy is hypothesized to help
echo "===== v10 cell_holdout (model × held cell) ====="
for cell_dir in data/processed/proof_blocks_redundancy_cell_holdout/*/; do
    [ -d "$cell_dir" ] || continue
    fold=$(basename "$cell_dir")
    for tag in baseline_v8 redundancy_only combined_v10; do
        run_one "$cell_dir" "${MODELS[$tag]}" \
            "$OUT_ROOT/redundancy_cell_holdout/$fold/$tag"
    done
done

echo "===== v10 operation_holdout (model × held op) ====="
for op_dir in data/processed/proof_blocks_redundancy_operation_holdout/*/; do
    [ -d "$op_dir" ] || continue
    fold=$(basename "$op_dir")
    for tag in baseline_v8 redundancy_only combined_v10; do
        run_one "$op_dir" "${MODELS[$tag]}" \
            "$OUT_ROOT/redundancy_operation_holdout/$fold/$tag"
    done
done

echo "===== v10 family_holdout (model × held surface family) ====="
for fam_dir in data/processed/proof_blocks_redundancy_family_holdout/*/; do
    [ -d "$fam_dir" ] || continue
    fold=$(basename "$fam_dir")
    for tag in baseline_v8 redundancy_only combined_v10; do
        run_one "$fam_dir" "${MODELS[$tag]}" \
            "$OUT_ROOT/redundancy_family_holdout/$fold/$tag"
    done
done

echo "===== v10 low_shot (model × k) ====="
for k_dir in data/processed/proof_blocks_redundancy_low_shot/*/; do
    [ -d "$k_dir" ] || continue
    fold=$(basename "$k_dir")
    for tag in baseline_v8 redundancy_only combined_v10; do
        run_one "$k_dir" "${MODELS[$tag]}" \
            "$OUT_ROOT/redundancy_low_shot/$fold/$tag"
    done
done

# v8 forall_inst / rewrite_succ negative controls — test if redundancy unblocks
# the cells that stayed at 0/n in v8/v9.
echo "===== v10 cross-eval on v8 negative-control cells ====="
for fold in planner_blind_family_holdout/forall_inst \
            planner_blind_family_holdout/rewrite_succ; do
    pb_dir="data/processed/proof_blocks_$fold"
    [ -d "$pb_dir" ] || { echo "MISS_REGIME $pb_dir"; continue; }
    fold_name=$(echo "$fold" | tr / _)
    for tag in baseline_v8 redundancy_only combined_v10; do
        run_one "$pb_dir" "${MODELS[$tag]}" \
            "$OUT_ROOT/v8_negative_controls/$fold_name/$tag"
    done
done

# Donorless eval — the strictest v7/v8 condition
echo "===== v10 cross-eval on donorless_eval ====="
pb_dir="data/processed/proof_blocks_donorless_eval"
if [ -d "$pb_dir" ]; then
    for tag in baseline_v8 redundancy_only combined_v10; do
        run_one "$pb_dir" "${MODELS[$tag]}" \
            "$OUT_ROOT/donorless_eval/$tag"
    done
fi

echo "ALL V10 EVAL CELLS QUEUED"
