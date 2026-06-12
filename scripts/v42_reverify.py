"""Mini-ELF v42 — re-baseline committed candidate sets in trusted (bisect-batched) mode.

Inputs: v40 detail JSONs (`outputs/v40/wholeproof/detail_*/<model>.json`, which persist
per-theorem ranked top-10 candidates + the OLD batched verdicts) or v42 regenerated
candidate JSONs (`outputs/v42/candidates/*.json` from v42_regen_candidates.py).

For each input, every unique (statement, candidate) is verified through the persistent
VerdictCache via `verify_many_bisect` (provably equal to one-per-file isolation, see
tests/test_verifier_poison.py). Output carries full mode provenance and an old->new
per-candidate diff so the re-derivation table can be built mechanically.
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

from mini_elf_lean.verdict_cache import VerdictCache, cached_verify  # noqa: E402


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


def extract(input_path: Path, ranked_key: str):
    """-> (label, tier, theorems: [{name, topk:[(tactic, old_verified|None)]}])."""
    d = json.loads(input_path.read_text())
    if "theorems" in d:  # v40 detail format (old batched verdicts present)
        label = f"{d['model_id']}"
        tier = d["tier"] if "tier" in d else input_path.parent.name.replace("detail_", "")
        ths = [{"name": t["name"],
                "topk": [(c["tactic"], bool(c["verified"])) for c in t["topk"]]}
               for t in d["theorems"]]
        return label, tier, ths
    # v42 regenerated candidates (no old verdicts)
    label, tier = d["label"], d["tier"]
    ths = [{"name": nm, "topk": [(c, None) for c in d[ranked_key][nm]]}
           for nm in sorted(d[ranked_key])]
    return label, tier, ths


def passk(theorems, key):
    out = {}
    for kk in (1, 5, 10):
        out[str(kk)] = sum(1 for t in theorems if any(c[key] for c in t["topk"][:kk])) / max(len(theorems), 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", required=True)
    ap.add_argument("--out-dir", default=str(ROOT / "outputs/v42/rebase"))
    ap.add_argument("--cache", default=str(ROOT / "outputs/v42/vcache.jsonl"))
    ap.add_argument("--ranked-key", default="ranked_wf",
                    help="for v42 candidate inputs: ranked_wf (v41-canonical) or ranked_raw")
    ap.add_argument("--isolated", action="store_true",
                    help="force one-per-file instead of bisect-batched (ground-truth mode)")
    ap.add_argument("--suffix", default="v42iso")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT / "scripts"))
    from v38_matrix_eval import get_verifier
    verifier = get_verifier()
    assert verifier is not None, "verifier unavailable"
    cache = VerdictCache(Path(args.cache), verifier.imports)
    stmts = load_statements()
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    mode = "isolated" if args.isolated else "bisect-batched"

    for ip in args.inputs:
        ip = Path(ip)
        label, tier, ths = extract(ip, args.ranked_key)
        items = []
        for t in ths:
            for tac, _old in t["topk"]:
                items.append((t["name"], stmts[t["name"]], tac))
        t0 = time.time()
        vmap = cached_verify(verifier, items, cache, isolated=args.isolated)
        dt = time.time() - t0
        out_th, changes = [], 0
        for t in ths:
            topk = [{"tactic": tac, "verified_old": old,
                     "verified_new": bool(vmap[(t["name"], tac)])}
                    for tac, old in t["topk"]]
            changes += sum(1 for c in topk if c["verified_old"] is not None
                           and c["verified_old"] != c["verified_new"])
            t_has_old = any(c["verified_old"] is not None for c in topk)
            out_th.append({"name": t["name"],
                           "solved_old": (any(c["verified_old"] for c in topk) if t_has_old else None),
                           "solved_new": any(c["verified_new"] for c in topk),
                           "topk": topk})
        has_old = any(t["solved_old"] is not None for t in out_th)
        rec = {"verify_mode": mode, "git_sha": git_sha(), "source_file": str(ip),
               "label": label, "tier": tier, "n_theorems": len(out_th),
               "solved_new": sum(1 for t in out_th if t["solved_new"]),
               "solved_old": (sum(1 for t in out_th if t["solved_old"]) if has_old else None),
               "pass_at_k_new": {k: round(v, 4) for k, v in passk(
                   [{"topk": [(c["verified_new"],) for c in t["topk"]]} for t in out_th], 0).items()},
               "candidate_verdict_changes": changes if has_old else None,
               "lean_s": round(verifier.total_lean_seconds, 1), "wall_s": round(dt, 1),
               "cache": {"hits": cache.hits, "misses": cache.misses},
               "theorems": out_th}
        op = out_dir / f"{tier}_{label}_{args.suffix}.json"
        op.write_text(json.dumps(rec))
        old_s = rec["solved_old"]
        print(f"[{tier}/{label}] solved {old_s if old_s is not None else '?'} -> {rec['solved_new']}"
              f"/{len(out_th)} (changes={rec['candidate_verdict_changes']}) {dt:.0f}s -> {op}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
