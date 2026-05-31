#!/usr/bin/env bash
# Run evaluate_proof_block_seq2seq.py per fold across family_holdout and
# operation_holdout. Skip folds whose metrics.json already exists.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/bin/python

run () {
  local regime="$1"; local model="$2"; local outdir="$3"
  if [ -f "$outdir/metrics.json" ]; then
    echo "SKIP $outdir"
    return
  fi
  if [ ! -f "$model/model.pt" ]; then
    echo "MISS_MODEL $model"
    return
  fi
  echo "EVAL $regime"
  timeout 900 $PY scripts/evaluate_proof_block_seq2seq.py \
    --regime-dir "$regime" --model-dir "$model" \
    --out-dir "$outdir" --top-k 10 || echo "TIMEOUT_OR_FAIL $regime"
}

for fam in neg_exfalso neg_imp_exfalso neg_double_intro neg_contrapositive \
           neg_or_cases exists_elim_conj exists_elim_prop exists_reconstruct \
           rewrite_succ ; do
  run "data/processed/proof_blocks_family_holdout/$fam" \
      "data/models/proof_block_seq2seq_family_holdout_$fam" \
      "data/baselines/v8_seq2seq_family_holdout_$fam"
done

for op in contradiction destruct_exists instantiate_forall intro_negation \
          project_conjunction rewrite ; do
  run "data/processed/proof_blocks_operation_holdout/$op" \
      "data/models/proof_block_seq2seq_operation_holdout_$op" \
      "data/baselines/v8_seq2seq_operation_holdout_$op"
done

# Also redo donorless_eval via the direct seq2seq evaluator (different cache,
# but its predictions.jsonl carries verifications which the v8 eval's
# back-fill enricher needs).
run "data/processed/proof_blocks_donorless_eval" \
    "data/models/proof_block_seq2seq_donorless_eval" \
    "data/baselines/v8_seq2seq_donorless_eval"

echo "v8 seq2seq eval loop done"
