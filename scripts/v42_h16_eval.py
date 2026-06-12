"""Mini-ELF v42 — H16: plan exact-seq stratified by plan length, one shared eval.

Re-computes the v41-H14 metric with ONE code path for both plan representations
(head-only `simp exact` vs typed `simp ( LEMMA ) ; exact ( TERM )`), so the
flow/AR ratio per length stratum is internally comparable. Pass@K exact-sequence:
a dev row counts as hit if ANY of K samples decodes to exactly the gold target
(whitespace-normalized). Strata by GOLD plan length L ∈ {1, 2, 3+} (typed: number
of ';'-separated steps; head-only: number of head tokens).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    sys.path.insert(0, p)

import torch

from mini_elf_lean.v38_backbone import V38Config
from mini_elf_lean.token_seq2seq_dataset import TokenVocab
from v38_matrix_eval import build_model

GEN_STEPS = {"flow": 1, "ar": 1, "mdlm": 16}


def plan_len(target: str) -> str:
    if ";" in target or "(" in target:  # typed representation
        n = len([s for s in target.split(";") if s.strip()])
    else:  # head-only: one token per step
        n = len(target.split())
    return "1" if n <= 1 else ("2" if n == 2 else "3+")


def norm(s: str) -> str:
    return " ".join(s.split())


@torch.no_grad()
def eval_model(snap_path: str, family: str, corpus: Path, K: int, dev_device: str):
    vocab = TokenVocab.load(corpus / "vocab.json")
    rows = [json.loads(l) for l in (corpus / "dev.jsonl").read_text().splitlines() if l.strip()]
    snap = torch.load(snap_path, map_location="cpu", weights_only=False)
    cfg = V38Config.from_dict(snap["cfg"])
    model = build_model(family, cfg, **(snap.get("family_kw") or {})).to(dev_device)
    model.load_state_dict({k: v.to(dev_device) for k, v in snap["state_dict"].items()})
    model.eval()
    hits, totals = {"1": 0, "2": 0, "3+": 0}, {"1": 0, "2": 0, "3+": 0}
    kw = {"cfg_weight": 2.0, "self_cond": True} if family == "flow" else {}
    for r in rows:
        gold = norm(r["tactic"])
        stratum = plan_len(r["tactic"])
        cids = (r.get("cond_ids") or vocab.encode_source(r["theorem_statement"]))[:cfg.max_cond_len]
        cids = cids + [cfg.pad_id] * (cfg.max_cond_len - len(cids))
        cond = torch.tensor([cids], dtype=torch.long, device=dev_device)
        ids = model.generate(cond, n_samples=K, steps=GEN_STEPS[family],
                             prompt=r["theorem_name"], device=dev_device, **kw)
        hit = any(norm(vocab.decode_target(ids[k].tolist())) == gold for k in range(ids.size(0)))
        totals[stratum] += 1
        hits[stratum] += hit
    return {s: (hits[s] / totals[s] if totals[s] else None) for s in totals}, totals


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", nargs="+", required=True,
                    help="label=family=snapshot=corpus_dir quads")
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--out", default=str(ROOT / "outputs/v42/h16_stratified.json"))
    args = ap.parse_args()
    dev_device = "cuda" if torch.cuda.is_available() else "cpu"

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    out = {"git_sha": sha, "K": args.k, "device": dev_device, "cells": {}}
    for spec in args.cells:
        label, family, snap, corpus = spec.split("=")
        rates, totals = eval_model(snap, family, Path(corpus), args.k, dev_device)
        out["cells"][label] = {"family": family, "snapshot": snap, "corpus": corpus,
                               "exact_seq": rates, "n": totals}
        print(label, rates, totals)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print("->", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
