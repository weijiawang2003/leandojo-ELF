#!/usr/bin/env bash
# Mini-ELF v12 — runner for evaluate_v12_literal_rerank.py + summarize_v12.py.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/bin/python

"$PY" scripts/evaluate_v12_literal_rerank.py \
    --verifier-timeout "${V12_VERIFIER_TIMEOUT:-20}"

"$PY" scripts/summarize_v12.py
