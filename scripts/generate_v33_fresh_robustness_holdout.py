"""Mini-ELF v33 — Part 3: fresh robustness holdout (eval only).

30–60 fresh theorems that stress BOTH canonicalization (adversarial identifiers
`h_left`/`h_right`/`h3`/`h_mem`, `A B C`/`U V W`, `φ ψ`, subscript `h₁`) AND single-tactic
coverage across all categories. Never trained; statement-level leakage-guarded; each
verified to have >=1 gold proof. TrustedMathlibVerifier only; no state_after.
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


def _e(name, stmt, cands, cat, fam):
    return {"theorem_name": f"v33rob_{name}", "theorem_statement": stmt, "candidates": cands, "category": cat, "theorem_family": fam}


def build_plan() -> List[Dict[str, Any]]:
    out = []
    # set/finset projection with adversarial hyp names
    SETS = [("A", "B", "obj", "h_left"), ("U", "V", "elem", "h_right"), ("C", "D", "z", "h₁"), ("R", "S", "w", "h_mem")]
    for i, (s, t, e, h) in enumerate(SETS):
        out.append(_e(f"set_inter_l_{i}", f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {s}", [f"exact {h}.1"], "set", "mem_inter_proj"))
        out.append(_e(f"set_inter_r_{i}", f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {t}", [f"exact {h}.2"], "set", "mem_inter_proj"))
        out.append(_e(f"set_union_r_{i}", f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {t}) : {e} ∈ {s} ∪ {t}", [f"exact Or.inr {h}"], "set", "mem_union_intro"))
        out.append(_e(f"fs_inter_r_{i}", f"{FD} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {t}", [f"exact (Finset.mem_inter.mp {h}).2"], "finset", "mem_inter_proj"))
        out.append(_e(f"set_inter_sub_{i}", f"(α : Type) ({s} {t} : Set α) : {s} ∩ {t} ⊆ {s}", ["intro x hx; exact hx.1", "exact Set.inter_subset_left"], "set", "inter_subset"))
    # order with adversarial vars
    for i, (a, b, c) in enumerate([("A", "B", "C"), ("U", "V", "W"), ("obj", "elem", "thing")]):
        out.append(_e(f"ord_trans_{i}", f"(α : Type) [Preorder α] ({a} {b} {c} : α) (h_ab : {a} ≤ {b}) (h_bc : {b} ≤ {c}) : {a} ≤ {c}", ["exact le_trans h_ab h_bc", "exact h_ab.trans h_bc"], "order", "le_trans"))
        out.append(_e(f"ord_refl_{i}", f"(α : Type) [Preorder α] ({a} : α) : {a} ≤ {a}", ["exact le_rfl", f"exact le_refl {a}"], "order", "le_refl"))
        out.append(_e(f"ord_anti_{i}", f"(α : Type) [PartialOrder α] ({a} {b} : α) (h_ab : {a} ≤ {b}) (h_ba : {b} ≤ {a}) : {a} = {b}", ["exact le_antisymm h_ab h_ba"], "order", "antisymm"))
    # function comp with greek/renamed
    for i, (f, g, h) in enumerate([("φ", "ψ", "χ"), ("F", "G", "H"), ("k", "l", "m")]):
        out.append(_e(f"fun_assoc_{i}", f"(α β γ δ : Type) ({f} : α → β) ({g} : β → γ) ({h} : γ → δ) : ({h} ∘ {g}) ∘ {f} = {h} ∘ ({g} ∘ {f})", ["rfl", "funext x; rfl"], "function", "comp_assoc"))
    # nat / list with adversarial vars
    for i, n in enumerate(["obj", "cnt", "num"]):
        out.append(_e(f"nat_addc_{i}", f"({n} m : Nat) : {n} + m = m + {n}", ["omega", f"exact Nat.add_comm {n} m", "ring"], "nat", "add_comm"))
        out.append(_e(f"nat_az_{i}", f"({n} : Nat) : {n} + 0 = {n}", ["rfl", "simp", "omega"], "nat", "add_zero"))
    for i, x in enumerate(["lst", "items"]):
        out.append(_e(f"list_an_{i}", f"(α : Type) ({x} : List α) : {x} ++ [] = {x}", ["simp", f"exact List.append_nil {x}"], "list", "append_nil"))
    # logic with adversarial hyp names + cases
    for i, (p, q, h) in enumerate([("P", "Q", "h_or"), ("prop1", "prop2", "h_disj")]):
        out.append(_e(f"logic_or_symm_{i}", f"({p} {q} : Prop) ({h} : {p} ∨ {q}) : {q} ∨ {p}", [f"exact {h}.symm", "tauto", f"exact Or.symm {h}"], "logic", "or_symm"))
        out.append(_e(f"logic_and_symm_{i}", f"({p} {q} : Prop) ({h} : {p} ∧ {q}) : {q} ∧ {p}", [f"exact ⟨{h}.2, {h}.1⟩", "tauto"], "logic", "and_symm"))
    return out


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _train_pairs() -> Set:
    pairs = set()
    for src in [ROOT / "data" / "processed" / "v30_mathlib_specialist" / "configs" / "v30_general_targeted_train_rows.jsonl",
                ROOT / "data" / "processed" / "v31_canonical_mathlib" / "configs" / "raw_plus_projection_aug_train_rows.jsonl",
                ROOT / "data" / "processed" / "v33_mathlib_specialist" / "residual_coverage_rows.jsonl"]:
        for r in _read(src):
            pairs.add((r.get("theorem_statement", ""), r.get("state_before", "")))
    return pairs


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("v33_fresh_rob")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(ROOT.parent / "mini_elf_mathlib_probe"))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--out-seeds", default=str(ROOT / "data" / "seeds" / "v33_fresh_robustness_holdout_seeds.jsonl"))
    ap.add_argument("--out-candidates", default=str(ROOT / "data" / "manual" / "v33_fresh_robustness_holdout_candidates.jsonl"))
    ap.add_argument("--out-summary", default=str(ROOT / "data" / "processed" / "v33_mathlib_specialist" / "fresh_robustness_summary.json"))
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    plan = build_plan()
    verifier = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=300)
    if not verifier.warmup():
        logger.error("warmup failed"); return 2
    work, meta = [], []
    for e in plan:
        for c in dict.fromkeys(x.strip() for x in e["candidates"]):
            work.append((e["theorem_name"], e["theorem_statement"], c)); meta.append(e)
    verdicts = verifier.verify_many(work, confirm=True)
    tp = _train_pairs()
    verified, thm_ok, leaked = [], {}, set()
    for vd, e in zip(verdicts, meta):
        st = state_before(vd.statement)
        if (vd.statement, st) in tp:
            leaked.add(vd.theorem_name); continue
        if vd.success:
            thm_ok[vd.theorem_name] = True
            verified.append({"theorem_name": vd.theorem_name, "theorem_statement": vd.statement, "state_before": st, "tactic": vd.tactic,
                             "category": e["category"], "theorem_family": e["theorem_family"], "source": "v33_fresh_robustness",
                             "verified": True, "mathlib": True, "proof_head": proof_head(vd.tactic)})
    by_name = {e["theorem_name"]: e for e in meta}
    seeds = []
    for nm in dict.fromkeys(e["theorem_name"] for e in meta):
        if nm in leaked or not thm_ok.get(nm):
            continue
        e = by_name[nm]
        seeds.append({"theorem_name": nm, "theorem_statement": e["theorem_statement"], "state_before": state_before(e["theorem_statement"]),
                      "category": e["category"], "theorem_family": e["theorem_family"], "expected_skill": e["category"],
                      "source": "v33_fresh_robustness", "mathlib": True, "imports": [MATHLIB_IMPORT]})
    zero = [nm for nm in dict.fromkeys(e["theorem_name"] for e in meta) if nm not in leaked and not thm_ok.get(nm)]

    for p in (args.out_seeds, args.out_candidates, args.out_summary):
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    for path, rows in ((args.out_seeds, seeds), (args.out_candidates, verified)):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"config": "v33_fresh_robustness", "n_theorems": len(plan), "n_solvable": len(seeds),
               "n_verified_candidates": len(verified), "n_zero_success": len(zero), "n_leaked_dropped": len(leaked),
               "by_category": dict(Counter(s["category"] for s in seeds)), "verifier": "TrustedMathlibVerifier",
               "total_lean_seconds": round(verifier.total_lean_seconds, 1), "uses_state_after": False, "uses_manual_oracle": False,
               "note": "EVAL ONLY; never trained; gold proofs are references"}
    Path(args.out_summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("v33 fresh robustness: solvable=%d cands=%d zero=%d leaked=%d by_cat=%s",
                len(seeds), len(verified), len(zero), len(leaked), summary["by_category"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
