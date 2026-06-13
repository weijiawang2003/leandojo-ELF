"""Mini-ELF v44 — premise-conditioning control (disambiguates the S2 small gap).

On the premcond corpus DEV split (in-distribution), generate under {none, gold} premise
conditioning and measure exact-seq match to the gold proof (NO Lean — just string match). If
gold >> none here, the model DID learn to use premises, so a small (gold-none) gap on the HARD
tier is a real generation-bound result. If gold ~= none here too, the model never learned to
condition on premises (a confound that would void the S2 interpretation).
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

from mini_elf_lean.v38_backbone import V38Config
from mini_elf_lean.token_seq2seq_dataset import TokenVocab
from v38_matrix_eval import build_model

MAX_PREM = 12
GEN_STEPS = {"ar": 1, "mdlm": 16, "flow": 1}


def cond_text(premises, stmt):
    return f"PREM: {' '.join(premises[:MAX_PREM]) if premises else ''} STMT: {stmt}"


def norm(s):
    return " ".join(s.split())


@torch.no_grad()
def arm(model, cfg, vocab, rows, dev, family, use_gold, K):
    hit = 0
    kw = {"cfg_weight": 2.0, "self_cond": True} if family == "flow" else {}
    for r in rows:
        prem = r.get("premises", []) if use_gold else []
        cids = vocab.encode_source(cond_text(prem, r["theorem_statement"]))[:cfg.max_cond_len]
        cids = cids + [cfg.pad_id] * (cfg.max_cond_len - len(cids))
        cond = torch.tensor([cids], dtype=torch.long, device=dev)
        ids = model.generate(cond, n_samples=K, steps=GEN_STEPS[family], prompt=r["theorem_name"], device=dev, **kw)
        gold = norm(r["tactic"])
        if any(norm(vocab.decode_target(ids[k].tolist())) == gold for k in range(ids.size(0))):
            hit += 1
    return hit / max(len(rows), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(ROOT / "data/v44/corpora/premcond"))
    ap.add_argument("--sources", required=True, help="label:family:snapshot comma list")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--out", default=str(ROOT / "outputs/v44/oracle/cond_control.json"))
    args = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    vocab = TokenVocab.load(Path(args.corpus) / "vocab.json")
    rows = [json.loads(l) for l in (Path(args.corpus) / "dev.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r.get("premises")][:args.n]  # rows WITH premises (where gold can help)
    print(f"control rows (dev, with premises): {len(rows)}")

    out = {"n": len(rows), "k": args.k, "cells": {}}
    for spec in args.sources.split(","):
        label, family, snap = spec.split(":")
        s = torch.load(snap, map_location="cpu", weights_only=False)
        cfg = V38Config.from_dict(s["cfg"])
        m = build_model(family, cfg, **(s.get("family_kw") or {})).to(dev)
        m.load_state_dict({k: v.to(dev) for k, v in s["state_dict"].items()}); m.eval()
        none = arm(m, cfg, vocab, rows, dev, family, False, args.k)
        gold = arm(m, cfg, vocab, rows, dev, family, True, args.k)
        out["cells"][label] = {"family": family, "exact_none": round(none, 4), "exact_gold": round(gold, 4),
                               "gold_minus_none": round(gold - none, 4)}
        print(f"{label}: exact none={none:.4f} gold={gold:.4f} | gold-none={gold-none:+.4f}")
        del m
        if dev == "cuda":
            torch.cuda.empty_cache()
    Path(args.out).write_text(json.dumps(out, indent=1))
    print("->", args.out)


if __name__ == "__main__":
    main()
