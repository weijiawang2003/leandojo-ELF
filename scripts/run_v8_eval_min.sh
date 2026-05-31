#!/usr/bin/env bash
# Mini-ELF v8 — minimum-sufficient eval matrix.
# Designed to finish in ~90 min on CPU with lean-cli verification.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=./.venv/bin/python

run () {
  local regime="$1"; local config="$2"
  local out="data/baselines/v8_eval/$regime/$config/metrics.json"
  if [ -f "$out" ]; then
    echo "SKIP $regime :: $config (metrics.json exists)"
    return
  fi
  echo "==== $regime :: $config ===="
  $PY scripts/evaluate_mini_elf_v8.py --regime "$regime" --config "$config" --top-k 10 || true
}

# ---- 1) Headline donorless: seq2seq vs retrieval vs fusion ----
run donorless_eval         seq2seq_only
run donorless_eval         retrieval_only
run donorless_eval         retrieval_seq2seq
run donorless_eval         full_fusion

# ---- 2) Interpolation upper bound ----
run current                seq2seq_only
run current                retrieval_only

# ---- 3) family_holdout pooled (10 folds × 2 configs) ----
for fam in neg_exfalso neg_imp_exfalso neg_double_intro neg_contrapositive \
           neg_or_cases exists_elim_conj exists_elim_prop exists_reconstruct \
           forall_inst rewrite_succ ; do
  run "family_holdout/$fam" seq2seq_only
  run "family_holdout/$fam" retrieval_only
done

# ---- 4) operation_holdout pooled (6 ops × seq2seq + retrieval) ----
for op in contradiction destruct_exists instantiate_forall intro_negation \
          project_conjunction rewrite ; do
  run "operation_holdout/$op" seq2seq_only
  run "operation_holdout/$op" retrieval_only
done

echo "v8 eval matrix complete"
