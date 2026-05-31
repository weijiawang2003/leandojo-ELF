#!/usr/bin/env bash
# Mini-ELF v8 Part 3 — train the seq2seq proposer across all four regimes.
# Sequential CPU training; ~5min per fold at 25 epochs.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=./.venv/bin/python
EP=${EP:-25}

mkdir -p data/models

train_one () {
  local regime_dir="$1"
  local out_dir="$2"
  if [ -f "$out_dir/model.pt" ]; then
    echo "SKIP $out_dir (model.pt exists)"
    return
  fi
  echo "TRAIN $regime_dir -> $out_dir"
  $PY scripts/train_proof_block_seq2seq.py \
      --regime-dir "$regime_dir" \
      --out-dir   "$out_dir" \
      --epochs "$EP" --seed 0 \
      2>&1 | tail -3
}

# donorless_eval — the main v8 benchmark
train_one data/processed/proof_blocks_donorless_eval \
          data/models/proof_block_seq2seq_donorless_eval

# family_holdout — one model per held planner-blind family
for fam in neg_exfalso neg_imp_exfalso neg_double_intro neg_contrapositive \
           neg_or_cases exists_elim_conj exists_elim_prop exists_reconstruct \
           forall_inst rewrite_succ ; do
  train_one "data/processed/proof_blocks_family_holdout/$fam" \
            "data/models/proof_block_seq2seq_family_holdout_$fam"
done

# operation_holdout — one model per observed required_operation
for op in contradiction destruct_exists instantiate_forall intro_negation \
          project_conjunction rewrite ; do
  train_one "data/processed/proof_blocks_operation_holdout/$op" \
            "data/models/proof_block_seq2seq_operation_holdout_$op"
done

echo "all v8 seq2seq models trained"
