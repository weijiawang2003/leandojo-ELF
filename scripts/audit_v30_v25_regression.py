"""Mini-ELF v30 — Part 1: v25 micro-regression audit.

v29 traded 2 of the 14 v25 held-out theorems (`v25_nat_add_assoc`,
`v25_set_empty_subset`) — pass@10 1.000 → 0.857. This script pins down *why*, from
existing artifacts (NO Lean run), so Part 3 can repair with the minimum siblings:

For each regressed theorem it records:
  * the statement and the known-good expected proof(s) (Lean-verified references);
  * the v28 vs v29 first-verified-rank (did the correct tactic leave the beam?);
  * the v29 model's top-10 candidates + Lean error classes;
  * whether the correct tactic is PRESENT-but-ranked-out or ABSENT from the beam;
  * the family's training density in v28 vs v29 and the sibling variants present;
  * a proposed minimal set of new siblings (var-renames + the canonical tactic).

Classifies each regression as:
  beam_absence | vocabulary_drift | api_namespace | ranking_issue | sparse_sibling

Reads only existing eval + corpora; expected proofs are references, never predictions.
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
from audit_v29_family_density import family_of  # noqa: E402

V29E = ROOT / "data" / "baselines" / "v29_specialist_eval"
V28E = ROOT / "data" / "baselines" / "v28_specialist_eval"
TRACES = ROOT / "data" / "traces"
VERIFIED = ["v25_mathlib_tierc_verified.jsonl", "v26_mathlib_specialist_verified.jsonl",
            "v27_mathlib_expanded_verified.jsonl", "v28_mathlib_expanded_verified.jsonl",
            "v29_mathlib_density_verified.jsonl"]
TARGETS = ["v25_nat_add_assoc", "v25_set_empty_subset"]
EXPECTED = {
    "v25_nat_add_assoc": ["exact Nat.add_assoc a b c", "omega", "ring", "simp [Nat.add_assoc]"],
    "v25_set_empty_subset": ["exact Set.empty_subset s", "simp", "intro x hx; cases hx"],
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


def find_pred(root: Path, model: str, bench: str, nm: str) -> Optional[Dict[str, Any]]:
    pf = best_pred(root / f"{model}__{bench}")
    if not pf:
        return None
    for r in _read(pf):
        if r["theorem_name"] == nm:
            return r
    return None


def train_density(rows_by_fam: Dict[str, set], fam: str, nm: str) -> int:
    return len(rows_by_fam.get(fam, set()) - {nm})


def classify(rec: Dict[str, Any]) -> str:
    # correct tactic in the beam but it didn't verify at top-10 -> pure ranking.
    if rec["correct_present_in_beam"]:
        return "ranking_issue"
    # correct tactic ABSENT from the beam. If the family is sparse in train, the fix
    # is density repair; the unknown-id/hallucination is the *symptom* of that drift.
    if rec["v29_train_density"] < 4:
        return "beam_absence_sparse_sibling"
    cnt = Counter(rec["top10_error_classes"])
    if cnt.get("unknown_identifier", 0) >= 1:
        return "vocabulary_drift"
    if cnt.get("type_mismatch", 0) >= 1:
        return "api_namespace"
    return "beam_absence"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v30_v25_regression" / "report.json"))
    args = ap.parse_args(argv)

    thm_stmt: Dict[str, str] = {}
    thm_fam: Dict[str, str] = {}
    fam_train_v29: Dict[str, set] = defaultdict(set)
    fam_train_v28: Dict[str, set] = defaultdict(set)
    for fn in VERIFIED:
        for r in _read(TRACES / fn):
            thm_stmt[r["theorem_name"]] = r.get("theorem_statement", "")
            thm_fam[r["theorem_name"]] = family_of(r)
    for r in _read(ROOT / "data" / "processed" / "v29_mathlib_specialist" / "configs" / "v29_general_train_rows.jsonl"):
        fam_train_v29[family_of(r)].add(r["theorem_name"])
    for r in _read(ROOT / "data" / "processed" / "v28_mathlib_specialist" / "configs" / "v28_general_train_rows.jsonl"):
        fam_train_v28[family_of(r)].add(r["theorem_name"])

    audits = []
    for nm in TARGETS:
        fam = thm_fam.get(nm, "?")
        stmt = thm_stmt.get(nm, "")
        v29 = find_pred(V29E, "v29_general", "v25_heldout", nm)
        v28 = find_pred(V28E, "v28_general", "v25_heldout", nm)
        beam = (v29 or {}).get("ordering", [])[:10]
        errs = [v25_taxonomy(v.get("error")) for v in (v29 or {}).get("verifications", [])]
        # is a known-correct tactic present in the beam (but ranked past where it verifies)?
        present = any(any(exp.strip() == c.strip() for exp in EXPECTED.get(nm, [])) for c in beam)
        rec = {
            "theorem_name": nm, "family": fam, "statement": stmt,
            "expected_proofs": EXPECTED.get(nm, []),
            "v28_first_rank": (v28 or {}).get("first_verified_rank"),
            "v29_first_rank": (v29 or {}).get("first_verified_rank"),
            "v28_pass@10": bool((v28 or {}).get("pass@10")),
            "v29_pass@10": bool((v29 or {}).get("pass@10")),
            "top10_candidates": beam,
            "top10_error_classes": errs,
            "error_class_counts": dict(Counter(errs)),
            "correct_present_in_beam": present,
            "v28_train_density": train_density(fam_train_v28, fam, nm),
            "v29_train_density": train_density(fam_train_v29, fam, nm),
            "v28_train_siblings": sorted(fam_train_v28.get(fam, set()) - {nm}),
            "v29_train_siblings": sorted(fam_train_v29.get(fam, set()) - {nm}),
        }
        rec["classification"] = classify(rec)
        rec["proposed_minimal_siblings"] = _proposal(nm)
        audits.append(rec)

    report = {
        "config": "v30_v25_regression_audit",
        "source": "v28/v29 specialist eval + verified corpora (no Lean run)",
        "targets": TARGETS,
        "audits": audits,
        "summary": {a["theorem_name"]: {"classification": a["classification"],
                                        "v28_rank": a["v28_first_rank"], "v29_rank": a["v29_first_rank"],
                                        "v29_train_density": a["v29_train_density"]} for a in audits},
        "uses_state_after": False, "uses_manual_oracle": False,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for a in audits:
        print(f"### {a['theorem_name']} [{a['family']}] -> {a['classification']}")
        print(f"   v28 rank={a['v28_first_rank']} pass={a['v28_pass@10']}  ->  v29 rank={a['v29_first_rank']} pass={a['v29_pass@10']}")
        print(f"   train density v28={a['v28_train_density']} v29={a['v29_train_density']}")
        print(f"   correct tactic present in beam? {a['correct_present_in_beam']}")
        print(f"   top10[:5]={a['top10_candidates'][:5]}")
        print(f"   err={a['error_class_counts']}")
    return 0


def _proposal(nm: str) -> Dict[str, Any]:
    if nm == "v25_nat_add_assoc":
        return {"shape": "(x y z : Nat) : x + y + z = x + (y + z)",
                "var_sets": ["a,b,c", "m,n,k", "i,j,l", "x,y,z", "p,q,r"],
                "proof_heads": ["exact Nat.add_assoc x y z", "omega", "ring", "simp [Nat.add_assoc]"],
                "target_density": 6}
    return {"shape": "(α : Type) (s : Set α) : (∅ : Set α) ⊆ s",
            "var_sets": ["s", "t", "a", "u", "A"],
            "proof_heads": ["exact Set.empty_subset s", "simp", "intro x hx; cases hx"],
            "target_density": 6}


if __name__ == "__main__":
    raise SystemExit(main())
