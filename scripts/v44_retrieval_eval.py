"""Mini-ELF v44 — R1: retriever recall@k / MRR, dense vs BM25, on the hard tier.

For each hard-tier theorem with >=1 gold premise, retrieve top-k premises from the statement and
score recall@k (fraction of gold premises present) + MRR of the first gold hit. Compares the dense
dual-encoder against BM25. Both retrievers exclude the theorem's own name.
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

from mini_elf_lean.grounder_retrieval import BM25Retriever


def git_sha():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def recall_mrr(retrieved, gold, ks):
    gold = set(gold)
    rec = {}
    for k in ks:
        topk = set(retrieved[:k])
        rec[k] = len(topk & gold) / len(gold) if gold else None
    mrr = 0.0
    for rank, nm in enumerate(retrieved, 1):
        if nm in gold:
            mrr = 1.0 / rank
            break
    return rec, mrr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", nargs="+", default=[
        str(ROOT / "outputs/v44/hard_tier/hard_dev.jsonl"),
        str(ROOT / "outputs/v44/hard_tier/hard_test.jsonl")])
    ap.add_argument("--ks", default="1,5,10,20")
    ap.add_argument("--topn", type=int, default=20)
    ap.add_argument("--out", default=str(ROOT / "outputs/v44/retriever/recall_eval.json"))
    args = ap.parse_args()
    ks = [int(x) for x in args.ks.split(",")]

    rows = []
    for tf in args.tiers:
        rows += [json.loads(l) for l in Path(tf).read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r.get("premises")]
    print(f"hard-tier theorems with gold premises: {len(rows)}")

    bm25 = BM25Retriever()
    try:
        from mini_elf_lean.retriever_dense import DenseRetriever
        dense = DenseRetriever(device="cuda" if __import__("torch").cuda.is_available() else "cpu")
        have_dense = True
    except Exception as e:
        print("dense retriever unavailable:", e); dense = None; have_dense = False

    def agg(retr):
        rsum = {k: 0.0 for k in ks}
        mrr_sum, n = 0.0, 0
        for r in rows:
            got = retr(r["statement"], r["full_name"])
            rec, mrr = recall_mrr(got, r["premises"], ks)
            for k in ks:
                rsum[k] += rec[k]
            mrr_sum += mrr; n += 1
        return {f"recall@{k}": round(rsum[k] / max(n, 1), 4) for k in ks} | {"mrr": round(mrr_sum / max(n, 1), 4)}

    out = {"git_sha": git_sha(), "n": len(rows), "ks": ks}
    out["bm25"] = agg(lambda s, nm: bm25.retrieve(s, topn=args.topn, exclude=[nm]))
    print("BM25 :", out["bm25"])
    if have_dense:
        out["dense"] = agg(lambda s, nm: dense.retrieve(s, topn=args.topn, exclude=[nm]))
        print("dense:", out["dense"])
        out["R1_dense_beats_bm25_recall@10"] = out["dense"]["recall@10"] > out["bm25"]["recall@10"]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print("->", args.out)


if __name__ == "__main__":
    main()
