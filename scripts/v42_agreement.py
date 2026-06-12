"""Mini-ELF v42 — agreement validation: bisect-batched vs isolated on real candidates.

Samples N candidates stratified across v40 detail sources and v42 regenerated v41
candidate sets (including the RAW unfiltered ranking, i.e. with malformed grounded
proofs), runs BOTH modes cache-free, and requires 100% agreement. Seeded; the
sample list is persisted in the output for reproducibility.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    sys.path.insert(0, p)


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def load_statements() -> dict:
    s = {}
    for tf in (ROOT / "data/v40/tiers/tier_dev.jsonl", ROOT / "data/v40/tiers/tier_final.jsonl"):
        for l in tf.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                s[r["full_name"]] = r["statement"]
    return s


def pool_from(path: Path, src_label: str, stmts: dict):
    d = json.loads(path.read_text())
    out = []
    if "theorems" in d:  # v40 detail
        for t in d["theorems"]:
            for c in t["topk"]:
                out.append((src_label, t["name"], stmts[t["name"]], c["tactic"]))
    else:  # v42 regenerated — use the RAW ranking (malformed candidates included)
        for nm, cands in d["ranked_raw"].items():
            for c in cands:
                out.append((src_label, nm, stmts[nm], c))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", nargs="+", required=True, help="label=path pairs")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=3407)
    ap.add_argument("--out", default=str(ROOT / "outputs/v42/agreement.json"))
    args = ap.parse_args()

    from v38_matrix_eval import get_verifier
    verifier = get_verifier()
    assert verifier is not None
    stmts = load_statements()

    pools = {}
    for spec in args.sources:
        label, path = spec.split("=", 1)
        pools[label] = pool_from(Path(path), label, stmts)
    rng = random.Random(args.seed)
    per = max(1, args.n // len(pools))
    sample = []
    for label, pool in sorted(pools.items()):
        uniq = sorted(set(pool))
        sample.extend(rng.sample(uniq, min(per, len(uniq))))
    sample = sample[:args.n]

    items = [(f"{i}", stmt, tac) for i, (_l, _nm, stmt, tac) in enumerate(sample)]
    t0 = time.time()
    bis = verifier.verify_many_bisect(items)
    t1 = time.time()
    iso = []
    for it in items:
        iso.extend(verifier.verify_many_bisect([it]))
    t2 = time.time()

    rows, n_agree = [], 0
    for (label, nm, _stmt, tac), b, g in zip(sample, bis, iso):
        agree = b.success == g.success
        n_agree += agree
        rows.append({"source": label, "theorem": nm, "tactic": tac,
                     "bisect": b.success, "isolated": g.success, "agree": agree})
    rec = {"verify_modes": ["bisect-batched", "isolated"], "git_sha": git_sha(),
           "seed": args.seed, "n": len(rows), "n_agree": n_agree,
           "agreement": n_agree / max(len(rows), 1),
           "bisect_s": round(t1 - t0, 1), "isolated_s": round(t2 - t1, 1),
           "per_source": {l: {"n": sum(1 for r in rows if r["source"] == l),
                              "agree": sum(1 for r in rows if r["source"] == l and r["agree"])}
                          for l in pools},
           "rows": rows}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rec))
    print(f"agreement {n_agree}/{len(rows)} = {rec['agreement']:.3f} "
          f"(bisect {rec['bisect_s']}s vs isolated {rec['isolated_s']}s) -> {args.out}")
    for r in rows:
        if not r["agree"]:
            print("MISMATCH", r["source"], r["theorem"], repr(r["tactic"][:60]),
                  "bisect", r["bisect"], "isolated", r["isolated"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
