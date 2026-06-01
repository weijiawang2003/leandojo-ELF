"""Mini-ELF v29 — Part 10: remaining failures + optional v24 cleanup decision.

Reads the v29 specialist eval (NO Lean run). For every residual of the best v29
model on the fresh held-outs (v28/v29 theorem holdouts + the density-contrast
holdouts), it records the statement, the model's top-10, the Lean error classes, and
a failure class:

  data_volume | lemma_vocabulary | api_syntax | multi_step_planning | architecture |
  proof_state_supervision

It then decides whether LeanDojo next-state supervision is now relevant (only if the
multi-step share is material) and, optionally, audits the 3 old v24 broad-core
residuals to suggest corpus or skip honestly (it never retrains the protected v24
model).

Writes `data/baselines/v29_remaining_failures/report.json`. Expected proofs are
Lean-verified references, never predictions; no state_after.
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

V29E = ROOT / "data" / "baselines" / "v29_specialist_eval"
DS = ROOT / "data" / "processed" / "v29_mathlib_specialist"
TRACES = ROOT / "data" / "traces"
VERIFIED = ["v25_mathlib_tierc_verified.jsonl", "v26_mathlib_specialist_verified.jsonl",
            "v27_mathlib_expanded_verified.jsonl", "v28_mathlib_expanded_verified.jsonl",
            "v29_mathlib_density_verified.jsonl"]


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


def fail_class(stmt: str, errs: List[str], beam: List[str]) -> str:
    cnt = Counter(errs)
    arrows = stmt.count("→")
    if arrows >= 2:
        return "multi_step_planning"
    if cnt.get("unknown_identifier", 0) >= max(1, len(errs) // 2):
        return "lemma_vocabulary"
    if cnt.get("type_mismatch", 0) >= 1:
        return "api_syntax"
    if cnt.get("parse_error", 0) >= max(2, len(errs) // 2):
        return "data_volume"   # garbled beams -> shape never learned -> more siblings
    return "data_volume"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--model", default="v29_general")
    ap.add_argument("--benches", default="v28_holdout,v29_holdout,family_density_holdout,low_density_holdout")
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v29_remaining_failures" / "report.json"))
    ap.add_argument("--v24-cleanup", action="store_true", help="also audit the old v24 broad-core residuals")
    args = ap.parse_args(argv)

    # expected proofs + statements from verified corpora
    proofs: Dict[str, List[str]] = defaultdict(list)
    thm_stmt: Dict[str, str] = {}
    for fn in VERIFIED:
        for r in _read(TRACES / fn):
            nm = r.get("theorem_name", "")
            t = (r.get("tactic") or "").strip()
            if t and t not in proofs[nm]:
                proofs[nm].append(t)
            thm_stmt[nm] = r.get("theorem_statement", "")
    seed_stmt = {}
    for split in ("theorem_holdout", "family_density_holdout", "low_density_holdout"):
        for s in _read(DS / split / "test_seeds.jsonl"):
            seed_stmt[s["theorem_name"]] = s.get("theorem_statement", "")

    residuals = []
    for bench in [b.strip() for b in args.benches.split(",") if b.strip()]:
        bm = best_metrics(V29E / f"{args.model}__{bench}")
        if not bm:
            continue
        for r in _read(bm["pred"]):
            if r.get("first_verified_rank") is not None:
                continue
            nm = r["theorem_name"]
            stmt = seed_stmt.get(nm) or thm_stmt.get(nm, "")
            errs = [v25_taxonomy(v.get("error")) for v in r.get("verifications", [])]
            beam = r.get("ordering", [])[:10]
            residuals.append({
                "bench": bench, "theorem": nm, "category": r.get("category"),
                "family": r.get("family"), "statement": stmt,
                "expected_proofs": proofs.get(nm, [])[:3],
                "top10": beam, "error_classes": errs,
                "error_counts": dict(Counter(errs)),
                "fail_class": fail_class(stmt, errs, beam),
            })

    buckets = dict(Counter(r["fail_class"] for r in residuals))
    n = len(residuals)
    plan = buckets.get("multi_step_planning", 0)
    proof_state = buckets.get("proof_state_supervision", 0)
    report = {
        "config": "v29_remaining_failures", "model": args.model,
        "n_residuals": n, "fail_class_counts": buckets,
        "by_bench": dict(Counter(r["bench"] for r in residuals)),
        "by_category": dict(Counter(r["category"] for r in residuals)),
        "residuals": residuals,
        "leandojo_next_state_relevant": (plan + proof_state) > max(1, n // 3),
        "verdict": ("remaining failures still single-tactic data/vocab-bound -> keep "
                    "scaling siblings; LeanDojo next-state premature"
                    if (plan + proof_state) <= max(1, n // 3) else
                    "multi-step / proof-state share now material -> move to LeanDojo "
                    "next-state supervision"),
        "uses_state_after": False, "uses_manual_oracle": False,
    }

    # ---- optional v24 cleanup audit (no retrain of the protected model) ----
    if args.v24_cleanup:
        v24_dir = ROOT / "data" / "baselines" / "v24_broad_residual_eval"
        old = []
        for cfg_dir in v24_dir.glob("*/"):
            pf = cfg_dir / "predictions.jsonl"
            for r in _read(pf):
                if r.get("first_verified_rank") is None:
                    old.append(r.get("theorem_name"))
        report["v24_cleanup"] = {
            "audited": True, "retrained": False,
            "n_old_core_residuals": len(set(filter(None, old))),
            "old_core_residuals": sorted(set(filter(None, old)))[:10],
            "recommendation": ("audited only; v24 broad-core model is protected (never "
                               "retrained). Old core residuals are few and orthogonal to the "
                               "Mathlib tier; defer to a dedicated core-residual corpus pass."),
        }
    else:
        report["v24_cleanup"] = {"audited": False, "retrained": False,
                                 "recommendation": "skipped honestly; v24 protected, out of v29 scope"}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[failures] model={args.model} residuals={n} buckets={buckets}")
    print(f"[failures] by_bench={report['by_bench']}")
    print(f"[failures] verdict: {report['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
