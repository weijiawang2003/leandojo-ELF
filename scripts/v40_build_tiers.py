"""Mini-ELF v40 — build two disjoint real-Mathlib verified tiers from LeanDojo test.

Harvest test-split theorems whose reconstructed `example stmt := by gold` COMPILES,
stratify by proof length {1, 2-3, 4+}, split into tier-dev / tier-final (touched once,
Phase 7). Gold-compile-rate is a deliverable. Writes data/v40/tiers/{tier_dev,tier_final}.jsonl
+ manifest. Verify wall-clock is the cost; cache the harvest.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    sys.path.insert(0, p)

from mini_elf_lean.tactic_tokenizer import tokenize
from v38_matrix_eval import get_verifier
from v40_wholeproof import state_to_example, whole_proof

RAW = ROOT / "data" / "v39" / "_raw" / "leandojo_benchmark_4" / "random"
OUT = ROOT / "data" / "v40" / "tiers"


def tlen(s):
    return sum(1 for _ in tokenize(s))


def length_bucket(nt):
    return "1" if nt == 1 else ("2-3" if nt <= 3 else "4+")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cond-cap", type=int, default=256)
    ap.add_argument("--proof-cap", type=int, default=48)
    ap.add_argument("--max-try", type=int, default=900, help="cap convertible theorems to verify")
    ap.add_argument("--per-tier", type=int, default=48)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    data = json.load(open(RAW / "test.json"))
    cand = []
    for th in data:
        tt = th.get("traced_tactics", [])
        if not tt:
            continue
        stmt = state_to_example(tt[0].get("state_before", ""))
        wp = whole_proof(tt)
        if stmt is None or wp is None:
            continue
        if tlen(stmt) > args.cond_cap or tlen(wp) > args.proof_cap:
            continue
        cand.append({"full_name": th["full_name"], "statement": stmt, "proof": wp,
                     "n_tactics": len(tt), "bucket": length_bucket(len(tt))})
    random.seed(3407); random.shuffle(cand)
    cand = cand[: args.max_try]
    print(f"convertible test theorems to verify: {len(cand)}")

    v = get_verifier()
    items = [(c["full_name"], c["statement"], c["proof"]) for c in cand]
    t = time.time()
    res = v.verify_many(items, confirm=True)
    smap = {(x.theorem_name, x.tactic): x.success for x in res}
    compiled = [c for c in cand if smap.get((c["full_name"], c["proof"]))]
    rate = len(compiled) / max(len(cand), 1)
    print(f"GOLD-COMPILE-RATE: {len(compiled)}/{len(cand)} = {rate:.1%}  ({time.time()-t:.0f}s lean={v.total_lean_seconds:.0f})")
    from collections import Counter
    bc = Counter(c["bucket"] for c in compiled)
    print(f"compiled by bucket: {dict(bc)}")

    # stratified 50/50 split dev/final, dedup by full_name
    seen, dev, fin = set(), [], []
    by_bucket = {"1": [], "2-3": [], "4+": []}
    for c in compiled:
        if c["full_name"] in seen:
            continue
        seen.add(c["full_name"]); by_bucket[c["bucket"]].append(c)
    for b, lst in by_bucket.items():
        for i, c in enumerate(lst):
            (dev if i % 2 == 0 else fin).append(c)
    dev = dev[: args.per_tier]; fin = fin[: args.per_tier]
    print(f"tier-dev: {len(dev)}  tier-final: {len(fin)}  (buckets dev={Counter(c['bucket'] for c in dev)}, "
          f"final={Counter(c['bucket'] for c in fin)})")

    for name, rows in [("tier_dev", dev), ("tier_final", fin)]:
        with (OUT / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for c in rows:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
    manifest = {
        "source": "LeanDojo Benchmark 4 random/test", "gold_compile_rate": round(rate, 4),
        "n_convertible_verified": len(cand), "n_compiled": len(compiled),
        "compiled_by_bucket": dict(bc), "n_tier_dev": len(dev), "n_tier_final": len(fin),
        "cond_cap": args.cond_cap, "proof_cap": args.proof_cap, "seed": 3407,
        "note": "tier-final touched exactly once (Phase 7). Whole-proof example reconstruction "
                "from first state_before; version skew (v4.19 bench vs v4.30 scratch) limits compile rate.",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
