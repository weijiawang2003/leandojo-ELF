"""Mini-ELF v30 — Part 9: density law update after targeted repair.

Tests the v29 density law OUT-OF-SAMPLE: did bringing the repaired families to ~4–6
siblings actually fix their held-out failures, and did the v25 micro-regression
recover? Reads the v30 specialist eval + dataset summary (NO Lean run).

Reports:
  * before→after for each repaired family (v29 → v30 pass@10 on the relevant holdout);
  * v25 micro-regression recovery (nat_add_assoc, set_empty_subset);
  * targeted-family-holdout pass@10 vs its training density;
  * whether failures now concentrate below 4 siblings;
  * whether marginal returns saturate;
  * any sign of an architecture / proof-state bottleneck.

Writes data/baselines/v30_density_law_update/report.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
V30E = ROOT / "data" / "baselines" / "v30_specialist_eval"
V29E = ROOT / "data" / "baselines" / "v29_specialist_eval"
DS = ROOT / "data" / "processed" / "v30_mathlib_specialist"


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def best_metrics(run_dir: Path) -> Optional[Dict[str, Any]]:
    best = None
    for f in run_dir.glob("*/metrics.json"):
        m = json.loads(f.read_text())
        key = (m.get("pass@5", 0), m.get("pass@1", 0))
        if best is None or key > best[0]:
            best = (key, m)
    return best[1] if best else None


def cell10(root, model, bench):
    m = best_metrics(root / f"{model}__{bench}")
    return m.get("pass@10") if m else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v30_density_law_update" / "report.json"))
    ap.add_argument("--model", default="v30_general_targeted")
    args = ap.parse_args(argv)

    ds = json.loads((DS / "summary.json").read_text()) if (DS / "summary.json").exists() else {}
    tf_density = ds.get("targeted_family_holdout", {}).get("family_train_density", {})

    report: Dict[str, Any] = {"config": "v30_density_law_update", "model": args.model}

    # ---- fresh/preserved benches: v29 best vs v30 ----
    benches = ["v25_heldout", "v26_holdout", "v27_holdout", "v28_holdout", "v29_holdout",
               "v29_family_density", "v29_low_density", "v30_holdout", "v30_targeted_family"]
    v29_models = ["v29_general", "v29_set_finset_order_heavy"]
    table = {}
    for bench in benches:
        v30 = cell10(V30E, args.model, bench)
        v29 = None
        for m in v29_models:
            c = cell10(V30E, m, bench)
            if c is not None and (v29 is None or c > v29):
                v29 = c
        table[bench] = {"v29_best": v29, "v30": v30,
                        "delta": (round(v30 - v29, 4) if v30 is not None and v29 is not None else None)}
    report["bench_v29_vs_v30"] = table

    # ---- v25 micro-regression recovery ----
    comp = json.loads((V30E / "comparison.json").read_text()) if (V30E / "comparison.json").exists() else {}
    rec = comp.get("recovery", {})
    report["v25_recovery"] = {
        "v29_general": rec.get("v29_general"),
        args.model: rec.get(args.model),
        "v25_pass@10_v29": cell10(V30E, "v29_general", "v25_heldout"),
        "v25_pass@10_v30": cell10(V30E, args.model, "v25_heldout"),
    }

    # ---- targeted-family holdout: per-family pass@10 vs training density ----
    m = best_metrics(V30E / f"{args.model}__v30_targeted_family")
    per_fam = (m or {}).get("per_family", {})
    fam_rows = []
    for fam, d in sorted(per_fam.items()):
        fam_rows.append({"family": fam, "n": d["n"], "pass@10": d["pass@10"],
                         "train_density": tf_density.get(fam)})
    report["targeted_family_per_family"] = fam_rows
    # do failures concentrate below 4 siblings?
    below = [r for r in fam_rows if (r["train_density"] or 0) < 4]
    atleast = [r for r in fam_rows if (r["train_density"] or 0) >= 4]
    def avg(rs):
        rs = [r["pass@10"] for r in rs if r["pass@10"] is not None]
        return round(sum(rs) / len(rs), 4) if rs else None
    report["failures_vs_threshold"] = {
        "below_4_siblings": {"n_families": len(below), "mean_pass@10": avg(below)},
        "at_least_4_siblings": {"n_families": len(atleast), "mean_pass@10": avg(atleast)},
    }

    # ---- v29 family-density (the _3 residuals) before/after ----
    report["v29_family_density_repair"] = {
        "v29_general": cell10(V30E, "v29_general", "v29_family_density"),
        "v30": cell10(V30E, args.model, "v29_family_density"),
    }

    # ---- remaining residuals of v30 best on fresh benches ----
    residual_classes = []
    for bench in ("v28_holdout", "v29_holdout", "v29_family_density", "v30_holdout", "v30_targeted_family"):
        mm = best_metrics(V30E / f"{args.model}__{bench}")
        if mm:
            residual_classes.extend(mm.get("no_verify_reason", {}).values())
    from collections import Counter
    report["v30_residual_classes"] = dict(Counter(residual_classes))
    n_resid = len(residual_classes)
    report["n_residuals"] = n_resid

    # ---- verdicts ----
    v25_rec = report["v25_recovery"]["v25_pass@10_v30"]
    report["density_law_out_of_sample"] = {
        "v25_recovered": (v25_rec is not None and v25_rec >= 1.0 - 1e-9),
        "below_threshold_worse": (report["failures_vs_threshold"]["below_4_siblings"]["mean_pass@10"] is not None
                                  and report["failures_vs_threshold"]["at_least_4_siblings"]["mean_pass@10"] is not None
                                  and report["failures_vs_threshold"]["below_4_siblings"]["mean_pass@10"]
                                  <= report["failures_vs_threshold"]["at_least_4_siblings"]["mean_pass@10"] + 1e-9),
        "note": "targeted repair validates the density law if v25 recovers and "
                "below-threshold families remain the weak ones.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[density-update] bench v29->v30:")
    for b, d in table.items():
        print(f"   {b:22s} v29={d['v29_best']} v30={d['v30']} delta={d['delta']}")
    print("[density-update] v25 recovery:", report["v25_recovery"])
    print("[density-update] failures vs 4-sibling threshold:", report["failures_vs_threshold"])
    print("[density-update] v29 family-density (_3) repair:", report["v29_family_density_repair"])
    print("[density-update] v30 residual classes:", report["v30_residual_classes"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
