#!/usr/bin/env bash
# Mini-ELF v8 Part 6 — sweep the eval matrix.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=./.venv/bin/python

run () {
  local regime="$1"; local config="$2"
  echo "==== $regime :: $config ===="
  $PY scripts/evaluate_mini_elf_v8.py --regime "$regime" --config "$config" || true
}

# 1) seq2seq-only on each main split (the headline donorless number)
run donorless_eval     seq2seq_only
run current            seq2seq_only

# 2) v7 retrieval baseline on each main split
for regime in current donorless_eval ; do
  run "$regime" retrieval_only
done

# 3) family_holdout pooled (one per held family)
for fam in neg_exfalso neg_imp_exfalso neg_double_intro neg_contrapositive \
           neg_or_cases exists_elim_conj exists_elim_prop exists_reconstruct \
           forall_inst rewrite_succ ; do
  run "family_holdout/$fam" seq2seq_only
  run "family_holdout/$fam" retrieval_only
  run "family_holdout/$fam" retrieval_seq2seq
done

# 4) operation_holdout pooled
for op in contradiction destruct_exists instantiate_forall intro_negation \
          project_conjunction rewrite ; do
  run "operation_holdout/$op" seq2seq_only
  run "operation_holdout/$op" retrieval_only
  run "operation_holdout/$op" retrieval_seq2seq
done

# 5) Full fusion on donorless_eval and current
for regime in donorless_eval current ; do
  run "$regime" full_fusion
done

# 6) kshot + literal_holdout (mostly for the gradient table)
for regime in kshot_0 kshot_1 kshot_2 literal_holdout ; do
  run "$regime" retrieval_only
  run "$regime" seq2seq_only
  run "$regime" retrieval_seq2seq
done

echo "v8 eval matrix complete"
