"""Mini-ELF v43 — union analysis for A2/D1/B2 (simp-inclusive base).

Reads e2e solved_sets (from v43_e2e_union outputs) + the base solved sets:
  direct-AR, plan-AR  (V42 rebase: outputs/v42/rebase/{tier}_{ar,plan_ar}_v42iso.json)
  simp, aesop, wide   (A1: outputs/v43/simp/simp_baseline.json)
Computes per-seed flow union gain over base = {direct-AR ∪ plan-AR ∪ simp3} and over the wide
base, and the D1 ensemble {AR ∪ MDLM ∪ flow}. A2 bar: flow gain ≥ +2 in ≥ 2/3 seeds.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def v42_solved(tier: str, stem: str) -> set:
    f = ROOT / f"outputs/v42/rebase/{tier}_{stem}_v42iso.json"
    if not f.exists():
        return set()
    d = json.loads(f.read_text())
    return {t["name"] for t in d["theorems"] if t["solved_new"]}


def simp_sets(tier: str):
    d = json.loads((ROOT / "outputs/v43/simp/simp_baseline.json").read_text())
    t = d["tiers"][tier]
    return set(t["solved_simp3"]), set(t["solved_wide"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--e2e", nargs="+", required=True, help="v43 e2e union json files")
    ap.add_argument("--tier", default="tier_dev")
    ap.add_argument("--out", default=str(ROOT / "outputs/v43/union/union_report.json"))
    args = ap.parse_args()

    solved = {}
    for f in args.e2e:
        d = json.loads(Path(f).read_text())
        solved.update({k: set(v) for k, v in d["solved_sets"].items()})

    dar = v42_solved(args.tier, "ar")
    par = v42_solved(args.tier, "plan_ar")
    simp3, wide = simp_sets(args.tier)
    base_core = dar | par                  # learned base (no simp)
    base_simp = dar | par | simp3          # + pre-registered simp set
    base_wide = dar | par | wide           # + wide trivial sweep

    rep = {"tier": args.tier, "sizes": {"direct_ar": len(dar), "plan_ar": len(par),
            "simp3": len(simp3), "wide": len(wide), "base_core": len(base_core),
            "base_simp": len(base_simp), "base_wide": len(base_wide)},
           "sources": {}}
    flow_gains_simp, flow_gains_wide = [], []
    for label, s in sorted(solved.items()):
        gain_core = len(s - base_core)
        gain_simp = len(s - base_simp)
        gain_wide = len(s - base_wide)
        rep["sources"][label] = {"solved": len(s),
                                 "gain_over_base_core": gain_core, "uniq_core": sorted(s - base_core),
                                 "gain_over_base_simp": gain_simp, "uniq_simp": sorted(s - base_simp),
                                 "gain_over_base_wide": gain_wide, "uniq_wide": sorted(s - base_wide)}
        if "flow" in label:
            flow_gains_simp.append((label, gain_simp))
            flow_gains_wide.append((label, gain_wide))

    # D1 ensemble: AR ∪ MDLM ∪ flow (plan level) per seed, vs coarse-AR alone
    ens = {}
    for seed in ("3407", "4242", "7331"):
        fa = solved.get(f"coarse_ar_{seed}", set())
        fm = solved.get(f"coarse_mdlm_{seed}", set())
        ff = solved.get(f"coarse_flow_{seed}", set())
        if fa or fm or ff:
            ens[seed] = {"ar": len(fa), "ar_mdlm": len(fa | fm),
                         "ar_mdlm_flow": len(fa | fm | ff),
                         "flow_adds_over_ar_mdlm": sorted(ff - (fa | fm))}
    rep["D1_ensemble"] = ens

    n_simp_pass = sum(1 for _l, g in flow_gains_simp if g >= 2)
    n_wide_pass = sum(1 for _l, g in flow_gains_wide if g >= 2)
    rep["A2_verdict"] = {
        "flow_gains_over_base_simp": flow_gains_simp,
        "flow_gains_over_base_wide": flow_gains_wide,
        "n_seeds_ge2_over_simp": n_simp_pass, "n_seeds_ge2_over_wide": n_wide_pass,
        "bar": "gain >= +2 in >= 2/3 seeds",
        "A2_passes_over_simp_base": n_simp_pass >= 2,
        "A2_passes_over_wide_base": n_wide_pass >= 2,
    }
    Path(args.out).write_text(json.dumps(rep, indent=1))
    print(f"[{args.tier}] base_core={len(base_core)} base_simp={len(base_simp)} base_wide={len(base_wide)}")
    for label, info in rep["sources"].items():
        print(f"  {label}: solved {info['solved']} | gain/core {info['gain_over_base_core']} "
              f"/simp {info['gain_over_base_simp']} /wide {info['gain_over_base_wide']}")
    print("A2 flow gains /simp:", flow_gains_simp, "-> passes" if n_simp_pass >= 2 else "-> FAILS (closes)")
    print("A2 flow gains /wide:", flow_gains_wide, "-> passes" if n_wide_pass >= 2 else "-> FAILS (closes)")
    print("D1 ensemble:", ens)
    print("->", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
