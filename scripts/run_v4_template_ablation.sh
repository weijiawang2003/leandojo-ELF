#!/usr/bin/env bash
# V4 Part 5: controlled template-addition ablation. Add the OPTIONAL, explicitly
# -labelled planner template families (planner_negation / planner_exists_elim,
# from proof_planner_v4.py) on top of the unchanged v3 system and measure the
# *marginal* recovery on the planner-blind corpus. These templates are NOT folded
# into v3 — they are a measurement of engineered symbolic coverage.
#   wsl -d Ubuntu -- bash -lc 'bash "$HOME/code/ELFMath/scripts/run_v4_template_ablation.sh"'
set -euo pipefail
cd "$HOME/code/ELFMath"
export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
PY=./.venv/bin/python
DS=data/processed/planner_blind_lean_cli/next_tactic.jsonl
SEEDS=data/seeds/planner_blind_seeds.jsonl
MODEL=data/models/combined_lean_cli_mini_elf_v2

seed_cache() {
  local target="$1"; mkdir -p "$target"
  "$PY" - "$target/verification_cache.json" <<'PYEOF'
import glob, json, sys
merged = {}
for f in glob.glob("data/baselines/*/verification_cache.json") + ["/tmp/blind_probe_cache.json"]:
    try: merged.update(json.load(open(f)))
    except Exception: pass
json.dump(merged, open(sys.argv[1], "w"), indent=2, sort_keys=True)
PYEOF
}

ablate() {  # out_suffix extra_flags...
  local suffix="$1"; shift
  local out="data/baselines/planner_blind_${suffix}"
  echo "=== ABLATION $suffix ($*) ==="; seed_cache "$out"
  "$PY" scripts/evaluate_mini_elf_v3.py --model-dir "$MODEL" \
    --dataset "$DS" --output-dir "$out" --split test --top-k 5 --n-samples 64 --flow-steps 10 \
    --verify-with-lean-cli --cache --seeds "$SEEDS" "$@" > "/tmp/ablate_${suffix}.log" 2>&1
  echo "done $suffix"
}

ablate v4_template_negation_test    --enable-negation-templates
ablate v4_template_exists_test       --enable-exists-elim-templates
ablate v4_template_both_test         --enable-negation-templates --enable-exists-elim-templates
echo "ALL DONE"
