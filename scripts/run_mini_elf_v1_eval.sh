#!/usr/bin/env bash
# Train Mini-ELF v1 and evaluate it with real lean-cli pass@k on val + test, in
# three modes (decoder-only / +reranker / +reranker+witness) plus the nn
# retrieval ablation. Uses the concrete toolchain binary to avoid the WSL2
# elan-shim stall, and pre-seeds each eval's verification cache from existing
# baseline caches so shared tactics are not re-verified.
#   wsl -d Ubuntu -- bash -lc 'bash "$HOME/code/ELFMath/scripts/run_mini_elf_v1_eval.sh"'
set -euo pipefail

cd "$HOME/code/ELFMath"
export MINI_ELF_LEAN_COMMAND="$HOME/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
PY=./.venv/bin/python
DATASET=data/processed/basic_lean_cli/next_tactic.jsonl
SPLITS=data/processed/basic_lean_cli/theorem_splits.json
SEEDS=data/seeds/basic_lean_seeds.jsonl
MODEL=data/models/basic_lean_cli_mini_elf_v1
NSAMP=64
STEPS=10

echo "lean: $("$MINI_ELF_LEAN_COMMAND" --version 2>&1 | head -1)"

# ---- 1. train v1 (generator + reranker) ----
if [ "${SKIP_TRAIN:-0}" != "1" ]; then
  echo "=== TRAIN Mini-ELF v1 ==="
  "$PY" scripts/train_mini_elf_v1.py \
    --dataset "$DATASET" --output-dir "$MODEL" \
    --verified-traces data/traces/basic_lean_cli_verified.jsonl \
    --failed-traces data/traces/basic_lean_cli_failed.jsonl \
    --splits "$SPLITS" --seeds "$SEEDS" \
    --ae-epochs 80 --flow-epochs 400 --rerank-epochs 80 \
    --ae-denoise-prob 0.1 --ae-latent-noise-std 0.1 \
    --self-train-rerank --self-train-max 12 \
    --latent-dim 64 --cond-dim 128 --n-samples "$NSAMP" --flow-steps "$STEPS" --seed 0 -v
fi

seed_cache() {  # merge all existing baseline caches into $1/verification_cache.json
  local target="$1"
  mkdir -p "$target"
  "$PY" - "$target/verification_cache.json" <<'PYEOF'
import glob, json, sys
out = sys.argv[1]
merged = {}
for f in glob.glob("data/baselines/*/verification_cache.json"):
    try:
        merged.update(json.load(open(f)))
    except Exception:
        pass
json.dump(merged, open(out, "w"), indent=2, sort_keys=True)
print(f"  seeded cache: {len(merged)} entries -> {out}")
PYEOF
}

run_eval() {  # mode_name dir_suffix split
  local mode="$1" suffix="$2" split="$3"
  local out="data/baselines/basic_lean_cli_mini_elf_v1_${suffix}_${split}"
  echo "=== EVAL mode=$mode split=$split -> $out ==="
  seed_cache "$out"
  "$PY" scripts/evaluate_mini_elf_v1.py \
    --model-dir "$MODEL" --dataset "$DATASET" --output-dir "$out" \
    --split "$split" --mode "$mode" --top-k 5 --n-samples "$NSAMP" --flow-steps "$STEPS" \
    --verify-with-lean-cli --cache --seeds "$SEEDS" \
    > "/tmp/mini_elf_v1_${suffix}_${split}.log" 2>&1
  echo "done mode=$mode split=$split"
}

# ---- 2-4. three generative modes, val + test ----
for split in val test; do
  run_eval decoder_no_rerank       decoder        "$split"
  run_eval decoder_rerank          rerank         "$split"
  run_eval decoder_rerank_witness  rerank_witness "$split"
done

# ---- 5. nn retrieval ablation (optional) ----
if [ "${RUN_NN:-1}" = "1" ]; then
  for split in val test; do
    run_eval nn_ablation nn "$split"
  done
fi

# ---- 6. compact comparison table ----
echo
echo "=== Mini-ELF v1 comparison (lean-cli pass@k) ==="
"$PY" - <<'PYEOF'
import json, os
def m(path):
    try:
        return json.load(open(path))
    except Exception:
        return None
def pk(d, k):
    try:
        return d["lean_verification"]["pass_at_k"][str(k)]["rate"]
    except Exception:
        return float("nan")
rows = []
configs = [
    ("AR seq2seq", "data/baselines/basic_lean_cli_ar_{s}"),
    ("v0 decoder", "data/baselines/basic_lean_cli_mini_elf_{s}"),
    ("v0 nn", "data/baselines/basic_lean_cli_mini_elf_{s}_nn"),
    ("v1 decoder", "data/baselines/basic_lean_cli_mini_elf_v1_decoder_{s}"),
    ("v1 rerank", "data/baselines/basic_lean_cli_mini_elf_v1_rerank_{s}"),
    ("v1 rerank+witness", "data/baselines/basic_lean_cli_mini_elf_v1_rerank_witness_{s}"),
    ("v1 nn", "data/baselines/basic_lean_cli_mini_elf_v1_nn_{s}"),
]
print(f"{'model':22s} {'split':5s} {'p@1':>5s} {'p@3':>5s} {'p@5':>5s} {'inv@1':>6s} {'novelV':>7s}")
for name, tmpl in configs:
    for s in ("val", "test"):
        d = m(os.path.join(tmpl.format(s=s), "metrics.json"))
        if not d:
            continue
        g = d.get("elf_v1_generation") or d.get("elf_generation") or {}
        inv = g.get("invalid_rate_top1", g.get("candidate_invalid_rate", float("nan")))
        nv = g.get("novel_candidates_verified", "-")
        print(f"{name:22s} {s:5s} {pk(d,1):5.2f} {pk(d,3):5.2f} {pk(d,5):5.2f} {inv:6.2f} {str(nv):>7s}")
PYEOF
echo "ALL DONE"
