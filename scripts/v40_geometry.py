"""Mini-ELF v40 — Phase 4: embedding-geometry probe (H9).

Trains ONE flow with unit-norm frozen embeddings (max-separation geometry: rows on the
unit sphere -> tied readout is a pure cosine, ||E||² constant, cleaner 1-step snap) at the
SAME budget/seed/corpus as the Phase-2 scratch flow. Compares dev exact-seq (1-step).
H9 criterion: unit-norm/scratch dev-exact ratio >= 1.5.

(Fallback (b) per the brief: pretrained-embedding download not attempted — this directly
tests the geometry mechanism without tokenizer-integration risk.)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    sys.path.insert(0, p)

import torch
from v39_grid import load_corpus
from v39_train import train_cell


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-dir", default=str(ROOT / "data/v40/corpora/wholeproof"))
    ap.add_argument("--budget", type=float, default=1.5e8)
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--scale", default="30M")
    ap.add_argument("--scratch-metrics", default=str(ROOT / "outputs/v40/wholeproof/matrix_metrics.jsonl"))
    args = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    out = ROOT / "outputs/v40/geometry"

    vocab, man, train_rows, dev_rows, golds, _, _ = load_corpus(args.corpus_dir)
    res = train_cell(family="flow", scale=args.scale, train_rows=train_rows, val_rows=dev_rows,
                     dev_rows=dev_rows, vocab=vocab, manifest=man, golds=golds,
                     token_budget=args.budget, ckpt_fracs=[1.0], batch_size=args.batch_size,
                     base_lr=3e-4, seed=3407, device=dev, cell_id="geom_flow_unitnorm",
                     out_dir=out, dev_n=len(dev_rows), K_dev=4, gen_steps=16,
                     family_kw={"unit_norm_emb": True}, time_cap_s=2400,
                     extra_meta={"phase": "P4_geometry", "geometry": "unit_norm_frozen"})
    unit_ex = res["final"]["dev_exact_seq"]; unit_pt = res["final"]["dev_per_token"]

    # scratch control = Phase-2 flow (default-init frozen emb, same budget)
    scratch_ex = scratch_pt = None
    for l in Path(args.scratch_metrics).read_text().splitlines():
        r = json.loads(l)
        if r.get("family") == "flow" and r.get("frac") == 1.0:
            scratch_ex, scratch_pt = r["dev_exact_seq"], r["dev_per_token"]
    ratio = (unit_ex / scratch_ex) if (scratch_ex and scratch_ex > 0) else float("inf") if unit_ex > 0 else 0.0
    verdict = "SUPPORTED" if (scratch_ex and ratio >= 1.5) else "REFUTED"
    result = {"unit_norm_dev_exact": unit_ex, "unit_norm_dev_pertok": unit_pt,
              "scratch_dev_exact": scratch_ex, "scratch_dev_pertok": scratch_pt,
              "ratio_unit_over_scratch": ratio, "H9_criterion": ">=1.5x", "H9_verdict": verdict,
              "geometry": "unit_norm_frozen vs scratch_default_init", "budget": args.budget}
    (out / "h9_geometry.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
