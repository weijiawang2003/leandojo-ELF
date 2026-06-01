"""Mini-ELF v32 — Part 5: fresh Mathlib micro-holdout (eval only).

20–40 fresh single-tactic Mathlib theorems across Set / Finset / order / function /
Nat / List / logic, **never used in training** (statement-level leakage-guarded against
every prior corpus + holdout). Each is verified to have >=1 gold proof. Used only for
evaluation — the gold proof is a reference, never a model prediction.
TrustedMathlibVerifier only; no state_after.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mini_elf_lean.mathlib_batched_verifier import TrustedMathlibVerifier, MATHLIB_IMPORT  # noqa: E402
from generate_v25_mathlib_tierc_corpus import state_before  # noqa: E402
from generate_v27_mathlib_expanded_corpus import proof_head  # noqa: E402

FD = "(α : Type) [DecidableEq α]"
# fresh single-tactic theorems (distinct shapes from the trained families)
PLAN = [
    ("set_inter_subset_union", "(α : Type) (s t : Set α) : s ∩ t ⊆ s ∪ t", ["intro x hx; exact Or.inl hx.1"], "set", "inter_subset_union"),
    ("set_union_self", "(α : Type) (s : Set α) : s ∪ s = s", ["simp", "exact Set.union_self s"], "set", "union_self"),
    ("set_inter_self", "(α : Type) (s : Set α) : s ∩ s = s", ["simp", "exact Set.inter_self s"], "set", "inter_self"),
    ("set_subset_union_self", "(α : Type) (s t : Set α) : s ⊆ (s ∪ t) ∪ s", ["intro x hx; exact Or.inl (Or.inl hx)"], "set", "subset_union"),
    ("set_inter_comm_eq", "(α : Type) (s t : Set α) : s ∩ t = t ∩ s", ["exact Set.inter_comm s t", "ext x; simp [and_comm]"], "set", "inter_comm"),
    ("set_union_comm_eq", "(α : Type) (s t : Set α) : s ∪ t = t ∪ s", ["exact Set.union_comm s t", "ext x; simp [or_comm]"], "set", "union_comm"),
    ("set_inter_assoc", "(α : Type) (s t u : Set α) : s ∩ t ∩ u = s ∩ (t ∩ u)", ["exact Set.inter_assoc s t u", "ext x; simp [and_assoc]"], "set", "inter_assoc"),
    ("fs_inter_self", f"{FD} (s : Finset α) : s ∩ s = s", ["exact Finset.inter_self s", "simp"], "finset", "inter_self"),
    ("fs_union_self", f"{FD} (s : Finset α) : s ∪ s = s", ["exact Finset.union_self s", "simp"], "finset", "union_self"),
    ("fs_subset_refl", f"{FD} (s : Finset α) : s ⊆ s", ["exact Finset.Subset.refl s", "intro x hx; exact hx"], "finset", "subset_refl"),
    ("fs_inter_comm", f"{FD} (s t : Finset α) : s ∩ t = t ∩ s", ["exact Finset.inter_comm s t"], "finset", "inter_comm"),
    ("ord_le_trans3", "(α : Type) [Preorder α] (a b c d : α) (h1 : a ≤ b) (h2 : b ≤ c) (h3 : c ≤ d) : a ≤ d", ["exact le_trans (le_trans h1 h2) h3", "exact h1.trans (h2.trans h3)"], "order", "le_trans"),
    ("ord_lt_imp_le", "(α : Type) [Preorder α] (a b : α) (h : a < b) : a ≤ b", ["exact le_of_lt h", "exact h.le"], "order", "le_of_lt"),
    ("ord_min_comm", "(α : Type) [LinearOrder α] (a b : α) : min a b = min b a", ["exact min_comm a b"], "order", "min_max"),
    ("ord_max_comm", "(α : Type) [LinearOrder α] (a b : α) : max a b = max b a", ["exact max_comm a b"], "order", "min_max"),
    ("ord_inf_comm", "(α : Type) [Lattice α] (a b : α) : a ⊓ b = b ⊓ a", ["exact inf_comm a b"], "order", "lattice"),
    ("fun_comp_apply", "(α β γ : Type) (f : β → γ) (g : α → β) (x : α) : (f ∘ g) x = f (g x)", ["rfl", "simp"], "function", "comp_app"),
    ("fun_id_comp", "(α β : Type) (f : α → β) : id ∘ f = f", ["rfl", "funext x; rfl"], "function", "comp_id"),
    ("nat_succ_pos", "(n : Nat) : 0 < n + 1", ["omega", "exact Nat.succ_pos n", "simp"], "nat", "lt"),
    ("nat_add_comm2", "(n m : Nat) : n + m = m + n", ["omega", "exact Nat.add_comm n m", "ring"], "nat", "add_comm"),
    ("nat_mul_two", "(n : Nat) : n * 2 = n + n", ["omega", "ring"], "nat", "two_mul"),
    ("nat_one_mul", "(n : Nat) : 1 * n = n", ["simp", "exact Nat.one_mul n", "omega"], "nat", "one_mul"),
    ("list_cons_ne_nil", "(α : Type) (a : α) (xs : List α) : a :: xs ≠ []", ["simp", "exact List.cons_ne_nil a xs"], "list", "cons_ne_nil"),
    ("list_reverse_nil", "(α : Type) : ([] : List α).reverse = []", ["simp", "rfl"], "list", "reverse"),
    ("list_map_nil", "(α β : Type) (f : α → β) : [].map f = []", ["simp", "rfl"], "list", "map_nil"),
    ("logic_or_symm2", "(p q : Prop) (h : p ∨ q) : q ∨ p", ["exact h.symm", "tauto", "exact Or.symm h"], "logic", "or_symm"),
    ("logic_and_self", "(p : Prop) : p ∧ p ↔ p", ["simp", "tauto", "exact and_self_iff"], "logic", "and_self"),
    ("logic_imp_self", "(p : Prop) : p → p", ["exact id", "intro h; exact h", "tauto"], "logic", "imp_self"),
    ("logic_true_intro", "True", ["trivial", "exact True.intro"], "logic", "true"),
    ("logic_not_false", "¬False", ["exact not_false", "simp", "tauto"], "logic", "not_false"),
    ("set_diff_self", "(α : Type) (s : Set α) : s \\ s = ∅", ["simp", "exact Set.diff_self"], "set", "diff_self"),
    ("set_empty_union", "(α : Type) (s : Set α) : (∅ : Set α) ∪ s = s", ["simp", "exact Set.empty_union s"], "set", "empty_union"),
    ("fs_empty_union", f"{FD} (s : Finset α) : (∅ : Finset α) ∪ s = s", ["simp", "exact Finset.empty_union s"], "finset", "empty_union"),
    ("nat_zero_add2", "(n : Nat) : 0 + n = n", ["simp", "omega", "exact Nat.zero_add n"], "nat", "zero_add"),
    ("ord_le_refl_lin", "(α : Type) [LinearOrder α] (a : α) : a ≤ a", ["exact le_rfl", "exact le_refl a"], "order", "le_refl"),
    ("logic_iff_self", "(p : Prop) : p ↔ p", ["exact Iff.rfl", "rfl", "tauto"], "logic", "iff_refl"),
]


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _all_train_pairs() -> Set:
    pairs = set()
    for src in [ROOT / "data" / "processed" / "v30_mathlib_specialist" / "configs" / "v30_general_targeted_train_rows.jsonl",
                ROOT / "data" / "processed" / "v31_canonical_mathlib" / "configs" / "raw_plus_projection_aug_train_rows.jsonl"]:
        for r in _read(src):
            pairs.add((r.get("theorem_statement", ""), r.get("state_before", "")))
    return pairs


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("v32_fresh")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(ROOT.parent / "mini_elf_mathlib_probe"))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--out-seeds", default=str(ROOT / "data" / "seeds" / "v32_fresh_mathlib_holdout_seeds.jsonl"))
    ap.add_argument("--out-candidates", default=str(ROOT / "data" / "manual" / "v32_fresh_mathlib_holdout_candidates.jsonl"))
    ap.add_argument("--out-summary", default=str(ROOT / "data" / "processed" / "v32_mathlib" / "fresh_holdout_summary.json"))
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    verifier = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=300)
    if not verifier.warmup():
        logger.error("warmup failed"); return 2

    work, meta = [], []
    for nm, stmt, cands, cat, fam in PLAN:
        for c in dict.fromkeys(x.strip() for x in cands):
            work.append((f"v32fresh_{nm}", stmt, c))
            meta.append({"theorem_name": f"v32fresh_{nm}", "theorem_statement": stmt, "category": cat, "theorem_family": fam})
    verdicts = verifier.verify_many(work, confirm=True)

    train_pairs = _all_train_pairs()
    verified, thm_ok, leaked = [], {}, set()
    for vd, e in zip(verdicts, meta):
        st = state_before(vd.statement)
        if (vd.statement, st) in train_pairs:
            leaked.add(vd.theorem_name)
            continue
        if vd.success:
            thm_ok[vd.theorem_name] = True
            verified.append({"theorem_name": vd.theorem_name, "theorem_statement": vd.statement, "state_before": st,
                             "tactic": vd.tactic, "category": e["category"], "theorem_family": e["theorem_family"],
                             "source": "v32_fresh_mathlib_holdout", "verified": True, "mathlib": True,
                             "proof_head": proof_head(vd.tactic)})
    by_name = {e["theorem_name"]: e for e in meta}
    seeds = []
    for nm in dict.fromkeys(e["theorem_name"] for e in meta):
        if nm in leaked or not thm_ok.get(nm):
            continue
        e = by_name[nm]
        seeds.append({"theorem_name": nm, "theorem_statement": e["theorem_statement"], "state_before": state_before(e["theorem_statement"]),
                      "category": e["category"], "theorem_family": e["theorem_family"], "expected_skill": e["category"],
                      "source": "v32_fresh_mathlib_holdout", "mathlib": True, "imports": [MATHLIB_IMPORT]})
    zero = [nm for nm in dict.fromkeys(e["theorem_name"] for e in meta) if nm not in leaked and not thm_ok.get(nm)]

    for p in (args.out_seeds, args.out_candidates, args.out_summary):
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    for path, rows in ((args.out_seeds, seeds), (args.out_candidates, verified)):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"config": "v32_fresh_mathlib_holdout", "n_theorems": len(PLAN), "n_solvable_theorems": len(seeds),
               "n_verified_candidates": len(verified), "n_zero_success": len(zero), "n_leaked_dropped": len(leaked),
               "by_category": dict(Counter(s["category"] for s in seeds)), "verifier": "TrustedMathlibVerifier",
               "total_lean_seconds": round(verifier.total_lean_seconds, 1), "uses_state_after": False, "uses_manual_oracle": False,
               "note": "EVAL ONLY; never trained on; gold proofs are references"}
    Path(args.out_summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("v32 fresh holdout: solvable=%d verified_cands=%d zero=%d leaked=%d by_cat=%s",
                len(seeds), len(verified), len(zero), len(leaked), summary["by_category"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
