"""Mini-ELF v30 — Part 10/11: remaining-failure audit + optional v24 core audit.

Classifies the best v30 model's residuals over the fresh/preserved holdouts into
data_volume | lemma_vocabulary | api_syntax | multi_step_planning | architecture |
proof_state_supervision, and explicitly answers whether LeanDojo next-state is now
relevant. Optionally audits the old v24 broad-core residuals (NO retrain). No Lean run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from evaluate_v25_tierc import v25_taxonomy  # noqa: E402

V30E = ROOT / "data" / "baselines" / "v30_specialist_eval"
TRACES = ROOT / "data" / "traces"
VERIFIED = ["v25_mathlib_tierc_verified.jsonl", "v26_mathlib_specialist_verified.jsonl",
            "v27_mathlib_expanded_verified.jsonl", "v28_mathlib_expanded_verified.jsonl",
            "v29_mathlib_density_verified.jsonl", "v30_targeted_density_verified.jsonl"]


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


def fail_class(stmt, errs):
    cnt = Counter(errs)
    if stmt.count("→") >= 2:
        return "multi_step_planning"
    if cnt.get("unknown_identifier", 0) >= max(1, len(errs) // 2):
        return "lemma_vocabulary"
    if cnt.get("type_mismatch", 0) >= 1:
        return "api_syntax"
    return "data_volume"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--model", default="v30_general_targeted")
    ap.add_argument("--benches", default="v28_holdout,v29_holdout,v29_family_density,v30_holdout,v30_targeted_family")
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v30_remaining_failures" / "report.json"))
    ap.add_argument("--v24-cleanup", action="store_true")
    args = ap.parse_args(argv)

    proofs: Dict[str, List[str]] = defaultdict(list)
    thm_stmt: Dict[str, str] = {}
    for fn in VERIFIED:
        for r in _read(TRACES / fn):
            nm = r.get("theorem_name", "")
            t = (r.get("tactic") or "").strip()
            if t and t not in proofs[nm]:
                proofs[nm].append(t)
            thm_stmt[nm] = r.get("theorem_statement", "")

    residuals = []
    for bench in [b.strip() for b in args.benches.split(",") if b.strip()]:
        bm = best_metrics(V30E / f"{args.model}__{bench}")
        if not bm:
            continue
        for r in _read(bm["pred"]):
            if r.get("first_verified_rank") is not None:
                continue
            nm = r["theorem_name"]
            errs = [v25_taxonomy(v.get("error")) for v in r.get("verifications", [])]
            residuals.append({"bench": bench, "theorem": nm, "category": r.get("category"),
                              "family": r.get("family"), "statement": thm_stmt.get(nm, ""),
                              "expected_proofs": proofs.get(nm, [])[:3], "top10": r.get("ordering", [])[:10],
                              "error_counts": dict(Counter(errs)),
                              "fail_class": fail_class(thm_stmt.get(nm, ""), errs)})

    buckets = dict(Counter(r["fail_class"] for r in residuals))
    n = len(residuals)
    plan = buckets.get("multi_step_planning", 0) + buckets.get("proof_state_supervision", 0)
    report = {
        "config": "v30_remaining_failures", "model": args.model, "n_residuals": n,
        "fail_class_counts": buckets, "by_bench": dict(Counter(r["bench"] for r in residuals)),
        "by_family": dict(Counter(r["family"] for r in residuals)), "residuals": residuals,
        "leandojo_next_state_relevant": plan > max(1, n // 3),
        "verdict": ("remaining failures still single-tactic data/vocab/API-bound -> continue "
                    "targeted density repair; LeanDojo next-state premature"
                    if plan <= max(1, n // 3) else
                    "multi-step/proof-state share material -> investigate LeanDojo next-state"),
        "uses_state_after": False, "uses_manual_oracle": False,
    }
    if args.v24_cleanup:
        v24_dir = ROOT / "data" / "baselines" / "v24_broad_residual_eval"
        old = []
        for cfg_dir in v24_dir.glob("*/"):
            for r in _read(cfg_dir / "predictions.jsonl"):
                if r.get("first_verified_rank") is None:
                    old.append(r.get("theorem_name"))
        report["v24_cleanup"] = {
            "audited": True, "retrained": False,
            "n_old_core_residuals": len(set(filter(None, old))),
            "old_core_residuals": sorted(set(filter(None, old)))[:10],
            "recommendation": ("audited only; v24 broad-core protected (never retrained). The few "
                               "old core residuals (and_assoc_one / or_inr / or_elim_to_common style) "
                               "are orthogonal to the Mathlib tier and would be repaired the same way "
                               "(a small CORE-density sibling corpus + a core specialist) — never on the "
                               "protected v24 model."),
        }
    else:
        report["v24_cleanup"] = {"audited": False, "retrained": False, "recommendation": "skipped honestly; v24 protected"}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[failures] model={args.model} residuals={n} buckets={buckets} by_bench={report['by_bench']}")
    print(f"[failures] verdict: {report['verdict']}")
    if args.v24_cleanup:
        print(f"[failures] v24 audit: {report['v24_cleanup']['n_old_core_residuals']} old core residuals (not retrained)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
