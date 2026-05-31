#!/usr/bin/env bash
# Mini-ELF v10 — focused eval (faster subset of run_v10_eval_loop.sh).
#
# Skips redundancy_family_holdout (32 redundant folds with same signal as
# cell_holdout) and redundancy_low_shot, and samples ONE cell per operation
# from cell_holdout. Keeps:
#
#   * cell_holdout: 1 representative cell per operation × 3 models (24 runs)
#   * operation_holdout: all 8 × 3 models (24 runs)
#   * v8 negative controls: forall_inst + rewrite_succ × 3 models (6 runs)
#
# Per-fold timeout still applies. Cells the loop has already evaluated (per
# the v10 cache + metrics.json on disk) are skipped, so re-runs are cheap.

set -uo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/bin/python
PER_FOLD_TIMEOUT="${PER_FOLD_TIMEOUT:-240}"
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
        --top-k "${V10_TOPK:-10}" --beam-width "${V10_BEAM:-10}" \
        --verifier-timeout "${V10_VERIFIER_TIMEOUT:-20}" \
        --cache data/lean_cache/v10_seq2seq_cache.json
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "  -> exit $rc (likely timeout; cell marked missing in v10 matrix)"
    fi
}

declare -A MODELS=(
    [baseline_v8]="data/models/proof_block_seq2seq_interpolation"
    [redundancy_only]="data/models/proof_block_seq2seq_redundancy"
    [combined_v10]="data/models/proof_block_seq2seq_combined_v10"
)

# Representative cell per operation: hash-stable choice (first folder per op
# when sorted alphabetically). This keeps the cell choice deterministic across
# re-runs.
declare -a CELL_REPS=(
    "conjunction_projection__left_ab"
    "contradiction__exfalso_pq"
    "disjunction_cases__or_self"
    "exists_elim__reuse_witness_3"
    "implication_chain__two_step_abc"
    "instantiate_forall__nat_eq_3"
    "intro_negation__contrapos_ab"
    "rewrite_eq__mul_one"
)

echo "===== cell_holdout (1 cell per operation) ====="
for cell in "${CELL_REPS[@]}"; do
    cell_dir="data/processed/proof_blocks_redundancy_cell_holdout/$cell"
    [ -d "$cell_dir" ] || { echo "MISS_REGIME $cell_dir"; continue; }
    for tag in baseline_v8 redundancy_only combined_v10; do
        run_one "$cell_dir" "${MODELS[$tag]}" \
            "$OUT_ROOT/redundancy_cell_holdout/$cell/$tag"
    done
done

echo "===== operation_holdout (all 8) ====="
for op_dir in data/processed/proof_blocks_redundancy_operation_holdout/*/; do
    [ -d "$op_dir" ] || continue
    fold=$(basename "$op_dir")
    for tag in baseline_v8 redundancy_only combined_v10; do
        run_one "$op_dir" "${MODELS[$tag]}" \
            "$OUT_ROOT/redundancy_operation_holdout/$fold/$tag"
    done
done

echo "===== v8 negative controls (forall_inst, rewrite_succ) ====="
for fold_name in forall_inst rewrite_succ; do
    pb_dir="data/processed/proof_blocks_family_holdout/${fold_name}"
    [ -d "$pb_dir" ] || { echo "MISS_REGIME $pb_dir"; continue; }
    for tag in baseline_v8 redundancy_only combined_v10; do
        run_one "$pb_dir" "${MODELS[$tag]}" \
            "$OUT_ROOT/v8_negative_controls/family_holdout_${fold_name}/$tag"
    done
done

echo "===== v10 focused eval QUEUED COMPLETE ====="
