"""Mini-ELF v29 — Part 2: sparse-family / residual audit.

Joins the Part-1 family-density census with the v28 specialist-eval predictions to
produce, for every **residual** held-out theorem (no verifying candidate at top-10
in the best config of its cell) and every **weak family** (held-out pass@10 < 1),
a single record that tells Part 3 exactly what to densify:

  * theorem statement and category;
  * the model's current **top-10 candidates** + their Lean error classes;
  * the known-good **expected proof(s)** (Lean-verified references, never predictions);
  * the **family density** (training siblings) from Part 1;
  * the **missing sibling variants** (which (var-set × proof-head) combinations the
    family lacks);
  * a **proposed densification** (concrete new variants for Part 3).

Each residual is classified into one v29 gap class:
  sibling_density_gap | lemma_name_vocabulary_gap | namespace_api_gap |
  wrong_projection_direction | renamed_identifier_gap | multi_step_gap

Reads only existing artifacts (the v29 family report + v28 eval + verified corpora);
no Lean run; no state_after; expected proofs are references.
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

from evaluate_v25_tierc import v25_taxonomy  # noqa: E402
from audit_v29_family_density import family_of, name_stem  # noqa: E402

V28_SPEC = ROOT / "data" / "baselines" / "v28_specialist_eval"
FAM_REPORT = ROOT / "data" / "baselines" / "v29_family_density" / "report.json"
FAM_JSONL = ROOT / "data" / "baselines" / "v29_family_density" / "families.jsonl"
TRACES = ROOT / "data" / "traces"

VERIFIED = ["v25_mathlib_tierc_verified.jsonl", "v26_mathlib_specialist_verified.jsonl",
            "v26_set_widen_verified.jsonl", "v27_mathlib_expanded_verified.jsonl",
            "v28_mathlib_expanded_verified.jsonl"]


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


def gap_class(stmt: str, family: str, errs: List[str], beam: List[str], density: int) -> str:
    cnt = Counter(errs)
    fam = family.split("::")[-1]
    # wrong projection: family is a projection/subset family and the beam emits the
    # *opposite* projector (.1 vs .2 / mem_inter_left vs right) — a binding error.
    if fam in ("mem_inter_proj", "inter_subset", "subset_union", "mem_union_intro"):
        proj_tokens = [".1", ".2", ".left", ".right", "Or.inl", "Or.inr",
                       "inter_subset_left", "inter_subset_right",
                       "mem_of_mem_inter_left", "mem_of_mem_inter_right",
                       "subset_union_left", "subset_union_right"]
        if any(t in c for c in beam for t in proj_tokens):
            return "wrong_projection_direction"
    if fam in ("comp_assoc", "comp_id", "id_apply") and cnt.get("type_mismatch", 0) + cnt.get("unsolved", 0) >= 1:
        return "renamed_identifier_gap"
    if cnt.get("unknown_identifier", 0) >= 1:
        return "namespace_api_gap" if any("." in c for c in beam) else "lemma_name_vocabulary_gap"
    if cnt.get("type_mismatch", 0) >= 1:
        return "namespace_api_gap"
    if stmt.count("→") >= 2 or (("h1" in stmt and "h2" in stmt) and "↔" not in stmt and "=" not in stmt.split(":")[-1][:6]):
        return "multi_step_gap"
    # default for a thin family with a shape miss
    return "sibling_density_gap" if density <= 4 else "sibling_density_gap"


# var-sets and proof-head menus the v29 densifier will draw from, per family kind
VAR_MENU = {
    "set": ["(s,t,u)", "(a,b,c)", "(p,q,r)", "(u,v,w)"],
    "finset": ["(s,t)", "(a,b)", "(p,q)", "(u,v)"],
    "order": ["(a,b,c)", "(x,y,z)", "(p,q,r)"],
    "function": ["(f,g,h)", "(p,q,r)", "(φ,ψ,χ)"],
}
HEAD_MENU = {
    "mem_inter_proj": ["exact (·.mp h).1/.2", "exact mem_of_mem_inter_left/right h", "intro;exact h.1/.2"],
    "inter_subset": ["exact inter_subset_left/right", "intro x hx; exact (mem_inter.mp hx).1/.2"],
    "subset_union": ["exact subset_union_left/right", "intro x hx; exact mem_union.mpr (Or.inl/inr hx)"],
    "union_subset": ["exact union_subset h1 h2", "rintro x (h|h)", "intro x hx; exact hx.elim h1 h2"],
    "subset_inter": ["exact subset_inter h1 h2", "intro x hx; exact ⟨h1 hx, h2 hx⟩"],
    "mem_iff": ["exact mem_inter/mem_union", "simp [mem_inter/mem_union]", "constructor <;> intro h"],
    "antisymm": ["exact le_antisymm h1 h2"],
    "le_total": ["exact le_total a b"],
    "comp_assoc": ["rfl", "funext x; rfl", "ext x; rfl"],
    "inter_comm": ["exact inter_comm s t", "ext x; simp [and_comm]"],
    "union_comm": ["exact union_comm s t", "ext x; simp [or_comm]"],
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v29_sparse_residual" / "report.json"))
    ap.add_argument("--out-residuals", default=str(ROOT / "data" / "baselines" / "v29_sparse_residual" / "residuals.jsonl"))
    args = ap.parse_args(argv)

    # expected proofs + statements from verified corpora
    proofs: Dict[str, List[str]] = defaultdict(list)
    thm_stmt: Dict[str, str] = {}
    thm_fam: Dict[str, str] = {}
    thm_cat: Dict[str, str] = {}
    for fn in VERIFIED:
        for r in _read(TRACES / fn):
            nm = r.get("theorem_name", "")
            t = (r.get("tactic") or "").strip()
            if t and t not in proofs[nm]:
                proofs[nm].append(t)
            thm_stmt[nm] = r.get("theorem_statement", "")
            thm_fam[nm] = family_of(r)
            thm_cat[nm] = r.get("category", "?")

    # family density from Part 1
    fam_density: Dict[str, int] = {}
    if FAM_JSONL.exists():
        for r in _read(FAM_JSONL):
            fam_density[r["family"]] = r["n_sibling_theorems"]

    # Only the CURRENT v28 system counts as "the model": a theorem is a residual iff
    # it is missed (no verifying candidate at top-10) by EVERY applicable v28 model.
    # Main v28 models share the theorem-holdout benches (take best-of across them);
    # transfer models are the only evaluators of their category-holdout bench.
    CURRENT_MAIN = {"v28_general", "v28_set_order_heavy", "v28_finset_specialist"}
    CURRENT_TRANSFER = {"v28_set_holdout", "v28_order_holdout", "v28_finset_holdout"}
    # per theorem: solved_in_any_current, and a representative residual record
    solved_any: Dict[str, bool] = defaultdict(bool)
    rep: Dict[str, Dict[str, Any]] = {}
    weak_family_members: Dict[str, List[str]] = defaultdict(list)
    if V28_SPEC.exists():
        for run_dir in sorted(V28_SPEC.iterdir()):
            if not run_dir.is_dir():
                continue
            model = run_dir.name.split("__")[0]
            if model not in CURRENT_MAIN and model not in CURRENT_TRANSFER:
                continue
            pf = best_pred(run_dir)
            if not pf:
                continue
            for r in _read(pf):
                nm = r["theorem_name"]
                fam = thm_fam.get(nm, "?")
                if not r.get("pass@10"):
                    weak_family_members[fam].append(nm)
                else:
                    solved_any[nm] = True
                if r.get("first_verified_rank") is not None:
                    continue
                stmt = thm_stmt.get(nm, "")
                errs = [v25_taxonomy(v.get("error")) for v in r.get("verifications", [])]
                beam = r.get("ordering", [])[:10]
                density = fam_density.get(fam, 0)
                regime = "whole_category_transfer" if model in CURRENT_TRANSFER else "theorem_holdout"
                rec = {
                    "theorem_name": nm, "cell": run_dir.name, "model": model,
                    "regime": regime,
                    "category": thm_cat.get(nm, "?"), "family": fam,
                    "family_density": density, "statement": stmt,
                    "expected_proofs": proofs.get(nm, [])[:4],
                    "top10_candidates": beam, "top10_error_classes": errs,
                    "error_class_counts": dict(Counter(errs)),
                    "gap_class": gap_class(stmt, fam, errs, beam, density),
                    "missing_variants": _missing_variants(fam),
                    "proposed_densification": _proposal(fam),
                }
                prev = rep.get(nm)
                if prev is None or (prev["regime"] == "whole_category_transfer"
                                    and regime == "theorem_holdout"):
                    rep[nm] = rec
    # a genuine residual = appears as a miss-record AND was never solved by any current v28 model
    residual_by_thm: Dict[str, Dict[str, Any]] = {nm: rec for nm, rec in rep.items()
                                                  if not solved_any.get(nm)}

    residuals = sorted(residual_by_thm.values(), key=lambda r: (r["category"], r["family"], r["theorem_name"]))

    # weak families (any held-out miss)
    weak_families = sorted({thm_fam.get(nm, "?") for nms in weak_family_members.values() for nm in nms
                            if thm_fam.get(nm)})
    weak_summary = []
    for fam in weak_families:
        density = fam_density.get(fam, 0)
        weak_summary.append({"family": fam, "category": fam.split("::")[0],
                             "density": density, "proposal": _proposal(fam)})
    weak_summary.sort(key=lambda r: (r["density"], r["family"]))

    report = {
        "config": "v29_sparse_residual_audit",
        "source": "v29 family report + v28 specialist eval + verified corpora (no Lean run)",
        "n_distinct_residual_theorems": len(residual_by_thm),
        "residual_theorems": sorted(residual_by_thm),
        "by_regime": dict(Counter(r["regime"] for r in residuals)),
        "n_theorem_holdout_residuals": sum(1 for r in residuals if r["regime"] == "theorem_holdout"),
        "theorem_holdout_residuals": [r["theorem_name"] for r in residuals if r["regime"] == "theorem_holdout"],
        "gap_class_counts": dict(Counter(r["gap_class"] for r in residuals)),
        "gap_class_counts_theorem_holdout": dict(Counter(
            r["gap_class"] for r in residuals if r["regime"] == "theorem_holdout")),
        "by_category": dict(Counter(r["category"] for r in residuals)),
        "by_family": dict(Counter(r["family"] for r in residuals)),
        "n_weak_families": len(weak_summary),
        "weak_families": weak_summary,
        "uses_state_after": False, "uses_manual_oracle": False,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    with Path(args.out_residuals).open("w", encoding="utf-8") as f:
        for r in residuals:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[sparse] residual theorems: {len(residual_by_thm)}  by_regime={report['by_regime']}")
    print(f"[sparse] gap classes (all): {report['gap_class_counts']}")
    print(f"[sparse] gap classes (theorem-holdout regime only): {report['gap_class_counts_theorem_holdout']}")
    print(f"[sparse] weak families: {len(weak_summary)}")
    print("[sparse] genuine theorem-holdout residuals (family intact, still missed):")
    for r in residuals:
        if r["regime"] == "theorem_holdout":
            print(f"   {r['category']:8s} {r['family'].split('::')[-1]:18s} dens={r['family_density']:2d} "
                  f"{r['gap_class']:26s} {r['theorem_name']}")
    return 0


def _proposal(fam: str) -> Dict[str, Any]:
    kind = fam.split("::")[0]
    head = fam.split("::")[-1]
    return {"var_sets": VAR_MENU.get(kind, ["(a,b,c)"]),
            "proof_heads": HEAD_MENU.get(head, ["named lemma", "intro;exact", "simp"]),
            "target_siblings": 8}


def _missing_variants(fam: str) -> str:
    kind = fam.split("::")[0]
    nv = len(VAR_MENU.get(kind, ["(a,b,c)"]))
    return f"{nv} var-sets x {len(_proposal(fam)['proof_heads'])} proof-heads not yet all present"


if __name__ == "__main__":
    raise SystemExit(main())
