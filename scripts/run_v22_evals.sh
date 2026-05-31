#!/usr/bin/env bash
# Mini-ELF v22 — Part 5: evaluate every v22 single general model on the
# v18 broad-core benchmark, then run the Part-6 interference analysis and
# refresh the routing audit.
#
# Uses the PINNED toolchain lean binary (NOT the elan `lean` shim, which
# intermittently hangs under sustained sequential verification — see
# docs/V22_REPO_STATUS.md). Reuses the shared warm lean cache, so only
# genuinely-new candidates are verified. Sequential (cache is a single
# JSON file; parallel runs would race on save()).
set -euo pipefail
cd "$(dirname "$0")/.."

LEANBIN="${MINI_ELF_LEAN_COMMAND:-/home/wangw/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean}"
export MINI_ELF_LEAN_COMMAND="$LEANBIN"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-8}"
PY=.venv/bin/python

# config_name  pattern_bag_pool
CONFIGS=(
  "v22_general_plus_exists:A_mixed"
  "v22_general_balanced:B_oversample"
  "v22_general_large:A_mixed"
  "v22_general_balanced_large:B_oversample"
)

# Optionally wait for models still training (pipelines evals with Part 4).
# WAIT_MODELS=0 disables; default waits up to ~30 min per model.
WAIT_SECS="${WAIT_SECS:-1800}"

for entry in "${CONFIGS[@]}"; do
  name="${entry%%:*}"
  pool="${entry##*:}"
  model="data/models/${name}"
  bag="data/processed/v22_balanced_broad/${pool}/train_rows.jsonl"
  out="data/baselines/${name}_eval"
  waited=0
  while [[ ! -f "${model}/model.pt" && "${WAIT_MODELS:-1}" != "0" && $waited -lt $WAIT_SECS ]]; do
    sleep 15; waited=$((waited+15))
  done
  if [[ ! -f "${model}/model.pt" ]]; then
    echo "SKIP ${name}: model not trained (waited ${waited}s)"
    continue
  fi
  echo "=== eval ${name} (bag=${pool}) ==="
  "$PY" scripts/evaluate_v21_broad_core.py \
    --model-root "$model" \
    --pattern-bag-rows "$bag" \
    --out-root "$out" \
    --verifier-timeout 20 > "${out}_stdout.log" 2>&1
  grep -E "pass@1=|DONE" "${out}_stdout.log" | tail -7
done

echo "=== Part 6: category-interference analysis ==="
"$PY" scripts/analyze_v22_category_interference.py
echo "=== refresh routing audit (Part 1, includes nothing new but re-asserts) ==="
"$PY" scripts/audit_v22_routing_vs_single.py >/dev/null 2>&1 || true
echo "ALL_V22_EVALS_DONE"
