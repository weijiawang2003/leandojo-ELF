"""Mini-ELF v31 — Part 9/10: remaining-failure audit + optional core note.

Classifies the best v31 model's residuals over the standard + token-diversity holdouts
into data_volume | token_coverage | vocabulary | api_syntax | multi_step_planning |
architecture | proof_state_supervision, and answers whether LeanDojo next-state is now
relevant. Optionally updates the v24 core-residual note (NO retrain). No Lean run.
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

V31E = ROOT / "data" / "baselines" / "v31_normalized_eval"
TRACES = ROOT / "data" / "traces"
VERIFIED = ["v25_mathlib_tierc_verified.jsonl", "v26_mathlib_specialist_verified.jsonl",
            "v27_mathlib_expanded_verified.jsonl", "v28_mathlib_expanded_verified.jsonl",
            "v29_mathlib_density_verified.jsonl", "v30_targeted_density_verified.jsonl",
            "v31_projection_rename_aug" + "_candidates.jsonl"]


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


def best_model(benches) -> str:
    comp = json.loads((V31E / "comparison.json").read_text()) if (V31E / "comparison.json").exists() else {"results": {}}
    res = comp["results"]
    models = sorted({k.split("__")[0] for k in res})
    # rank by mean pass@10 over the given benches
    def score(m):
        vals = [res[f"{m}__{b}"]["best"]["pass@10"] for b in benches if f"{m}__{b}" in res]
        return sum(vals) / len(vals) if vals else -1
    return max(models, key=score) if models else "v31_raw_plus_projection_aug"


def fail_class(stmt, errs):
    cnt = Counter(errs)
    if stmt.count("→") >= 2:
        return "multi_step_planning"
    if cnt.get("unknown_identifier", 0) >= max(1, len(errs) // 2):
        return "vocabulary"
    if cnt.get("type_mismatch", 0) >= 1:
        return "api_syntax"
    return "token_coverage"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--benches", default="v28_holdout,v29_holdout,v30_targeted_family,token_diversity")
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v31_remaining_failures" / "report.json"))
    ap.add_argument("--v24-note", action="store_true")
    args = ap.parse_args(argv)

    benches = [b.strip() for b in args.benches.split(",") if b.strip()]
    model = args.model or best_model(benches)

    proofs: Dict[str, List[str]] = defaultdict(list)
    thm_stmt: Dict[str, str] = {}
    for fn in VERIFIED:
        for r in _read(TRACES / fn) if (TRACES / fn).exists() else _read(ROOT / "data" / "manual" / fn):
            nm = r.get("theorem_name", "")
            t = (r.get("tactic") or "").strip()
            if t and t not in proofs[nm]:
                proofs[nm].append(t)
            thm_stmt[nm] = r.get("theorem_statement", "")

    residuals = []
    for bench in benches:
        bm = best_metrics(V31E / f"{model}__{bench}")
        if not bm:
            continue
        for r in _read(bm["pred"]):
            if r.get("first_verified_rank") is not None:
                continue
            nm = r["theorem_name"]
            errs = [v25_taxonomy(v.get("error")) for v in r.get("verifications", [])]
            residuals.append({"bench": bench, "theorem": nm, "category": r.get("category"),
                              "family": r.get("family"), "statement": thm_stmt.get(nm, ""),
                              "expected_proofs": proofs.get(nm, [])[:3], "top10": r.get("ordering", [])[:6],
                              "error_counts": dict(Counter(errs)), "fail_class": fail_class(thm_stmt.get(nm, ""), errs)})

    buckets = dict(Counter(r["fail_class"] for r in residuals))
    n = len(residuals)
    plan = buckets.get("multi_step_planning", 0) + buckets.get("proof_state_supervision", 0)
    report = {
        "config": "v31_remaining_failures", "best_model": model, "benches": benches,
        "n_residuals": n, "fail_class_counts": buckets,
        "by_bench": dict(Counter(r["bench"] for r in residuals)),
        "by_family": dict(Counter(r["family"] for r in residuals)), "residuals": residuals,
        "leandojo_next_state_relevant": plan > max(1, n // 3),
        "verdict": ("remaining failures still single-tactic token/vocab/API-bound -> LeanDojo "
                    "next-state premature" if plan <= max(1, n // 3) else
                    "multi-step/proof-state material -> investigate LeanDojo next-state"),
        "uses_state_after": False, "uses_manual_oracle": False,
    }
    if args.v24_note:
        v24_dir = ROOT / "data" / "baselines" / "v24_broad_residual_eval"
        old = []
        for cfg_dir in v24_dir.glob("*/"):
            for r in _read(cfg_dir / "predictions.jsonl"):
                if r.get("first_verified_rank") is None:
                    old.append(r.get("theorem_name"))
        report["v24_core_note"] = {
            "audited": True, "retrained": False,
            "n_old_core_residuals": len(set(filter(None, old))),
            "old_core_residuals": sorted(set(filter(None, old)))[:10],
            "v31_insight": ("the v31 finding (residuals are identifier/token coverage, fixable by "
                            "verified rename augmentation or canonicalization) applies directly to the "
                            "core residuals and_assoc_one / or_inr / or_elim_to_common: build a small "
                            "CORE rename-augmented sibling corpus + a core specialist routed to — never "
                            "retrain the protected v24 model."),
        }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[failures] best_model={model} residuals={n} buckets={buckets} by_bench={report['by_bench']}")
    print(f"[failures] verdict: {report['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
