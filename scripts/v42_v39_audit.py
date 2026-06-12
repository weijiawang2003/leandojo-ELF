"""Mini-ELF v42 — P2.5: spot audit of the v39 24-tier headline (AR .917 / MDLM .917 / FLOW@1 .833).

Re-verifies the persisted v39B per-theorem topk candidates in trusted bisect-batched
mode and diffs against the old batched verdicts. Single-tactic candidates on a
377-token vocab — low poison risk (the pre-registered expectation), but unaudited
until tonight. Statements come from the same loader v39_verify used
(`mathlib_test_tier(load_dataset()["test"], cap=24)`).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    sys.path.insert(0, p)

from mini_elf_lean.v38_data import load_dataset, mathlib_test_tier  # noqa: E402
from mini_elf_lean.verdict_cache import VerdictCache, cached_verify  # noqa: E402


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--details", nargs="+", default=[
        str(ROOT / "outputs/v39/trackA/detail/headline_ar_30M_U3689_s16.json"),
        str(ROOT / "outputs/v39/trackA/detail/headline_mdlm_30M_U3689_s16.json"),
        str(ROOT / "outputs/v39/trackA/detail/headline_flow_30M_U3689_s1.json"),
    ])
    ap.add_argument("--cache", default=str(ROOT / "outputs/v42/vcache.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "outputs/v42/rebase/v39_24tier_spot_v42iso.json"))
    args = ap.parse_args()

    from v38_matrix_eval import get_verifier
    verifier = get_verifier()
    assert verifier is not None
    cache = VerdictCache(Path(args.cache), verifier.imports)
    tier = mathlib_test_tier(load_dataset()["test"], cap=24)
    stmts = {r["theorem_name"]: r["theorem_statement"] for r in tier}

    out_models, t0 = [], time.time()
    for dp in args.details:
        d = json.loads(Path(dp).read_text())
        items, ths = [], []
        for t in d["theorems"]:
            for c in t["topk"]:
                items.append((t["name"], stmts[t["name"]], c["tactic"]))
        vmap = cached_verify(verifier, items, cache)
        n_old = n_new = changes = 0
        th_rows = []
        for t in d["theorems"]:
            topk = [{"tactic": c["tactic"], "verified_old": bool(c["verified"]),
                     "verified_new": bool(vmap[(t["name"], c["tactic"])])} for c in t["topk"]]
            changes += sum(1 for c in topk if c["verified_old"] != c["verified_new"])
            so, sn = any(c["verified_old"] for c in topk), any(c["verified_new"] for c in topk)
            n_old += so; n_new += sn
            th_rows.append({"name": t["name"], "solved_old": so, "solved_new": sn, "topk": topk})
        out_models.append({"detail_file": dp, "model_id": d["model_id"], "steps": d.get("steps"),
                           "n_theorems": len(th_rows), "solved_old": n_old, "solved_new": n_new,
                           "pass10_old": round(n_old / len(th_rows), 4),
                           "pass10_new": round(n_new / len(th_rows), 4),
                           "candidate_verdict_changes": changes, "theorems": th_rows})
        print(f"[{d['model_id']} s{d.get('steps')}] {n_old}/{len(th_rows)} -> {n_new}/{len(th_rows)} (changes={changes})")

    rec = {"verify_mode": "bisect-batched", "git_sha": git_sha(),
           "lean_s": round(verifier.total_lean_seconds, 1), "wall_s": round(time.time() - t0, 1),
           "cache": {"hits": cache.hits, "misses": cache.misses}, "models": out_models}
    op = Path(args.out); op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(rec))
    print("->", op)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
