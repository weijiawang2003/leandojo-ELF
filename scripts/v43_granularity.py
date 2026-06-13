"""Mini-ELF v43 — C1 (granularity frontier) + B1 (per-token vs exact-seq across plan length).

One shared eval over arbitrary (label, family, snapshot, corpus) cells. For each dev row,
generate K samples; record per length-stratum L∈{1,2,3+}:
  - exact-seq pass@K (any sample == gold target, whitespace-normalized)
  - per-token accuracy (best sample's fraction of target positions equal to gold)
C1 reads the flow/AR exact-seq RATIO across granularities (head-only / coarse / full-typed).
B1 reads per-token (should stay high for flow) vs exact-seq (should fall with L) — the
joint-modeling signature.
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


def plan_len_bucket(target: str) -> str:
    n = len([s for s in target.split(";") if s.strip()]) if (";" in target or "(" in target) else len(target.split())
    return "1" if n <= 1 else ("2" if n == 2 else "3+")


def norm(s: str) -> str:
    return " ".join(s.split())


def token_acc(pred: str, gold: str) -> float:
    pt, gt = pred.split(), gold.split()
    if not gt:
        return 1.0 if not pt else 0.0
    m = sum(1 for i, g in enumerate(gt) if i < len(pt) and pt[i] == g)
    return m / len(gt)


@torch.no_grad()
def eval_cell(snap_path: str, family: str, corpus: Path, K: int, dev: str):
    vocab = TokenVocab.load(corpus / "vocab.json")
    rows = [json.loads(l) for l in (corpus / "dev.jsonl").read_text().splitlines() if l.strip()]
    snap = torch.load(snap_path, map_location="cpu", weights_only=False)
    cfg = V38Config.from_dict(snap["cfg"])
    model = build_model(family, cfg, **(snap.get("family_kw") or {})).to(dev)
    model.load_state_dict({k: v.to(dev) for k, v in snap["state_dict"].items()})
    model.eval()
    buckets = ("1", "2", "3+")
    ex_hit = {b: 0 for b in buckets}
    tok_sum = {b: 0.0 for b in buckets}
    tot = {b: 0 for b in buckets}
    kw = {"cfg_weight": 2.0, "self_cond": True} if family == "flow" else {}
    for r in rows:
        gold = norm(r["tactic"])
        b = plan_len_bucket(r["tactic"])
        cids = (r.get("cond_ids") or vocab.encode_source(r["theorem_statement"]))[:cfg.max_cond_len]
        cids = cids + [cfg.pad_id] * (cfg.max_cond_len - len(cids))
        cond = torch.tensor([cids], dtype=torch.long, device=dev)
        ids = model.generate(cond, n_samples=K, steps=GEN_STEPS[family],
                             prompt=r["theorem_name"], device=dev, **kw)
        preds = [norm(vocab.decode_target(ids[k].tolist())) for k in range(ids.size(0))]
        tot[b] += 1
        if any(p == gold for p in preds):
            ex_hit[b] += 1
        tok_sum[b] += max(token_acc(p, gold) for p in preds)
    exact = {b: (ex_hit[b] / tot[b] if tot[b] else None) for b in buckets}
    perok = {b: (tok_sum[b] / tot[b] if tot[b] else None) for b in buckets}
    return {"exact_seq": exact, "per_token": perok, "n": tot}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", nargs="+", required=True, help="label=family=snapshot=corpus quads")
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    out = {"git_sha": sha, "K": args.k, "device": dev, "cells": {}}
    for spec in args.cells:
        label, family, snap, corpus = spec.split("=")
        res = eval_cell(snap, family, Path(corpus), args.k, dev)
        out["cells"][label] = {"family": family, "corpus": corpus, **res}
        print(label, "exact", res["exact_seq"], "pertok", {k: round(v, 3) if v is not None else None for k, v in res["per_token"].items()})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print("->", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
