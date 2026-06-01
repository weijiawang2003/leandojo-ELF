"""Mini-ELF v28 — Part 8: scaling / plateau analysis.

Reads the v28 specialist eval (+ v27 eval, routed system) and answers the v28
research questions, with no Lean run:

  * Did more data improve the **fresh holdout** (v27 0.714 plateau, and the new
    30-theorem v28 holdout)?
  * Did **Set / order** continue improving (per-category pass@10)?
  * Did **Finset transfer** work (the v28_finset_holdout transfer cell)?
  * Did **category balancing** help or hurt (general vs balanced vs set_order_heavy
    vs finset_specialist)?
  * Are the remaining failures data-volume / lemma-vocabulary / syntax-API /
    multi-step-planning / architecture?
  * Is LeanDojo next-state supervision now becoming relevant, or still premature?

Writes ``data/baselines/v28_scaling/report.json``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
V28 = ROOT / "data" / "baselines" / "v28_specialist_eval"
V27 = ROOT / "data" / "baselines" / "v27_specialist_eval"


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


def cell(root: Path, model: str, bench: str) -> Optional[Dict[str, Any]]:
    m = best_metrics(root / f"{model}__{bench}")
    if not m:
        return None
    pc = m.get("per_category", {})
    return {"best_config": m.get("config"), "pass@1": m.get("pass@1"), "pass@5": m.get("pass@5"),
            "pass@10": m.get("pass@10"),
            "set@10": pc.get("set", {}).get("pass@10"), "order@10": pc.get("order", {}).get("pass@10"),
            "finset@10": pc.get("finset", {}).get("pass@10"),
            "n_no_verify": m.get("n_no_candidate_verified"), "n": m.get("n_test_theorems")}


def classify(stmt: str, failure_class: str) -> str:
    if failure_class in ("parse_error", "unknown_tactic"):
        return "syntax/parse"
    if failure_class == "unknown_identifier":
        return "lemma_vocabulary"
    if failure_class == "type_mismatch":
        return "proof_shape (API/arity)"
    if failure_class == "shape_miss":
        return "proof_shape (goal not closed)"
    if stmt.count("→") >= 2:
        return "multi-step planning"
    return "insufficient_shape_diversity"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v28_scaling" / "report.json"))
    args = ap.parse_args(argv)

    report: Dict[str, Any] = {"config": "v28_scaling"}
    benches = ["v25_heldout", "v26_holdout", "v27_holdout", "v28_holdout"]
    v28_models = ["v28_general", "v28_set_order_heavy", "v28_category_balanced", "v28_finset_specialist"]
    v27_models = ["v26_base", "v26_widened", "v27_widened", "v27_set_heavy"]

    table: Dict[str, Dict[str, Any]] = {}
    for model in v28_models:
        for bench in benches:
            c = cell(V28, model, bench)
            if c:
                table[f"{model}__{bench}"] = c
    # pull v27-era models from the v28 eval if present (they were re-run), else v27 eval
    for model in v27_models:
        for bench in benches:
            c = cell(V28, model, bench) or cell(V27, model, bench)
            if c:
                table[f"{model}__{bench}"] = c
    report["table"] = table

    # ---- fresh-holdout scaling: v27 best vs v28 best on each fresh bench ----
    def best_over(models, bench):
        best = None
        for m in models:
            c = table.get(f"{m}__{bench}")
            if c and (best is None or (c["pass@10"], c["pass@5"]) > (best["pass@10"], best["pass@5"])):
                best = {**c, "model": m}
        return best

    fresh = {}
    for bench in benches:
        v27b = best_over(v27_models, bench)
        v28b = best_over(v28_models, bench)
        fresh[bench] = {
            "v27_best": {"model": v27b["model"], "pass@10": v27b["pass@10"]} if v27b else None,
            "v28_best": {"model": v28b["model"], "pass@10": v28b["pass@10"]} if v28b else None,
            "delta_pass@10": (round(v28b["pass@10"] - v27b["pass@10"], 4)
                              if v27b and v28b else None)}
    report["fresh_holdout_scaling"] = fresh

    # ---- Set/order continued improvement (best v28 per bench) ----
    report["set_order_per_category"] = {
        bench: {"set@10": (best_over(v28_models, bench) or {}).get("set@10"),
                "order@10": (best_over(v28_models, bench) or {}).get("order@10"),
                "finset@10": (best_over(v28_models, bench) or {}).get("finset@10")}
        for bench in benches}

    # ---- balancing helpful/harmful on v28 holdout ----
    report["balancing_v28_holdout"] = {
        m: (table.get(f"{m}__v28_holdout") or {}).get("pass@10") for m in v28_models}

    # ---- Finset transfer (from the transfer cells in comparison.json) ----
    comp = json.loads((V28 / "comparison.json").read_text()) if (V28 / "comparison.json").exists() else {}
    report["finset_transfer"] = comp.get("transfer", {})

    # ---- remaining failures of the best v28 model on the fresh v28 holdout ----
    seed_stmt = {}
    for bp in (ROOT / "data" / "processed" / "v28_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl",
               ROOT / "data" / "processed" / "v27_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"):
        for s in _read(bp):
            seed_stmt[s["theorem_name"]] = (s["theorem_statement"], s.get("category", "?"))
    residuals = []
    v28_best_model = (best_over(v28_models, "v28_holdout") or {}).get("model", "v28_general")
    for bench in ("v27_holdout", "v28_holdout"):
        m = best_metrics(V28 / f"{v28_best_model}__{bench}")
        if not m:
            continue
        for nm, cls in m.get("no_verify_reason", {}).items():
            stmt, cat = seed_stmt.get(nm, ("", "?"))
            residuals.append({"bench": bench, "theorem": nm, "category": cat,
                              "failure_class": cls, "bucket": classify(stmt, cls)})
    report["v28_best_model"] = v28_best_model
    report["v28_residuals"] = residuals
    report["residual_buckets"] = dict(Counter(r["bucket"] for r in residuals))

    # ---- wall diagnosis ----
    buckets = report["residual_buckets"]
    n_resid = sum(buckets.values())
    data_bound = buckets.get("lemma_vocabulary", 0) + buckets.get("insufficient_shape_diversity", 0)
    shape_bound = buckets.get("proof_shape (API/arity)", 0) + buckets.get("proof_shape (goal not closed)", 0)
    plan_bound = buckets.get("multi-step planning", 0)
    report["wall_diagnosis"] = {
        "n_residuals": n_resid,
        "data_or_vocabulary_bound": data_bound,
        "proof_shape_bound": shape_bound,
        "multi_step_planning_bound": plan_bound,
        "leandojo_next_state_relevant": plan_bound > max(1, n_resid // 3),
        "note": ("residuals dominated by vocab/shape -> still a DATA/coverage regime; "
                 "LeanDojo next-state supervision premature" if plan_bound <= max(1, n_resid // 3)
                 else "multi-step planning now a material share -> proof-state supervision worth exploring"),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[scaling] wrote {out}")
    print("[scaling] fresh-holdout scaling:")
    for b, v in fresh.items():
        print(f"   {b:12s} v27={v['v27_best']} v28={v['v28_best']} delta@10={v['delta_pass@10']}")
    print("[scaling] balancing on v28 holdout:", report["balancing_v28_holdout"])
    print("[scaling] residual buckets:", report["residual_buckets"])
    print("[scaling] wall:", report["wall_diagnosis"]["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
