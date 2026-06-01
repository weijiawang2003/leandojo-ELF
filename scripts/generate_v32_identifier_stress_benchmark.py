"""Mini-ELF v32 — Part 3: adversarial identifier-renaming stress benchmark.

Generates fresh variants of *solved* v31 families with **adversarial local
identifiers** the training corpus never used — `h_mem`, `hyp`, `proof₁`, Greek
(`φ ψ χ`, `hα`), uppercase sets (`A B C`, `U V W`), unusual elements (`obj`, `elem`).
This is the real test of v31's identifier invariance (RQ3): canonicalization should
solve ALL of them, while a raw model that merely memorized the v30 residual identifiers
should still miss the new ones.

This is an EVALUATION benchmark (held out, never trained). Each theorem is verified to
have >=1 gold proof (so it is genuinely provable); the gold proof is a reference, never
fed to a model. TrustedMathlibVerifier only.

Categories: Set projection, Finset projection, order refl/trans, function composition,
Nat/List simp, logic. 30–80 theorems / 80–200 verified candidates.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mini_elf_lean.mathlib_batched_verifier import TrustedMathlibVerifier, MATHLIB_IMPORT  # noqa: E402
from generate_v25_mathlib_tierc_corpus import state_before  # noqa: E402
from generate_v27_mathlib_expanded_corpus import proof_head  # noqa: E402

# adversarial (set/elem/hyp) and (var) tuples the training corpus never used
SET_HYP = [("A", "B", "obj", "h_mem"), ("U", "V", "elem", "hyp"), ("S", "T", "z", "proof₁"),
           ("X", "Y", "w", "hα"), ("P", "Q", "o", "h_1")]
ORD_VARS = [("A", "B", "C"), ("X", "Y", "Z"), ("obj", "elem", "thing")]
FN_VARS = [("φ", "ψ", "χ"), ("F", "G", "H"), ("k", "l", "m")]


def _entry(name, stmt, cands, cat, fam):
    return {"theorem_name": f"v32stress_{name}", "theorem_statement": stmt, "candidates": cands,
            "category": cat, "theorem_family": fam}


def build_plan() -> List[Dict[str, Any]]:
    out = []
    F = "(α : Type) [DecidableEq α]"
    for i, (s, t, e, h) in enumerate(SET_HYP):
        out.append(_entry(f"set_inter_left_{i}", f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {s}",
                          [f"exact {h}.1", f"exact {h}.left"], "set", "mem_inter_proj"))
        out.append(_entry(f"set_inter_right_{i}", f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {t}",
                          [f"exact {h}.2", f"exact {h}.right"], "set", "mem_inter_proj"))
        out.append(_entry(f"set_union_left_{i}", f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s}) : {e} ∈ {s} ∪ {t}",
                          [f"exact Or.inl {h}"], "set", "mem_union_intro"))
        out.append(_entry(f"fs_inter_left_{i}", f"{F} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {s}",
                          [f"exact (Finset.mem_inter.mp {h}).1", f"exact Finset.mem_of_mem_inter_left {h}"], "finset", "mem_inter_proj"))
        out.append(_entry(f"fs_union_right_{i}", f"{F} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {t}) : {e} ∈ {s} ∪ {t}",
                          [f"exact Finset.mem_union.mpr (Or.inr {h})"], "finset", "mem_union_intro"))
    for i, (a, b, c) in enumerate(ORD_VARS):
        out.append(_entry(f"ord_refl_{i}", f"(α : Type) [Preorder α] ({a} : α) : {a} ≤ {a}",
                          ["exact le_rfl", f"exact le_refl {a}"], "order", "le_refl"))
        out.append(_entry(f"ord_trans_{i}", f"(α : Type) [Preorder α] ({a} {b} {c} : α) (hab : {a} ≤ {b}) (hbc : {b} ≤ {c}) : {a} ≤ {c}",
                          ["exact le_trans hab hbc", "exact hab.trans hbc"], "order", "le_trans"))
        out.append(_entry(f"ord_antisymm_{i}", f"(α : Type) [PartialOrder α] ({a} {b} : α) (hab : {a} ≤ {b}) (hba : {b} ≤ {a}) : {a} = {b}",
                          ["exact le_antisymm hab hba"], "order", "antisymm"))
    for i, (f, g, h) in enumerate(FN_VARS):
        out.append(_entry(f"fun_comp_assoc_{i}", f"(α β γ δ : Type) ({f} : α → β) ({g} : β → γ) ({h} : γ → δ) : ({h} ∘ {g}) ∘ {f} = {h} ∘ ({g} ∘ {f})",
                          ["rfl", "funext x; rfl"], "function", "comp_assoc"))
    for i, n in enumerate(["obj", "elem", "cnt"]):
        out.append(_entry(f"nat_add_assoc_{i}", f"({n} m k : Nat) : {n} + m + k = {n} + (m + k)",
                          [f"exact Nat.add_assoc {n} m k", "omega", "ring"], "nat", "add_assoc"))
    for i, x in enumerate(["lst", "items", "xs2"]):
        out.append(_entry(f"list_append_nil_{i}", f"(α : Type) ({x} : List α) : {x} ++ [] = {x}",
                          ["simp", f"exact List.append_nil {x}"], "list", "append_nil"))
    for i, (p, q) in enumerate([("P", "Q"), ("prop1", "prop2"), ("hp", "hq")]):
        out.append(_entry(f"logic_and_symm_{i}", f"({p} {q} : Prop) (hand : {p} ∧ {q}) : {q} ∧ {p}",
                          ["exact ⟨hand.2, hand.1⟩", "exact hand.symm", "tauto"], "logic", "and_symm"))
    return out


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("v32_stress_gen")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(ROOT.parent / "mini_elf_mathlib_probe"))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--out-seeds", default=str(ROOT / "data" / "seeds" / "v32_identifier_stress_seeds.jsonl"))
    ap.add_argument("--out-candidates", default=str(ROOT / "data" / "manual" / "v32_identifier_stress_candidates.jsonl"))
    ap.add_argument("--out-summary", default=str(ROOT / "data" / "processed" / "v32_mathlib" / "identifier_stress_summary.json"))
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

    verified = []
    thm_ok = {e["theorem_name"]: False for e in plan}
    for vd, e in zip(verdicts, meta):
        if vd.success:
            thm_ok[vd.theorem_name] = True
            verified.append({"theorem_name": vd.theorem_name, "theorem_statement": vd.statement,
                             "state_before": state_before(vd.statement), "tactic": vd.tactic,
                             "category": e["category"], "theorem_family": e["theorem_family"],
                             "source": "v32_identifier_stress", "verified": True, "mathlib": True,
                             "proof_head": proof_head(vd.tactic)})
    # seeds: one per theorem that has >=1 verified gold proof
    seeds = []
    by_name = {e["theorem_name"]: e for e in plan}
    for nm, ok in thm_ok.items():
        if not ok:
            continue
        e = by_name[nm]
        seeds.append({"theorem_name": nm, "theorem_statement": e["theorem_statement"],
                      "state_before": state_before(e["theorem_statement"]), "category": e["category"],
                      "theorem_family": e["theorem_family"], "expected_skill": e["category"],
                      "source": "v32_identifier_stress", "mathlib": True, "imports": [MATHLIB_IMPORT]})
    zero = [nm for nm, ok in thm_ok.items() if not ok]

    for p in (args.out_seeds, args.out_candidates, args.out_summary):
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    for path, rows in ((args.out_seeds, seeds), (args.out_candidates, verified)):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"config": "v32_identifier_stress", "n_theorems": len(plan), "n_solvable_theorems": len(seeds),
               "n_verified_candidates": len(verified), "n_zero_success_theorems": len(zero),
               "zero_success_theorems": zero, "by_category": dict(Counter(s["category"] for s in seeds)),
               "verifier": "TrustedMathlibVerifier", "total_lean_seconds": round(verifier.total_lean_seconds, 1),
               "uses_state_after": False, "uses_manual_oracle": False, "note": "EVAL benchmark; gold proofs are references, never model predictions"}
    Path(args.out_summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("v32 stress: theorems=%d solvable=%d verified_cands=%d zero=%d by_cat=%s",
                len(plan), len(seeds), len(verified), len(zero), summary["by_category"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
