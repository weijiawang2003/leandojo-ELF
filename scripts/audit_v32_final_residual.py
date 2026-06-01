"""Mini-ELF v32 — Part 1: final-residual audit.

After v31 the best specialist (`v31_canonical_general`) has a single residual. This
script locates it from the v31 normalized eval and produces a definitive record: the
statement, the model's top-10, the Lean error class, the canonical map, the family
density and token coverage in training, similar verified train rows, and a
classification:

  absent_from_beam | ranked_below_top10 | canonicalization_failure | api_arity |
  multi_step | missing_lemma | sparse_shape_single_tactic

A separate Lean probe (run once, recorded here) established that the residual
`(∅ : Set α) ∩ s ⊆ t` is **single-tactic** (`simp` closes it), so it is a
sparse-shape / density gap on the single-tactic tier — NOT a multi-step / proof-state
limit. No Lean run in this script (reads existing eval + corpora).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mini_elf_lean.v31_identifier_normalization import build_canonical_map, tactic_pattern  # noqa: E402
from audit_v29_family_density import family_of  # noqa: E402
from evaluate_v25_tierc import v25_taxonomy  # noqa: E402

V31E = ROOT / "data" / "baselines" / "v31_normalized_eval"
V31_TRAIN = ROOT / "data" / "processed" / "v31_canonical_mathlib" / "configs" / "canonical_general_train_rows.jsonl"
V30_TRAIN = ROOT / "data" / "processed" / "v30_mathlib_specialist" / "configs" / "v30_general_targeted_train_rows.jsonl"
TRACES = ROOT / "data" / "traces"
VERIFIED = ["v25_mathlib_tierc_verified.jsonl", "v26_mathlib_specialist_verified.jsonl",
            "v27_mathlib_expanded_verified.jsonl", "v28_mathlib_expanded_verified.jsonl",
            "v29_mathlib_density_verified.jsonl", "v30_targeted_density_verified.jsonl"]
# Recorded from the Part-1 Lean probe (single-tactic confirmation).
SINGLE_TACTIC_PROBE = {
    "v30_set_empty_inter_subset": {
        "statement": "(α : Type) (s t : Set α) : (∅ : Set α) ∩ s ⊆ t",
        "verified_single_tactics": ["simp", "intro x hx; cases hx.1", "intro x hx; simp at hx",
                                    "intro x hx; exact hx.1.elim"],
        "is_single_tactic": True,
    }
}


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def best_pred(run_dir: Path) -> Optional[Path]:
    best = None
    for mf in run_dir.glob("*/metrics.json"):
        m = json.loads(mf.read_text())
        key = (m.get("pass@5", 0), m.get("pass@1", 0))
        if best is None or key > best[0]:
            best = (key, mf.parent / "predictions.jsonl")
    return best[1] if best else None


def classify(rec: Dict[str, Any]) -> str:
    if rec["theorem"] in SINGLE_TACTIC_PROBE and SINGLE_TACTIC_PROBE[rec["theorem"]]["is_single_tactic"]:
        if rec["correct_pattern_in_train"]:
            return "ranked_below_top10" if rec["correct_present_in_beam"] else "sparse_shape_single_tactic"
        return "sparse_shape_single_tactic"
    cnt = Counter(rec["error_classes"])
    if rec.get("statement", "").count("→") >= 2:
        return "multi_step"
    if cnt.get("type_mismatch", 0) >= 1:
        return "api_arity"
    if cnt.get("unknown_identifier", 0) >= 1:
        return "missing_lemma"
    return "absent_from_beam"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--model", default="v31_canonical_general")
    ap.add_argument("--benches", default="v25_heldout,v26_holdout,v27_holdout,v28_holdout,v29_holdout,v30_targeted_family,token_diversity")
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v32_final_residual" / "report.json"))
    args = ap.parse_args(argv)

    # expected proofs + family train coverage
    proofs: Dict[str, List[str]] = defaultdict(list)
    for fn in VERIFIED:
        for r in _read(TRACES / fn):
            t = (r.get("tactic") or "").strip()
            if t and t not in proofs[r.get("theorem_name", "")]:
                proofs[r.get("theorem_name", "")].append(t)
    fam_train_rows: Dict[str, List[str]] = defaultdict(list)
    fam_patterns: Dict[str, set] = defaultdict(set)
    for src in (V31_TRAIN, V30_TRAIN):
        for r in _read(src):
            fam = family_of(r)
            fam_train_rows[fam].append(r.get("theorem_name", ""))
            fam_patterns[fam].add(tactic_pattern((r.get("tactic") or "").strip()))

    residuals = []
    for bench in [b.strip() for b in args.benches.split(",") if b.strip()]:
        pf = best_pred(V31E / f"{args.model}__{bench}")
        if not pf:
            continue
        for r in _read(pf):
            if r.get("first_verified_rank") is not None:
                continue
            nm = r["theorem_name"]
            stmt = SINGLE_TACTIC_PROBE.get(nm, {}).get("statement", "")
            fam = r.get("family", "?")
            beam = r.get("ordering", [])[:10]
            errs = [v25_taxonomy(v.get("error")) for v in r.get("verifications", [])]
            expected = proofs.get(nm, []) or SINGLE_TACTIC_PROBE.get(nm, {}).get("verified_single_tactics", [])
            exp_patterns = {tactic_pattern(e) for e in expected}
            cmap = build_canonical_map(stmt) if stmt else None
            rec = {
                "bench": bench, "theorem": nm, "category": r.get("category"), "family": fam,
                "statement": stmt, "expected_proofs": expected[:4],
                "top10_candidates": beam, "error_classes": errs, "error_counts": dict(Counter(errs)),
                "correct_present_in_beam": any(e.strip() in [c.strip() for c in beam] for e in expected),
                "correct_pattern_in_train": bool(exp_patterns & fam_patterns.get(fam, set())),
                "family_train_siblings": len(set(fam_train_rows.get(fam, []))),
                "token_surface": {"tactic_patterns_expected": sorted(exp_patterns)},
                "canonical_map": (cmap.real_to_canon if cmap and cmap.ok else None),
                "similar_train_rows_in_family": sorted(set(fam_train_rows.get(fam, [])))[:8],
                "single_tactic_probe": SINGLE_TACTIC_PROBE.get(nm),
            }
            rec["classification"] = classify(rec)
            residuals.append(rec)

    report = {
        "config": "v32_final_residual_audit", "model": args.model,
        "source": "v31 normalized eval + verified corpora + recorded single-tactic Lean probe",
        "n_residuals": len(residuals), "residuals": residuals,
        "classification_counts": dict(Counter(r["classification"] for r in residuals)),
        "is_multi_step": any(r["classification"] == "multi_step" for r in residuals),
        "leandojo_justified_by_residual": any(r["classification"] in ("multi_step",) for r in residuals),
        "uses_state_after": False, "uses_manual_oracle": False,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[final-residual] model={args.model} residuals={len(residuals)} classes={report['classification_counts']}")
    for r in residuals:
        print(f"   {r['theorem']} [{r['family']}] -> {r['classification']}")
        print(f"     stmt: {r['statement']}")
        print(f"     family_train_siblings={r['family_train_siblings']} correct_pattern_in_train={r['correct_pattern_in_train']}")
        print(f"     top10[:5]={r['top10_candidates'][:5]}")
    print(f"[final-residual] leandojo_justified_by_residual={report['leandojo_justified_by_residual']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
