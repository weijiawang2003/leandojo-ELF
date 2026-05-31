"""Mini-ELF v27 — Part 8: remaining-failure + data-scaling analysis.

Reads the v27 specialist eval (and v26 eval, corrected-metrics, routed system) and
produces the data-scaling story:
  * v26 -> v27 per-category pass@k deltas (does Set/order keep improving?);
  * specialist vs co-training (v27 vs v25_aug);
  * category balancing helpful or harmful (widened vs category_balanced);
  * remaining failures classified (lemma vocabulary / proof shape / syntax-parse /
    multi-step planning) for the best v27 model;
  * concrete examples for V27_FAILURE_EXAMPLES.md.

Reads only existing artifacts (no Lean). Writes
``data/baselines/v27_data_scaling/report.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data" / "baselines" / "v27_specialist_eval"
V26_SPEC = ROOT / "data" / "baselines" / "v26_specialist_eval"
V26_WIDEN = ROOT / "data" / "baselines" / "v26_widen_eval"


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


def classify_failure(stmt: str, failure_class: str, category: str) -> str:
    s = stmt.lower()
    if failure_class in ("parse_error", "unknown_tactic"):
        return "syntax/parse"
    if failure_class in ("unknown_identifier",):
        return "lemma_vocabulary"
    if failure_class in ("type_mismatch",):
        return "proof_shape (API/arity or wrong term)"
    if failure_class in ("shape_miss",):
        return "proof_shape (tactic ran, goal not closed)"
    # multi-binder hypothesis-chaining goals tend to need planning
    if stmt.count("→") + stmt.count("h1") + stmt.count("h2") >= 2:
        return "multi-step planning"
    return "other"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v27_data_scaling" / "report.json"))
    args = ap.parse_args(argv)

    report: Dict[str, Any] = {"config": "v27_data_scaling"}

    benches = ["v25_heldout", "v26_holdout", "v27_holdout"]
    models = ["v24", "v25_aug", "v26_base", "v26_widened",
              "v27_base", "v27_widened", "v27_category_balanced", "v27_set_heavy"]

    # ---- table: best-config overall + Set/order per-category pass@10 ----
    def cell(model, bench):
        # v26 widened lives in a different eval dir
        if model == "v26_widened":
            d = V26_WIDEN / f"{model}__{bench}"
        elif model in ("v24", "v25_aug", "v26_base", "v26_plus_core") and (V26_SPEC / f"{model}__{bench}").exists():
            d = V26_SPEC / f"{model}__{bench}"
        else:
            d = SPEC / f"{model}__{bench}"
        m = best_metrics(d)
        if not m:
            return None
        pc = m.get("per_category", {})
        return {"best_config": m.get("config"), "pass@1": m.get("pass@1"), "pass@5": m.get("pass@5"),
                "pass@10": m.get("pass@10"), "set@10": pc.get("set", {}).get("pass@10"),
                "order@10": pc.get("order", {}).get("pass@10"),
                "n_no_verify": m.get("n_no_candidate_verified")}
    table: Dict[str, Dict[str, Any]] = {}
    for model in models:
        for bench in benches:
            c = cell(model, bench)
            if c:
                table[f"{model}__{bench}"] = c
    report["table"] = table

    # ---- v26 -> v27 deltas ----
    deltas = {}
    for bench in benches:
        for pair in (("v26_base", "v27_base"), ("v26_widened", "v27_widened")):
            a, b = pair
            ca, cb = table.get(f"{a}__{bench}"), table.get(f"{b}__{bench}")
            if ca and cb:
                deltas[f"{a}->{b}@{bench}"] = {
                    "pass@10": round((cb["pass@10"] or 0) - (ca["pass@10"] or 0), 4),
                    "set@10": (None if ca.get("set@10") is None or cb.get("set@10") is None
                               else round(cb["set@10"] - ca["set@10"], 4)),
                    "order@10": (None if ca.get("order@10") is None or cb.get("order@10") is None
                                 else round(cb["order@10"] - ca["order@10"], 4))}
    report["v26_to_v27_deltas"] = deltas

    # ---- specialist vs co-training ----
    report["specialist_vs_cotraining"] = {
        bench: {"v25_aug(co-train)@10": (table.get(f"v25_aug__{bench}") or {}).get("pass@10"),
                "v27_widened(specialist)@10": (table.get(f"v27_widened__{bench}") or {}).get("pass@10")}
        for bench in benches}

    # ---- balancing helpful/harmful ----
    report["balancing"] = {
        bench: {"v27_widened@10": (table.get(f"v27_widened__{bench}") or {}).get("pass@10"),
                "v27_category_balanced@10": (table.get(f"v27_category_balanced__{bench}") or {}).get("pass@10"),
                "v27_set_heavy@10": (table.get(f"v27_set_heavy__{bench}") or {}).get("pass@10")}
        for bench in benches}

    # ---- remaining failures of the best v27 model (widened) ----
    seed_stmt = {}
    for bp in (ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl",
               ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout" / "test_seeds.jsonl",
               ROOT / "data" / "processed" / "v27_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"):
        for s in _read(bp):
            seed_stmt[s["theorem_name"]] = (s["theorem_statement"], s.get("category", "?"))
    residuals = []
    for bench in benches:
        d = SPEC / f"v27_widened__{bench}"
        m = best_metrics(d)
        if not m:
            continue
        nvr = m.get("no_verify_reason", {})
        for nm, cls in nvr.items():
            stmt, cat = seed_stmt.get(nm, ("", "?"))
            residuals.append({"bench": bench, "theorem": nm, "statement": stmt, "category": cat,
                              "failure_class": cls, "bucket": classify_failure(stmt, cls, cat)})
    report["v27_widened_residuals"] = residuals
    from collections import Counter
    report["residual_buckets"] = dict(Counter(r["bucket"] for r in residuals))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[scaling] wrote {out}")
    print("[scaling] v26->v27 deltas:")
    for k, v in deltas.items():
        print(f"   {k}: p@10 {v['pass@10']:+.3f}  set@10 {v['set@10']}  order@10 {v['order@10']}")
    print("[scaling] residual buckets:", report["residual_buckets"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
