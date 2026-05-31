#!/usr/bin/env bash
# Evaluate v11 per-family models AND the v8/v9 per-family baselines on the
# SAME test sets (so v8 vs v11 is apples-to-apples). For each held family:
#   * v8/v9 model:  data/models/proof_block_seq2seq_family_holdout_<fam>
#   * v11 model:    data/models/proof_block_seq2seq_v11_family_<fam>
#   * baseline_v8:  data/models/proof_block_seq2seq_interpolation (broad,
#                   IN-DISTRIBUTION on these families — labelled as such)
#
# Test set is the v11 fold's test.jsonl, which is byte-identical to the v8
# family_holdout/<fam>/test.jsonl (verified by the build script).
set -uo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/bin/python
PER_FOLD_TIMEOUT="${PER_FOLD_TIMEOUT:-300}"
OUT_ROOT="data/baselines/v11_family_lofo_eval"

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
        --cache data/lean_cache/v11_seq2seq_cache.json
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "  -> exit $rc (likely timeout)"
    fi
}

for fold_dir in data/processed/proof_blocks_v11_family_lofo/*/; do
    [ -d "$fold_dir" ] || continue
    fam=$(basename "$fold_dir")
    # v11 (with v10 redundancy)
    run_one "$fold_dir" \
        "data/models/proof_block_seq2seq_v11_family_${fam}" \
        "$OUT_ROOT/${fam}/v11"
    # v8/v9 baseline (LOFO without v10 redundancy)
    run_one "$fold_dir" \
        "data/models/proof_block_seq2seq_family_holdout_${fam}" \
        "$OUT_ROOT/${fam}/v8_lofo"
    # broad interpolation baseline (IN-DISTRIBUTION on these families; for
    # context only — labelled as in-distribution in the docs)
    run_one "$fold_dir" \
        "data/models/proof_block_seq2seq_interpolation" \
        "$OUT_ROOT/${fam}/baseline_v8_indist"
done

echo "ALL V11 FAMILY-LOFO EVAL DONE"
