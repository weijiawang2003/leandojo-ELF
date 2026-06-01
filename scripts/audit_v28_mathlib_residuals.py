"""Mini-ELF v28 — Part 1: residual Mathlib audit.

Starts from the v27 remaining failures (the theorems no v27 specialist config can
get a verifying candidate for at top-10) and classifies each by *why* it fails,
so the v28 corpus can target the real gap rather than guessing.

For every residual theorem it records:
  * theorem name, category, statement;
  * the known-good **expected proof(s)** (Lean-verified, pulled from the v25/v26/v27
    verified corpora — never fed to a model, audit-only reference);
  * the model's current **top-10 candidates** and their Lean **error classes**
    (via the shared ``v25_taxonomy``);
  * a **failure bucket**, one of:
      missing_lemma_vocabulary | wrong_namespace | wrong_api_arity |
      insufficient_shape_diversity | multi_step_planning | impossible_single_tactic

It reads only existing eval artifacts (no Lean run) and writes a JSON report plus a
machine-readable residual list for Part 2 to consume. Special focus families
(mem_inter_iff, union_subset, Set union/inter subset, order transitivity, Finset,
Nat/List vocabulary) are flagged.

Honesty: expected proofs are Lean-verified reference targets, never predictions;
no state_after; reads only existing artifacts.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from evaluate_v25_tierc import v25_taxonomy  # noqa: E402

SPEC = ROOT / "data" / "baselines" / "v27_specialist_eval"

# v27 specialist configs to treat as "the v27 system" (their union of residuals is
# the genuine v27 remaining-failure set).
V27_MODELS = ["v27_widened", "v27_set_heavy", "v27_category_balanced", "v27_base"]
BENCHES = ["v25_heldout", "v26_holdout", "v27_holdout"]

# special-focus families flagged in the v28 plan
FOCUS_KEYS = {
    "mem_inter_iff": ["∩", "↔", "∧"],
    "union_subset": ["∪", "⊆"],
    "subset_inter": ["⊆", "∩"],
    "order_trans": ["≤"],
    "finset": ["Finset"],
}


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _best_pred_file(run_dir: Path) -> Optional[Tuple[str, Path]]:
    """Return (config_name, predictions.jsonl) of the best-pass@5 config in a cell."""
    best = None
    for mf in run_dir.glob("*/metrics.json"):
        m = json.loads(mf.read_text())
        key = (m.get("pass@5", 0), m.get("pass@1", 0))
        if best is None or key > best[0]:
            best = (key, m.get("config"), mf.parent / "predictions.jsonl")
    return (best[1], best[2]) if best else None


def expected_proofs() -> Dict[str, List[str]]:
    """{theorem_name: [verified tactics]} from every Lean-verified corpus."""
    out: Dict[str, List[str]] = defaultdict(list)
    for fn in ("v25_mathlib_tierc_verified.jsonl",
               "v26_mathlib_specialist_verified.jsonl",
               "v26_set_widen_verified.jsonl",
               "v27_mathlib_expanded_verified.jsonl"):
        for r in _read(ROOT / "data" / "traces" / fn):
            t = (r.get("tactic") or "").strip()
            if t and t not in out[r.get("theorem_name", "")]:
                out[r.get("theorem_name", "")].append(t)
    return out


def seed_index() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for bp in (ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl",
               ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout" / "test_seeds.jsonl",
               ROOT / "data" / "processed" / "v27_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"):
        for s in _read(bp):
            out[s["theorem_name"]] = s
    return out


def focus_family(stmt: str) -> Optional[str]:
    for fam, toks in FOCUS_KEYS.items():
        if all(tok in stmt for tok in toks):
            return fam
    return None


def bucket(stmt: str, error_classes: List[str], category: str) -> str:
    """Map the top-10 error-class multiset + statement shape to a failure bucket."""
    cnt = Counter(error_classes)
    # unknown identifier dominating => vocabulary / namespace gap
    if cnt.get("unknown_identifier", 0) >= 1 and cnt.get("unknown_identifier", 0) >= cnt.get("type_mismatch", 0):
        # a dotted lemma name that doesn't resolve = wrong namespace; bare = missing vocab
        return "wrong_namespace" if "." in stmt else "missing_lemma_vocabulary"
    if cnt.get("type_mismatch", 0) >= 1:
        return "wrong_api_arity"
    if cnt.get("parse_error", 0) >= max(2, len(error_classes) // 2):
        # mostly garbled/truncated beams => the model never found the shape
        return "insufficient_shape_diversity"
    # hypothesis-chaining goals with several arrows tend to need planning
    if stmt.count("→") >= 2 or (("h1" in stmt and "h2" in stmt)):
        return "multi_step_planning"
    if cnt.get("shape_miss", 0) >= 1:
        return "insufficient_shape_diversity"
    return "insufficient_shape_diversity"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--spec-dir", default=str(SPEC))
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v28_residual_audit" / "report.json"))
    ap.add_argument("--out-residuals", default=str(ROOT / "data" / "baselines" / "v28_residual_audit" / "residuals.jsonl"))
    args = ap.parse_args(argv)

    spec = Path(args.spec_dir)
    proofs = expected_proofs()
    seeds = seed_index()

    # per (model, bench): best config + its residual theorems (no verified top-10)
    per_cell: Dict[str, Dict[str, Any]] = {}
    residual_by_thm: Dict[str, Dict[str, Any]] = {}
    fail_count: Counter = Counter()  # how many v27 cells each theorem fails in
    cells_seen: Counter = Counter()

    for model in V27_MODELS:
        for bench in BENCHES:
            run = spec / f"{model}__{bench}"
            picked = _best_pred_file(run)
            if not picked:
                continue
            cfg, pf = picked
            preds = _read(pf)
            residuals = [r for r in preds if r.get("first_verified_rank") is None]
            per_cell[f"{model}__{bench}"] = {"config": cfg, "n_theorems": len(preds),
                                             "n_residual": len(residuals),
                                             "residual_theorems": [r["theorem_name"] for r in residuals]}
            for r in residuals:
                nm = r["theorem_name"]
                cells_seen[nm] += 0  # ensure key
                fail_count[nm] += 1
                seed = seeds.get(nm, {})
                stmt = seed.get("theorem_statement", "")
                cat = r.get("category", seed.get("category", "?"))
                errs = [v.get("error") for v in r.get("verifications", [])]
                eclasses = [v25_taxonomy(e) for e in errs]
                rec = {
                    "theorem_name": nm, "category": cat, "bench": bench,
                    "statement": stmt, "expected_proofs": proofs.get(nm, [])[:4],
                    "top10_candidates": r.get("ordering", [])[:10],
                    "top10_error_classes": eclasses,
                    "error_class_counts": dict(Counter(eclasses)),
                    "focus_family": focus_family(stmt),
                    "bucket": bucket(stmt, eclasses, cat),
                }
                # keep the richest record per theorem (prefer one with expected proofs)
                prev = residual_by_thm.get(nm)
                if prev is None or (not prev["expected_proofs"] and rec["expected_proofs"]):
                    residual_by_thm[nm] = rec

    # genuine v27 residual = fails in the best config of EVERY model that covers it
    n_models_per_bench = {b: sum(1 for m in V27_MODELS if f"{m}__{b}" in per_cell) for b in BENCHES}
    hard_in_all = []
    for nm, rec in residual_by_thm.items():
        b = rec["bench"]
        # fails in every model on at least its own bench? approximate via fail_count vs models
        if fail_count[nm] >= n_models_per_bench.get(b, 1):
            hard_in_all.append(nm)

    residuals_sorted = sorted(residual_by_thm.values(),
                              key=lambda r: (r["bench"], r["category"], r["theorem_name"]))
    report = {
        "config": "v28_residual_audit",
        "source": "v27_specialist_eval best-config predictions (no Lean re-run)",
        "v27_models_considered": V27_MODELS,
        "benches": BENCHES,
        "per_cell": per_cell,
        "n_distinct_residual_theorems": len(residual_by_thm),
        "residual_theorems": sorted(residual_by_thm),
        "hard_in_all_v27_configs": sorted(set(hard_in_all)),
        "bucket_counts": dict(Counter(r["bucket"] for r in residuals_sorted)),
        "focus_family_counts": dict(Counter(r["focus_family"] for r in residuals_sorted if r["focus_family"])),
        "by_category": dict(Counter(r["category"] for r in residuals_sorted)),
        "uses_state_after": False, "uses_manual_oracle": False,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    with Path(args.out_residuals).open("w", encoding="utf-8") as f:
        for r in residuals_sorted:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[audit] distinct v27 residual theorems: {len(residual_by_thm)}")
    print(f"[audit] hard in all configs: {report['hard_in_all_v27_configs']}")
    print(f"[audit] buckets: {report['bucket_counts']}")
    print(f"[audit] focus families: {report['focus_family_counts']}")
    for r in residuals_sorted:
        print(f"   {r['bench']:12s} {r['theorem_name']:26s} {r['category']:6s} "
              f"{r['bucket']:28s} focus={r['focus_family']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
