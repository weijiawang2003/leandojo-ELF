#!/usr/bin/env bash
# Build the hard-corpus processed datasets under every v2 split strategy, plus a
# combined (basic+hard) dataset. Re-runnable; no Lean (operates on collected
# traces). Run after scripts/generate_hard_corpus.py + collect_traces.py.
set -euo pipefail
cd "$HOME/code/ELFMath"
PY=./.venv/bin/python
HARD_VERIFIED=data/traces/hard_lean_cli_verified.jsonl
HARD_SEEDS=data/seeds/hard_lean_seeds.jsonl
BASIC_SEEDS=data/seeds/basic_lean_seeds.jsonl
BASIC_VERIFIED=data/traces/basic_lean_cli_verified.jsonl

# Hard corpus under each split strategy (hash also written to the unsuffixed dir).
"$PY" scripts/build_dataset.py --input "$HARD_VERIFIED" --output-dir data/processed/hard_lean_cli \
  --backend lean-cli --seeds "$HARD_SEEDS" --corpus-source hard --split-strategy hash > /tmp/build_hard_hash.log
for strat in hash family_holdout difficulty_holdout adversarial_sibling; do
  "$PY" scripts/build_dataset.py --input "$HARD_VERIFIED" \
    --output-dir "data/processed/hard_lean_cli_${strat}" \
    --backend lean-cli --seeds "$HARD_SEEDS" --corpus-source hard --split-strategy "$strat" \
    > "/tmp/build_hard_${strat}.log"
  echo "built hard_lean_cli_${strat}"
done

# Combined basic+hard for v2 training, under each strategy (leakage-free eval
# per strategy). corpus_source/difficulty/pattern_family tag each row.
for strat in hash difficulty_holdout adversarial_sibling family_holdout; do
  suffix=""
  if [ "$strat" != "hash" ]; then suffix="_${strat}"; fi
  "$PY" scripts/build_combined.py --output-dir "data/processed/combined_lean_cli${suffix}" \
    --split-strategy "$strat" > "/tmp/build_combined_${strat}.log"
  echo "built combined_lean_cli${suffix}"
done

# Merged seeds (basic + hard) so a single --seeds covers combined test sets.
cat "$BASIC_SEEDS" "$HARD_SEEDS" > data/seeds/combined_lean_seeds.jsonl
echo "wrote data/seeds/combined_lean_seeds.jsonl"
echo "ALL BUILT"
