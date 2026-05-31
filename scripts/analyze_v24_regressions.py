"""Mini-ELF v24 — Parts 7/8: residual row-by-row results + regression
analysis.

Compares the v24 broad+residual generator against the v22 plus_exists
generator on the v18 broad-core benchmark (both at `raw` beam order, the
config v23 established as best). Emits:

  * ``V24_RESIDUAL_ROW_RESULTS.md`` — for each of the 8 generator-bound
    theorems: old first-verified rank (None) → new rank + the verifying
    candidate (or why it still fails).
  * ``V24_REGRESSION_ANALYSIS.md``  — per-category pass@k deltas; flags
    any regression on the previously-solved categories
    (forall/implication/bool must stay 1.000; negation ≥ 0.800).

Read-only over generated metrics/predictions; no Lean.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("analyze_v24_regressions")

CATEGORIES = ["implication", "conjunction", "disjunction", "negation",
              "equality_rewrite", "exists", "forall", "nat_succ", "bool", "list"]
PROTECTED = {"forall": 1.0, "implication": 1.0, "bool": 1.0, "negation": 0.8}


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()] if p.exists() else []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v24-eval", default="v24_broad_residual_eval")
    ap.add_argument("--v22-eval", default="v22_general_plus_exists_eval")
    ap.add_argument("--config", default="raw")
    args = ap.parse_args(argv)

    b = ROOT / "data" / "baselines"
    v24 = json.loads((b / args.v24_eval / args.config / "metrics.json").read_text(encoding="utf-8"))
    v22 = json.loads((b / args.v22_eval / args.config / "metrics.json").read_text(encoding="utf-8"))
    v24_raw_preds = {r["theorem_name"]: r for r in
                     _read(b / args.v24_eval / "raw" / "predictions.jsonl")}
    gb = json.loads((b / "v24_generator_bound_rows.json").read_text(encoding="utf-8"))

    # ---- Part 7: row-by-row on the 8 generator-bound theorems ----
    rows = []
    fixed = 0
    for r in gb["rows"]:
        nm = r["theorem_name"]
        pr = v24_raw_preds.get(nm, {})
        fvr = pr.get("first_verified_rank")
        verifying = None
        if fvr is not None:
            verifying = pr["ordering"][fvr]
            fixed += 1
        rows.append({"theorem": nm, "category": r["category"],
                     "old_first_verified_rank": None,
                     "new_first_verified_rank": fvr,
                     "verifying_candidate": verifying,
                     "expected_family": r["proposed_family"],
                     "still_failing_reason": (None if fvr is not None
                                              else "no verified candidate in v24 top-10")})

    # ---- Part 8: per-category regression ----
    deltas = {}
    regressions = []
    for c in CATEGORIES:
        a = v22["per_category"].get(c, {})
        d = v24["per_category"].get(c, {})
        dd = {k: round(d.get(k, 0) - a.get(k, 0), 3) for k in ("pass@1", "pass@5", "pass@10")}
        deltas[c] = {"v22": a, "v24": d, "delta": dd}
        if d.get("pass@5", 0) <= a.get("pass@5", 0) - 0.1:
            regressions.append(c)
        if c in PROTECTED and d.get("pass@5", 0) < PROTECTED[c] - 1e-9:
            if c not in regressions:
                regressions.append(c)

    out = {
        "config": args.config,
        "v24_mean": {k: v24[k] for k in ("pass@1", "pass@5", "pass@10", "MRR",
                                         "n_no_candidate_verified")},
        "v22_mean": {k: v22[k] for k in ("pass@1", "pass@5", "pass@10", "MRR",
                                         "n_no_candidate_verified")},
        "n_residual_fixed": fixed, "n_residual_total": len(rows),
        "per_category": deltas, "regressions": regressions,
        "row_results": rows,
        "protected_held": all(
            v24["per_category"].get(c, {}).get("pass@5", 0) >= thr - 1e-9
            for c, thr in PROTECTED.items()),
        "uses_state_after": False,
    }
    (b / "v24_regression_analysis.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- row-results doc ----
    L = ["# v24 residual row-by-row results (Part 7)\n\n",
         f"The 8 v18 generator-bound theorems, v22 plus_exists → v24 "
         f"broad+residual (`{args.config}` beam order). v22 had **no verified "
         f"candidate in the top-10** for every one of these. **v24 fixes "
         f"{fixed} / {len(rows)}.**\n\n",
         "| theorem | category | old fvr | new fvr | verifying candidate / reason |\n",
         "|---|---|---|---|---|\n"]
    for r in rows:
        cell = (repr(r["verifying_candidate"]) if r["new_first_verified_rank"] is not None
                else r["still_failing_reason"])
        L.append(f"| `{r['theorem']}` | {r['category']} | None | "
                 f"{r['new_first_verified_rank']} | {cell} |\n")
    (ROOT / "docs" / "V24_RESIDUAL_ROW_RESULTS.md").write_text("".join(L), encoding="utf-8")

    # ---- regression doc ----
    R = ["# v24 regression analysis (Part 8)\n\n",
         f"v24 broad+residual vs v22 plus_exists on v18 broad-core "
         f"(`{args.config}`). Mean pass@5 {v22['pass@5']:.3f} → "
         f"{v24['pass@5']:.3f}; pass@10 {v22['pass@10']:.3f} → "
         f"{v24['pass@10']:.3f}; no_verify {v22['n_no_candidate_verified']} → "
         f"{v24['n_no_candidate_verified']}.\n\n",
         "## Per-category pass@5 (v22 → v24, Δ)\n\n| category | v22 | v24 | Δ |\n|---|---:|---:|---:|\n"]
    for c in CATEGORIES:
        a = deltas[c]["v22"].get("pass@5", 0)
        d = deltas[c]["v24"].get("pass@5", 0)
        R.append(f"| {c} | {a:.3f} | {d:.3f} | {d-a:+.3f} |\n")
    R.append(f"\n## Protected categories held (forall/impl/bool=1.0, "
             f"negation≥0.8): **{out['protected_held']}**\n\n")
    R.append(f"## Regressions (pass@5 drop ≥ 0.1 or protected broken): "
             f"**{regressions or 'none'}**\n\n")
    if regressions:
        R.append("A residual-corpus tradeoff was introduced; see deltas above. "
                 "If v24 improves residuals but regresses solved categories, the "
                 "honest options are balanced training or a routed/panel "
                 "fallback for the regressed category.\n")
    else:
        R.append("No category regressed — the targeted residual corpus closed "
                 "generator-bound failures **without** a category tradeoff.\n")
    (ROOT / "docs" / "V24_REGRESSION_ANALYSIS.md").write_text("".join(R), encoding="utf-8")

    logger.info("v24 vs v22 (%s): mean p@5 %.3f→%.3f p@10 %.3f→%.3f no_verify %d→%d; "
                "residual fixed %d/%d; regressions=%s; protected_held=%s",
                args.config, v22["pass@5"], v24["pass@5"], v22["pass@10"],
                v24["pass@10"], v22["n_no_candidate_verified"],
                v24["n_no_candidate_verified"], fixed, len(rows),
                regressions or "none", out["protected_held"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
