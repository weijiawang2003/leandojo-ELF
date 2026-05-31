#!/usr/bin/env bash
# Mini-ELF v10 follow-up — evaluate the 8 newly-verified redundancy cells.
#
# After re-running scripts/generate_redundancy_corpus.py with --timeout 180
# all 40 design cells verified. 8 of those are NEW (were previously refused
# under cold-start timeouts):
#   * contradiction:        arrow_false, exfalso_with_extra
#   * exists_elim:          reuse_witness_5
#   * implication_chain:    two_step_pqr
#   * instantiate_forall:   nat_add_zero_4, prop_self_imp
#   * rewrite_eq:           swap_under_z
#   * disjunction_cases:    or_with_false
#
# These cells did not exist in any prior model's train pool (the prior models
# were trained on the 32-cell corpus, which excluded all 8). So their
# cell_holdout test rows are truly held-out for every v10 model. We eval all
# three on each of the 8 new cells: 24 runs total.

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
        --top-k 10 --beam-width 10 \
        --verifier-timeout 20 \
        --cache data/lean_cache/v10_seq2seq_cache.json
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "  -> exit $rc (likely timeout)"
    fi
}

declare -A MODELS=(
    [baseline_v8]="data/models/proof_block_seq2seq_interpolation"
    [redundancy_only]="data/models/proof_block_seq2seq_redundancy"
    [combined_v10]="data/models/proof_block_seq2seq_combined_v10"
)

declare -a NEW_CELLS=(
    "contradiction__arrow_false"
    "contradiction__exfalso_with_extra"
    "disjunction_cases__or_with_false"
    "exists_elim__reuse_witness_5"
    "implication_chain__two_step_pqr"
    "instantiate_forall__nat_add_zero_4"
    "instantiate_forall__prop_self_imp"
    "rewrite_eq__swap_under_z"
)

echo "===== v10 follow-up: 8 newly-verified cells × 3 models ====="
for cell in "${NEW_CELLS[@]}"; do
    cell_dir="data/processed/proof_blocks_redundancy_cell_holdout/$cell"
    [ -d "$cell_dir" ] || { echo "MISS_REGIME $cell_dir"; continue; }
    for tag in baseline_v8 redundancy_only combined_v10; do
        run_one "$cell_dir" "${MODELS[$tag]}" \
            "$OUT_ROOT/redundancy_cell_holdout/$cell/$tag"
    done
done

echo "===== donorless_eval × 3 models ====="
pb_dir="data/processed/proof_blocks_donorless_eval"
if [ -d "$pb_dir" ]; then
    for tag in baseline_v8 redundancy_only combined_v10; do
        run_one "$pb_dir" "${MODELS[$tag]}" \
            "$OUT_ROOT/donorless_eval/$tag"
    done
else
    echo "MISS_REGIME $pb_dir"
fi

echo "===== v10 follow-up DONE ====="
