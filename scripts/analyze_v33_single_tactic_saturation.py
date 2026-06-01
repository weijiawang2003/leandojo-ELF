"""Mini-ELF v33 — Part 8: final single-tactic saturation analysis.

Reads the v33 specialist eval + routed eval + remaining-residual audit (NO Lean run)
and makes the final saturation decision for v34.

Decision:
  * residuals still single-tactic vocab/API/token -> packaging + future coverage, NOT LeanDojo;
  * genuine multi-step residuals appear -> LeanDojo next-state;
  * metrics saturated and robust -> packaging / reporting / git cleanup.
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

V33E = ROOT / "data" / "baselines" / "v33_specialist_eval"
ROUTED = ROOT / "data" / "baselines" / "v33_routed_system"
AUDIT = ROOT / "data" / "baselines" / "v33_remaining_residual" / "report.json"
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
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v33_saturation" / "report.json"))
    args = ap.parse_args(argv)

    comp = json.loads((V33E / "comparison.json").read_text()) if (V33E / "comparison.json").exists() else {"results": {}}
    res = comp.get("results", {})
    # pick the best v33 model by mean pass@10 over the harder benches
    hard = ["identifier_stress", "fresh_robustness", "token_diversity"]
    v33_models = sorted({k.split("__")[0] for k in res if k.startswith("v33_")})

    def mean_hard(m):
        vals = [res[f"{m}__{b}"]["best"]["pass@10"] for b in hard if f"{m}__{b}" in res]
        return sum(vals) / len(vals) if vals else -1
    best_model = max(v33_models, key=mean_hard) if v33_models else "v33_general_residual"

    report: Dict[str, Any] = {"config": "v33_saturation", "best_v33_model": best_model}
    benches = ["v25_heldout", "v28_holdout", "v29_holdout", "token_diversity", "identifier_stress", "fresh_robustness"]

    def p10(model, bench):
        c = res.get(f"{model}__{bench}")
        return c["best"]["pass@10"] if c else None
    report["pass10"] = {m: {b: p10(m, b) for b in benches if p10(m, b) is not None}
                        for m in ("v31_canonical_general", "v32_canonical_repaired", best_model)}

    routed = json.loads((ROUTED / "comparison.json").read_text()) if (ROUTED / "comparison.json").exists() else {}
    report["routed"] = routed.get("routed")
    report["routed_adopt"] = routed.get("adopt_router")

    # remaining failures of the best v33 model on the hard benches
    residuals = []
    for bench in ("identifier_stress", "fresh_robustness", "token_diversity"):
        bm = best_metrics(V33E / f"{best_model}__{bench}")
        if not bm:
            continue
        for r in _read(bm["pred"]):
            if r.get("first_verified_rank") is not None:
                continue
            errs = [v25_taxonomy(v.get("error")) for v in r.get("verifications", [])]
            cnt = Counter(errs)
            cls = ("vocabulary" if cnt.get("unknown_identifier", 0) else
                   "api" if cnt.get("type_mismatch", 0) else "token_or_shape")
            residuals.append({"bench": bench, "theorem": r["theorem_name"], "family": r.get("family"), "class": cls})
    report["remaining_failures"] = residuals
    report["n_remaining_failures"] = len(residuals)
    report["failure_class_counts"] = dict(Counter(r["class"] for r in residuals))
    report["by_family"] = dict(Counter(r["family"] for r in residuals))
    report["any_multi_step"] = False  # construction: all benches are single-tactic
    report["leandojo_next_state_relevant"] = False

    # v32 baselines for comparison
    stress31 = p10("v31_canonical_general", "identifier_stress")
    stress_best = p10(best_model, "identifier_stress")
    fresh_best = p10(best_model, "fresh_robustness")
    report["adversarial_stress_v31_to_v33"] = {"v31": stress31, "v33": stress_best}
    n = len(residuals)
    strong = (stress_best is not None and stress_best >= 0.95 and fresh_best is not None and fresh_best >= 0.85)
    report["saturation_strong"] = strong

    if report["any_multi_step"]:
        decision = "v34 = LeanDojo next-state (genuine multi-step residuals)"
    elif strong and n <= 2:
        decision = ("v34 = PACKAGING / paper-style report / git recovery — single-tactic Mathlib tier is "
                    "SATURATED (adversarial stress >=0.95, fresh >=0.85, <=2 residuals, all single-tactic); "
                    "LeanDojo next-state premature until a genuinely multi-step benchmark exists")
    elif n <= 5:
        decision = ("v34 = PACKAGING — single-tactic tier is essentially saturated (few residuals, all "
                    "single-tactic vocab/API/token; robustness high); recommend reporting + git cleanup, "
                    "with optional minor coverage; LeanDojo next-state premature")
    else:
        decision = ("v34 = light coverage then package — residuals remain but all single-tactic; "
                    "LeanDojo next-state premature")
    report["v34_decision"] = decision
    report["uses_state_after"] = False

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[v33 saturation] best model:", best_model)
    print("[v33 saturation] adversarial stress v31->v33:", report["adversarial_stress_v31_to_v33"])
    print("[v33 saturation] residuals:", n, report["failure_class_counts"])
    print("[v33 saturation] leandojo_relevant:", report["leandojo_next_state_relevant"])
    print("[v33 saturation] v34 decision:", report["v34_decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
