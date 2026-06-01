"""Mini-ELF v30 — Part 2: low-density residual audit.

Starts from the v29 residuals + the v29 family-density census + the v25 regression
(Part 1) and lists exactly which families v30 should repair — those that are below the
reliable 4–6 sibling threshold OR carry a v29 held-out failure / v25 regression /
vocabulary-API residual. NO Lean run.

For each target family it records: current training density (v29), the residual /
regression reason, the target density (4–6), proposed example shapes, expected proof
heads, and whether a single tactic should close it.

A nuance the audit surfaces: the `_3` projection/membership residuals come from
families whose *count* is already ≥4, but whose held-out members use **surface tokens
(`u,v` sets, element `w`, hyp `hw`) absent from every training sibling** — so the
repair is **token-diversity**, not just more rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audit_v29_family_density import family_of  # noqa: E402

FAM_JSONL = ROOT / "data" / "baselines" / "v29_family_density" / "families.jsonl"
V29_RESID = ROOT / "data" / "baselines" / "v29_remaining_failures" / "report.json"
V25_REG = ROOT / "data" / "baselines" / "v30_v25_regression" / "report.json"
V29_TRAIN = ROOT / "data" / "processed" / "v29_mathlib_specialist" / "configs" / "v29_general_train_rows.jsonl"

# (family, category, target_density, proposed_shape, proof_heads, single_tactic, repair_kind)
FOCUS = [
    ("add_assoc", "nat", 6, "(x y z : Nat) : x + y + z = x + (y + z)",
     ["exact Nat.add_assoc x y z", "omega", "ring", "simp [Nat.add_assoc]"], True, "v25_regression+count"),
    ("empty_subset", "set", 6, "(α : Type) (s : Set α) : (∅ : Set α) ⊆ s",
     ["exact Set.empty_subset s", "simp", "intro x hx; cases hx"], True, "v25_regression+count"),
    ("empty_subset", "finset", 6, "(α : Type) [DecidableEq α] (s : Finset α) : (∅ : Finset α) ⊆ s",
     ["exact Finset.empty_subset s", "simp"], True, "residual+count"),
    ("le_refl", "order", 6, "(α : Type) [Preorder α] (a : α) : a ≤ a",
     ["exact le_rfl", "exact le_refl a"], True, "residual+count"),
    ("mem_inter_proj", "set", 6, "(α : Type) (s t : Set α) (w : α) (hw : w ∈ s ∩ t) : w ∈ s",
     ["exact hw.1", "exact hw.2", "exact (Set.mem_inter_iff.mp hw).1"], True, "residual+token_diversity"),
    ("mem_union_intro", "set", 6, "(α : Type) (s t : Set α) (w : α) (hw : w ∈ s) : w ∈ s ∪ t",
     ["exact Or.inl hw", "exact Set.mem_union_left t hw"], True, "residual+token_diversity"),
    ("mem_inter_proj", "finset", 6, "(α : Type) [DecidableEq α] (s t : Finset α) (w : α) (hw : w ∈ s ∩ t) : w ∈ s",
     ["exact (Finset.mem_inter.mp hw).1", "exact Finset.mem_of_mem_inter_left hw"], True, "residual+token_diversity"),
    ("mem_union_intro", "finset", 6, "(α : Type) [DecidableEq α] (s t : Finset α) (w : α) (hw : w ∈ s) : w ∈ s ∪ t",
     ["exact Finset.mem_union.mpr (Or.inl hw)", "exact Finset.mem_union_left t hw"], True, "residual+token_diversity"),
    ("union_subset", "set", 6, "(α : Type) (s t u : Set α) (hs : s ⊆ u) (ht : t ⊆ u) : s ∪ t ⊆ u",
     ["exact Set.union_subset hs ht", "rintro x (h | h)"], True, "low_density"),
    ("comp_assoc", "function", 6, "(α β γ δ : Type) (φ ψ χ : _) : (χ ∘ ψ) ∘ φ = χ ∘ (ψ ∘ φ)",
     ["rfl", "funext x; rfl"], True, "low_density"),
]


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v30_low_density" / "report.json"))
    args = ap.parse_args(argv)

    # v29 corpus-wide family sibling counts (from Part 1 audit)
    fam_corpus_density: Dict[str, int] = {}
    for r in _read(FAM_JSONL):
        fam_corpus_density[r["family"]] = r["n_sibling_theorems"]
    # v29 *training* density (siblings actually in v29_general train)
    fam_train: Dict[str, set] = defaultdict(set)
    for r in _read(V29_TRAIN):
        fam_train[family_of(r)].add(r["theorem_name"])

    resid = json.loads(V29_RESID.read_text()) if V29_RESID.exists() else {"residuals": []}
    resid_fams = {r["family"] for r in resid.get("residuals", [])}

    targets = []
    for fam, cat, tgt, shape, heads, single, kind in FOCUS:
        key = f"{cat}::{fam}"
        train_d = len(fam_train.get(key, set()))
        targets.append({
            "family": key, "category": cat,
            "v29_corpus_density": fam_corpus_density.get(key, 0),
            "v29_train_density": train_d,
            "has_v29_residual": key in resid_fams,
            "repair_kind": kind,
            "below_threshold": train_d < 4,
            "target_density": tgt,
            "proposed_shape": shape, "expected_proof_heads": heads,
            "single_tactic_solvable": single,
        })

    report = {
        "config": "v30_low_density_residual_audit",
        "source": "v29 family census + v29 residuals + v30 v25-regression audit (no Lean run)",
        "n_target_families": len(targets),
        "n_below_threshold": sum(1 for t in targets if t["below_threshold"]),
        "n_token_diversity": sum(1 for t in targets if "token_diversity" in t["repair_kind"]),
        "targets": targets,
        "note": ("families tagged token_diversity already have >=4 siblings by count but "
                 "their held-out _3 members use surface tokens (u,v sets, element w, hyp "
                 "hw) absent from training siblings -> repair = more token variety, not "
                 "just more rows"),
        "uses_state_after": False, "uses_manual_oracle": False,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[low-density] target families: {len(targets)} (below-threshold {report['n_below_threshold']}, "
          f"token-diversity {report['n_token_diversity']})")
    for t in targets:
        print(f"   {t['family']:26s} train_density={t['v29_train_density']:2d} "
              f"resid={t['has_v29_residual']!s:5s} target={t['target_density']} kind={t['repair_kind']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
