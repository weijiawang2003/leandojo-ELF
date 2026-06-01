"""Mini-ELF v33 — Part 1: remaining-residual audit.

Audits the 11 v32 residuals (from the v32 stress + fresh + token-diversity evals),
classifying each and proposing the minimal repair. NO Lean run (reads existing eval +
the saturation report + the now-hardened canonicalizer for the canonical-map column).

Classification:
  vocabulary_gap | api_arity_gap | projection_direction_gap | theorem_shape_density_gap |
  canonicalization_gap | true_multi_step_gap
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mini_elf_lean.v31_identifier_normalization import build_canonical_map, parse_binders  # noqa: E402
from evaluate_v25_tierc import v25_taxonomy  # noqa: E402

SAT = ROOT / "data" / "baselines" / "v32_saturation" / "report.json"
STRESS_EVAL = ROOT / "data" / "baselines" / "v32_identifier_stress_eval"
FINAL = ROOT / "data" / "baselines" / "v32_final_residual" / "report.json"
SEEDS = [ROOT / "data" / "seeds" / "v32_identifier_stress_seeds.jsonl",
         ROOT / "data" / "seeds" / "v32_fresh_mathlib_holdout_seeds.jsonl"]
GOLD = [ROOT / "data" / "manual" / "v32_identifier_stress_candidates.jsonl",
        ROOT / "data" / "manual" / "v32_fresh_mathlib_holdout_candidates.jsonl"]

# the v33 levers per residual family
REPAIR = {
    "set::mem_inter_proj": ("canonicalization_gap", "subscript identifier `proof₁` now parses (hardened decode); + projection siblings"),
    "set::mem_union_intro": ("canonicalization_gap", "subscript identifier now parses; + union-intro siblings"),
    "finset::mem_inter_proj": ("canonicalization_gap", "subscript identifier now parses; + finset projection siblings"),
    "finset::mem_union_intro": ("canonicalization_gap", "subscript identifier now parses; + finset union siblings"),
    "set::inter_assoc": ("theorem_shape_density_gap", "add `inter_assoc`/`union_assoc` siblings (Set.inter_assoc / simp [and_assoc])"),
    "order::le_trans": ("theorem_shape_density_gap", "add 3-4 hop le_trans chains (le_trans (le_trans h1 h2) h3)"),
    "order::min_max": ("vocabulary_gap", "add min_comm/max_comm siblings (min_comm a b / max_comm a b)"),
    "order::lattice": ("vocabulary_gap", "add inf_comm/sup_comm siblings (inf_comm a b / sup_comm a b)"),
    "set::empty_subset": ("theorem_shape_density_gap", "the ∅∩ shape (v32 added 37; the canonical model should now generalize)"),
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v33_remaining_residual" / "report.json"))
    args = ap.parse_args(argv)

    sat = json.loads(SAT.read_text()) if SAT.exists() else {"remaining_failures": []}
    seed_idx = {}
    for sp in SEEDS:
        for s in _read(sp):
            seed_idx[s["theorem_name"]] = s
    gold = {}
    for gp in GOLD:
        for g in _read(gp):
            gold.setdefault(g["theorem_name"], []).append(g.get("tactic", ""))
    # best v32 predictions per bench
    pred_idx = {}
    for bench in ("identifier_stress", "fresh_mathlib"):
        pf = best_pred(STRESS_EVAL / f"v32_canonical_repaired__{bench}")
        if pf:
            for r in _read(pf):
                pred_idx[r["theorem_name"]] = r
    final = json.loads(FINAL.read_text()) if FINAL.exists() else {"residuals": []}
    final_stmt = {r["theorem"]: r["statement"] for r in final.get("residuals", [])}

    audits = []
    for x in sat.get("remaining_failures", []):
        nm = x["theorem"]; fam = x["family"]
        seed = seed_idx.get(nm, {})
        stmt = seed.get("theorem_statement") or final_stmt.get(nm, "")
        pred = pred_idx.get(nm, {})
        beam = pred.get("ordering", [])[:8]
        errs = [v25_taxonomy(v.get("error")) for v in pred.get("verifications", [])]
        cmap = build_canonical_map(stmt) if stmt else None
        cls, proposal = REPAIR.get(fam, ("theorem_shape_density_gap", "add verified siblings"))
        audits.append({
            "theorem": nm, "category": x["category"], "family": fam, "bench": x["bench"],
            "statement": stmt, "expected_proofs": gold.get(nm, [])[:3],
            "v32_top8": beam, "error_classes": errs, "error_counts": dict(Counter(errs)),
            "binders_parsed": parse_binders(stmt) if stmt else [],
            "canonical_map": (cmap.real_to_canon if cmap and cmap.ok else None),
            "classification": cls, "minimal_repair_proposal": proposal,
        })

    report = {
        "config": "v33_remaining_residual_audit", "n_residuals": len(audits),
        "classification_counts": dict(Counter(a["classification"] for a in audits)),
        "by_family": dict(Counter(a["family"] for a in audits)),
        "any_multi_step": any(a["classification"] == "true_multi_step_gap" for a in audits),
        "audits": audits,
        "v33_levers": {"hardened_canonical_decode": "subscript/superscript identifiers now parse (proof₁, h₂, f¹)",
                       "residual_coverage_corpus": "inter_assoc, le_trans chains, min/max/inf_comm, ∅∩ siblings"},
        "uses_state_after": False, "uses_manual_oracle": False,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[v33 residual audit] residuals={len(audits)} classes={report['classification_counts']}")
    print(f"[v33 residual audit] any_multi_step={report['any_multi_step']}")
    for a in audits:
        print(f"   {a['theorem']:28s} {a['family']:24s} {a['classification']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
