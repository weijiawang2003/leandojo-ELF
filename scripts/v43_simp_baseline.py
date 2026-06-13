"""Mini-ELF v43 — A1: the simp/aesop baseline (cheapest falsifier, NO training).

For both tiers, try the pre-registered trivial-closer set {simp, simp_all, aesop} (plus a wider
context sweep) on every theorem, via the V42 sound bisect verifier. Compare against the V42
flow-unique theorems and the {direct-AR ∪ plan-AR} solved sets (from outputs/v42/rebase).

Pre-registered falsifier: if the simp-sweep solves >= the flow∪AR uniques on dev, LPSF's H13
value is simp-bias and the bet closes as a mechanism result.
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

# Pre-registered A1 set + a wider trivial-closer context sweep.
SIMP_SET = ["simp", "simp_all", "aesop"]
WIDE_SET = ["simp", "simp_all", "aesop", "norm_num", "omega", "rfl", "tauto",
            "decide", "simp_all [*]", "aesop?", "exact?", "norm_num [*]",
            "simp only []", "constructor <;> simp", "intro <;> simp"]


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def load_tier(name: str):
    return [json.loads(l) for l in (ROOT / f"data/v40/tiers/{name}.jsonl").read_text().splitlines() if l.strip()]


def solved_set(rebase_stem: str):
    f = ROOT / f"outputs/v42/rebase/{rebase_stem}_v42iso.json"
    if not f.exists():
        return set()
    d = json.loads(f.read_text())
    return {t["name"] for t in d["theorems"] if t["solved_new"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tactic-set", choices=["simp", "wide"], default="wide")
    ap.add_argument("--cache", default=str(ROOT / "outputs/v43/simp/vcache.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "outputs/v43/simp/simp_baseline.json"))
    args = ap.parse_args()

    from v38_matrix_eval import get_verifier
    verifier = get_verifier()
    assert verifier is not None, "verifier unavailable"
    cache = VerdictCache(Path(args.cache), verifier.imports)
    tactics = WIDE_SET if args.tactic_set == "wide" else SIMP_SET

    out = {"verify_mode": "bisect-batched", "git_sha": git_sha(),
           "tactic_set": args.tactic_set, "tactics": tactics, "tiers": {}}
    t0 = time.time()
    for tier in ("tier_dev", "tier_final"):
        rows = load_tier(tier)
        items = [(r["full_name"], r["statement"], tac) for r in rows for tac in tactics]
        vmap = cached_verify(verifier, items, cache)
        per_thm = {}
        simp3 = set()  # solved by the pre-registered {simp,simp_all,aesop} subset
        wide = set()
        for r in rows:
            nm = r["full_name"]
            hits = [tac for tac in tactics if vmap.get((nm, tac))]
            per_thm[nm] = hits
            if hits:
                wide.add(nm)
            if any(vmap.get((nm, t)) for t in SIMP_SET):
                simp3.add(nm)
        out["tiers"][tier] = {
            "n": len(rows),
            "solved_simp3": sorted(simp3), "n_simp3": len(simp3),
            "solved_wide": sorted(wide), "n_wide": len(wide),
            "per_theorem": per_thm,
        }
        print(f"[{tier}] simp3={len(simp3)}/{len(rows)}  wide={len(wide)}/{len(rows)}")

    # comparison against V42 flow uniques and AR/plan-AR bases
    recheck = json.loads((ROOT / "outputs/v42/rebase/v41_uniques_directAR_recheck.json").read_text())
    flow_uniques = {"tier_dev": [], "tier_final": []}
    for row in recheck["rows"]:
        flow_uniques[row["tier"]].append(row["theorem"])
    out["v42_flow_uniques"] = flow_uniques
    cmp = {}
    for tier in ("tier_dev", "tier_final"):
        dar = solved_set(f"{tier}_ar")
        par = solved_set(f"{tier}_plan_ar")
        base = dar | par
        simp3 = set(out["tiers"][tier]["solved_simp3"])
        wide = set(out["tiers"][tier]["solved_wide"])
        fu = set(flow_uniques[tier])
        cmp[tier] = {
            "direct_ar": len(dar), "plan_ar": len(par), "base_union": len(base),
            "flow_uniques": sorted(fu),
            "flow_uniques_caught_by_simp3": sorted(fu & simp3),
            "flow_uniques_caught_by_wide": sorted(fu & wide),
            "simp3_uniques_over_base": sorted(simp3 - base),
            "wide_uniques_over_base": sorted(wide - base),
            "base_plus_simp3": len(base | simp3),
            "base_plus_wide": len(base | wide),
        }
        print(f"[{tier}] base_union={len(base)} flow_uniques={sorted(fu)} "
              f"caught_by_simp3={sorted(fu & simp3)} caught_by_wide={sorted(fu & wide)}")
    out["comparison"] = cmp
    out["wall_s"] = round(time.time() - t0, 1)
    out["lean_s"] = round(verifier.total_lean_seconds, 1)
    out["cache"] = {"hits": cache.hits, "misses": cache.misses}

    op = Path(args.out)
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, indent=1))
    print("->", op, f"({out['wall_s']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
