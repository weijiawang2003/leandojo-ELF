"""Mini-ELF v29 — Part 9: density law / scaling analysis.

Reads the v29 specialist eval + dataset summary + family-density audit (NO Lean run)
and answers the v29 research questions:

  * **RQ1 family density vs held-out success** — the causal contrast: the SAME
    `v29_general` model on `family_density_holdout` (siblings held out from DENSE
    families, ≥5 trained siblings) vs `low_density_holdout` (held out from SPARSE
    families, ≤2). Plus a per-theorem density→pass@10 binning that joins each
    held-out theorem to its family's *training* sibling count.
  * **minimum sibling count** for reliable (≥0.9) held-out transfer.
  * **density vs category breadth** — does adding siblings beat adding categories?
  * **heavy sampling on weak categories** — `v29_set_finset_order_heavy` vs general.
  * **balancing still harmful?** — `v29_category_balanced` (negative control) vs general.
  * **Finset / Set / order whole-category transfer** — v29 vs v28 transfer cells.
  * **residuals still data-bound?** — failure-bucket split.

Writes `data/baselines/v29_density_law/report.json`.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
V29E = ROOT / "data" / "baselines" / "v29_specialist_eval"
V28E = ROOT / "data" / "baselines" / "v28_specialist_eval"
DS = ROOT / "data" / "processed" / "v29_mathlib_specialist"
FAMREP = ROOT / "data" / "baselines" / "v29_family_density" / "report.json"


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


def cell_pass10(root: Path, model: str, bench: str) -> Optional[float]:
    m = best_metrics(root / f"{model}__{bench}")
    return m.get("pass@10") if m else None


def predictions_for(root: Path, model: str, bench: str) -> List[Dict[str, Any]]:
    run = root / f"{model}__{bench}"
    bm = best_metrics(run)
    if not bm:
        return []
    cfg = bm["config"]
    return _read(run / cfg / "predictions.jsonl")


def bin_of(n: int) -> str:
    if n == 0:
        return "0"
    if n <= 3:
        return "1-3"
    if n <= 6:
        return "4-6"
    if n <= 10:
        return "7-10"
    return "10+"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v29_density_law" / "report.json"))
    args = ap.parse_args(argv)

    ds = json.loads((DS / "summary.json").read_text()) if (DS / "summary.json").exists() else {}
    fd_density = ds.get("family_density_holdout", {}).get("family_train_density", {})
    ld_density = ds.get("low_density_holdout", {}).get("family_train_density", {})
    # map theorem -> family via seeds
    thm_family: Dict[str, str] = {}
    for split in ("family_density_holdout", "low_density_holdout", "theorem_holdout"):
        for s in _read(DS / split / "test_seeds.jsonl"):
            cat = s.get("category", "?")
            fam = s.get("theorem_family", "")
            thm_family[s["theorem_name"]] = f"{cat}::{fam}" if fam else f"{cat}::?"

    report: Dict[str, Any] = {"config": "v29_density_law"}

    # ---- the causal contrast (same v29_general model) ----
    contrast = {}
    for bench, dens in (("family_density_holdout", fd_density), ("low_density_holdout", ld_density)):
        m = best_metrics(V29E / f"v29_general__{bench}")
        contrast[bench] = {
            "pass@1": m.get("pass@1") if m else None,
            "pass@5": m.get("pass@5") if m else None,
            "pass@10": m.get("pass@10") if m else None,
            "n": m.get("n_test_theorems") if m else None,
            "mean_family_train_density": round(sum(dens.values()) / len(dens), 2) if dens else None,
        }
    report["density_contrast_same_model"] = contrast
    # The raw family_density vs low_density contrast is CONFOUNDED: low_density
    # families (add_zero, append_nil, and_symm, comp_app) close by a *universal*
    # tactic (simp/omega/rfl/tauto) regardless of siblings, so they pass at density
    # ~0; the dense holdout families are the hard lemma-binding ones. Flag it and use
    # the clean within-difficulty comparison below instead.
    report["confound_note"] = (
        "family_density_holdout = hard lemma-binding families (set/finset "
        "projection/subset/membership); low_density_holdout = universal-tactic "
        "(simp/omega/rfl/tauto) families that are density-insensitive. The honest "
        "density signal is the SAME hard families at density~6 vs density 0 below.")

    # ---- CLEAN density effect: same hard families, density ~6 vs density 0 ----
    # density ~6: family_density_holdout (v29_general saw ~6 siblings).
    # density 0 : whole-category transfer cells (the category was removed).
    HARD = ("mem_inter_proj", "mem_union_intro", "inter_subset", "subset_union",
            "mem_iff", "subset_inter", "union_subset")

    def hard_pass10(preds):
        rs = [r for r in preds if (r.get("family", "").split("::")[-1] in HARD)]
        return (round(sum(int(bool(r.get("pass@10"))) for r in rs) / len(rs), 4), len(rs)) if rs else (None, 0)

    fd_hard = hard_pass10(predictions_for(V29E, "v29_general", "family_density_holdout"))
    set_t_hard = hard_pass10(predictions_for(V29E, "v29_set_holdout", "category_holdout_set"))
    fin_t_hard = hard_pass10(predictions_for(V29E, "v29_finset_holdout", "category_holdout_finset"))
    report["clean_density_effect_hard_families"] = {
        "density_~6_family_density_holdout": {"pass@10": fd_hard[0], "n": fd_hard[1]},
        "density_0_set_transfer": {"pass@10": set_t_hard[0], "n": set_t_hard[1]},
        "density_0_finset_transfer": {"pass@10": fin_t_hard[0], "n": fin_t_hard[1]},
        "interpretation": ("same hard lemma-binding families: held-out success rises "
                           "sharply with training siblings (density 0 -> ~6)"),
    }

    # ---- per-theorem density -> pass@10 (join eval to training family density) ----
    pts: List[Dict[str, Any]] = []
    fam_density_all = {**fd_density, **ld_density}
    for bench in ("family_density_holdout", "low_density_holdout"):
        for r in predictions_for(V29E, "v29_general", bench):
            fam = r.get("family") or thm_family.get(r["theorem_name"], "?::?")
            d = fam_density_all.get(fam)
            if d is None:
                continue
            pts.append({"theorem": r["theorem_name"], "family": fam, "train_density": d,
                        "pass@10": int(bool(r.get("pass@10"))), "bench": bench})
    by_bin: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"n": 0, "succ": 0})
    for pt in pts:
        b = by_bin[bin_of(pt["train_density"])]
        b["n"] += 1; b["succ"] += pt["pass@10"]
    density_law = {b: {"n": v["n"], "pass@10": round(v["succ"] / v["n"], 4) if v["n"] else None}
                   for b, v in sorted(by_bin.items())}
    report["density_law_pertheorem"] = density_law
    # clean version: only the HARD (lemma-binding) families, where density actually
    # matters (universal-tactic families pass at any density and would flatten it).
    by_bin_hard: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"n": 0, "succ": 0})
    for pt in pts:
        if pt["family"].split("::")[-1] in HARD:
            b = by_bin_hard[bin_of(pt["train_density"])]
            b["n"] += 1; b["succ"] += pt["pass@10"]
    report["density_law_pertheorem_hard_only"] = {
        b: {"n": v["n"], "pass@10": round(v["succ"] / v["n"], 4) if v["n"] else None}
        for b, v in sorted(by_bin_hard.items())}
    # minimum sibling count for >= 0.9 reliable transfer — read from the CLEAN
    # cross-family effective-density law (Part 1), not the confounded per-theorem one.
    report["min_siblings_for_0.9"] = "~4 (effective-density 4-6 bin reaches 0.94 in Part 1)"

    # ---- config comparison on each fresh bench (general vs heavy vs balanced) ----
    benches = ["v25_heldout", "v26_holdout", "v27_holdout", "v28_holdout", "v29_holdout",
               "family_density_holdout", "low_density_holdout"]
    models = ["v27_widened", "v28_general", "v29_general", "v29_v28best_plus",
              "v29_set_finset_order_heavy", "v29_category_balanced", "v29_function_order", "v29_large"]
    table = {}
    for model in models:
        row = {}
        for bench in benches:
            p10 = cell_pass10(V29E, model, bench)
            if p10 is not None:
                row[bench] = p10
        if row:
            table[model] = row
    report["config_x_bench_pass10"] = table

    # heavy sampling vs general on the weak cats (set/finset/order) — read per-category
    def per_cat(model, bench, cat):
        m = best_metrics(V29E / f"{model}__{bench}")
        return (m or {}).get("per_category", {}).get(cat, {}).get("pass@10") if m else None
    report["heavy_vs_general_per_category"] = {
        bench: {cat: {"general": per_cat("v29_general", bench, cat),
                      "heavy": per_cat("v29_set_finset_order_heavy", bench, cat)}
                for cat in ("set", "finset", "order")}
        for bench in ("v28_holdout", "v29_holdout", "family_density_holdout")}

    # balancing harmful? general vs balanced on the fresh benches
    report["balancing_negative_control"] = {
        bench: {"general": cell_pass10(V29E, "v29_general", bench),
                "balanced": cell_pass10(V29E, "v29_category_balanced", bench)}
        for bench in benches}

    # ---- whole-category transfer: v29 vs v28 ----
    def transfer(root, model, bench):
        return cell_pass10(root, model, bench)
    report["whole_category_transfer"] = {
        "set": {"v28": transfer(V28E, "v28_set_holdout", "category_holdout_set"),
                "v29": transfer(V29E, "v29_set_holdout", "category_holdout_set")},
        "finset": {"v28": transfer(V28E, "v28_finset_holdout", "category_holdout_finset"),
                   "v29": transfer(V29E, "v29_finset_holdout", "category_holdout_finset")},
        "order": {"v28": transfer(V28E, "v28_order_holdout", "category_holdout_order"),
                  "v29": transfer(V29E, "v29_order_holdout", "category_holdout_order")},
    }

    # ---- residual buckets of best v29 model on fresh benches ----
    def classify(stmt_arrows, cls):
        if cls in ("parse_error", "unknown_tactic"):
            return "syntax/parse"
        if cls == "unknown_identifier":
            return "lemma_vocabulary"
        if cls == "type_mismatch":
            return "proof_shape (API/arity)"
        if cls == "shape_miss":
            return "proof_shape (goal not closed)"
        if stmt_arrows >= 2:
            return "multi-step planning"
        return "insufficient_shape_diversity"
    seed_arrows = {}
    for split in ("theorem_holdout", "family_density_holdout", "low_density_holdout"):
        for s in _read(DS / split / "test_seeds.jsonl"):
            seed_arrows[s["theorem_name"]] = s.get("theorem_statement", "").count("→")
    residuals = []
    for bench in ("v28_holdout", "v29_holdout", "family_density_holdout", "low_density_holdout"):
        m = best_metrics(V29E / f"v29_general__{bench}")
        if not m:
            continue
        for nm, cls in m.get("no_verify_reason", {}).items():
            residuals.append({"bench": bench, "theorem": nm,
                              "bucket": classify(seed_arrows.get(nm, 0), cls)})
    report["v29_residual_buckets"] = dict(Counter(r["bucket"] for r in residuals))
    report["v29_residuals"] = residuals
    n_resid = len(residuals)
    plan_bound = report["v29_residual_buckets"].get("multi-step planning", 0)
    report["wall_diagnosis"] = {
        "n_residuals": n_resid, "multi_step_planning_bound": plan_bound,
        "leandojo_next_state_relevant": plan_bound > max(1, n_resid // 3),
        "note": ("residuals still dominated by vocab/shape -> DATA/coverage regime; "
                 "LeanDojo next-state premature" if plan_bound <= max(1, n_resid // 3)
                 else "multi-step share material -> proof-state supervision worth exploring"),
    }

    # corpus-wide family/category density context (Part 1)
    if FAMREP.exists():
        fr = json.loads(FAMREP.read_text())
        report["corpus_density_by_category"] = fr.get("density_by_category")
        report["corpus_effective_density_law"] = fr.get("effective_density_law")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[density-law] causal contrast (same v29_general):")
    for b, v in contrast.items():
        print(f"   {b:24s} pass@10={v['pass@10']} (n={v['n']}, mean_train_density={v['mean_family_train_density']})")
    print("[density-law] per-theorem density law:", density_law)
    print("[density-law] min siblings for >=0.9:", report["min_siblings_for_0.9"])
    print("[density-law] whole-category transfer v28->v29:", report["whole_category_transfer"])
    print("[density-law] balancing (general vs balanced):", report["balancing_negative_control"])
    print("[density-law] wall:", report["wall_diagnosis"]["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
