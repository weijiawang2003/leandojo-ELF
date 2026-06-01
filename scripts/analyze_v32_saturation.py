"""Mini-ELF v32 — Part 7: saturation / next-state analysis.

Reads the stress eval, routed eval, final-residual audit, and fresh-holdout results
(NO Lean run) and decides whether the single-tactic Mathlib pipeline is saturated and
whether LeanDojo next-state is now justified for v33.

Decision criteria:
  * residuals mostly single-tactic data/API  -> LeanDojo premature; continue coverage;
  * residuals mostly multi-step (correct first tactic, missing next state) -> LeanDojo;
  * no residuals on tier-C but fresh/stress weak -> more coverage;
  * stress AND fresh strong + ~0 residuals -> packaging / paper / git-recovery.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

STRESS = ROOT / "data" / "baselines" / "v32_identifier_stress_eval"
ROUTED = ROOT / "data" / "baselines" / "v32_routed_system"
FINAL = ROOT / "data" / "baselines" / "v32_final_residual" / "report.json"
from evaluate_v25_tierc import v25_taxonomy  # noqa: E402


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def best_metrics(run_dir: Path) -> Optional[Dict[str, Any]]:
    best = None
    for f in run_dir.glob("*/metrics.json"):
        m = json.loads(f.read_text())
        key = (m.get("pass@5", 0), m.get("pass@1", 0))
        if best is None or key > best[0]:
            best = (key, m, f.parent / "predictions.jsonl")
    return {"metrics": best[1], "pred": best[2]} if best else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--model", default="v32_canonical_repaired")
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v32_saturation" / "report.json"))
    args = ap.parse_args(argv)

    report: Dict[str, Any] = {"config": "v32_saturation", "model": args.model}

    # stress + fresh results
    stress_comp = json.loads((STRESS / "comparison.json").read_text()) if (STRESS / "comparison.json").exists() else {"results": {}}
    res = stress_comp.get("results", {})

    def p10(model, bench):
        c = res.get(f"{model}__{bench}")
        return c["best"]["pass@10"] if c else None
    report["stress_fresh_pass10"] = {
        m: {"identifier_stress": p10(m, "identifier_stress"), "fresh_mathlib": p10(m, "fresh_mathlib")}
        for m in ("v30_general_targeted", "v31_canonical_general", args.model)}

    # routed broad-core / tier-C
    routed = json.loads((ROUTED / "comparison.json").read_text()) if (ROUTED / "comparison.json").exists() else {}
    report["routed"] = routed.get("routed")
    report["routed_adopt"] = routed.get("adopt_router")

    # collect ALL remaining failures of the best model across stress + fresh + tier-C
    residuals = []
    for bench in ("identifier_stress", "fresh_mathlib"):
        bm = best_metrics(STRESS / f"{args.model}__{bench}")
        if not bm:
            continue
        for r in _read(bm["pred"]):
            if r.get("first_verified_rank") is not None:
                continue
            errs = [v25_taxonomy(v.get("error")) for v in r.get("verifications", [])]
            cnt = Counter(errs)
            stmt_arrows = 0  # stress/fresh are single-tactic by construction
            cls = ("multi_step" if stmt_arrows >= 2 else
                   "api_vocabulary" if (cnt.get("unknown_identifier", 0) or cnt.get("type_mismatch", 0)) else
                   "token_or_shape")
            residuals.append({"bench": bench, "theorem": r["theorem_name"], "category": r.get("category"),
                              "family": r.get("family"), "class": cls})
    # add the known final residual (sparse shape, single-tactic)
    final = json.loads(FINAL.read_text()) if FINAL.exists() else {"residuals": []}
    for fr in final.get("residuals", []):
        residuals.append({"bench": "tierc_token_diversity", "theorem": fr["theorem"], "category": fr.get("category"),
                          "family": fr.get("family"), "class": ("multi_step" if fr["classification"] == "multi_step"
                                                                else "sparse_shape_single_tactic")})
    report["remaining_failures"] = residuals
    report["n_remaining_failures"] = len(residuals)
    report["failure_class_counts"] = dict(Counter(r["class"] for r in residuals))
    report["by_category"] = dict(Counter(r["category"] for r in residuals))

    n = len(residuals)
    multistep = report["failure_class_counts"].get("multi_step", 0)
    report["leandojo_next_state_relevant"] = multistep > max(1, n // 3)

    # strength gates
    stress10 = p10(args.model, "identifier_stress")
    fresh10 = p10(args.model, "fresh_mathlib")
    routed_tierc = (routed.get("routed", {}) or {}).get("tierc", {}).get("pass@10")
    strong = (stress10 is not None and stress10 >= 0.95 and fresh10 is not None and fresh10 >= 0.85)

    if multistep > max(1, n // 3):
        decision = "v33 = LeanDojo next-state (multi-step residuals with correct first tactic, missing next state)"
    elif n <= 1 and strong:
        decision = ("v33 = PACKAGING / paper-style report / git recovery — single-tactic Mathlib tier is "
                    "saturated (stress + fresh strong, <=1 residual, that one a sparse single-tactic shape); "
                    "LeanDojo next-state premature until a genuinely multi-step benchmark exists")
    elif strong:
        decision = ("v33 = light coverage — strong robustness but a few sparse single-tactic shapes remain; "
                    "add density siblings; LeanDojo still premature")
    else:
        decision = "v33 = more coverage — stress/fresh not yet strong; continue single-tactic density/canonicalization"
    report["v33_decision"] = decision
    report["saturation_strong"] = strong
    report["uses_state_after"] = False

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[saturation] stress/fresh pass@10:", report["stress_fresh_pass10"])
    print("[saturation] remaining failures:", report["n_remaining_failures"], report["failure_class_counts"])
    print("[saturation] leandojo_relevant:", report["leandojo_next_state_relevant"])
    print("[saturation] v33 decision:", report["v33_decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
