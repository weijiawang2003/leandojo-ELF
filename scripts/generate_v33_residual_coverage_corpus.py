"""Mini-ELF v33 — Part 2: targeted residual-coverage corpus.

Adds verified siblings for exactly the v32 residual families (Part 1): the
theorem-shape / vocabulary gaps — `inter_assoc`/`union_assoc`, `le_trans` 3-4 hop
chains, `min_comm`/`max_comm`/`inf_comm`/`sup_comm`, `∅∩` — plus extra
projection/membership siblings with **subscript identifiers** (`h₁`, `proof₁`) to
reinforce the now-hardened canonical decode. NO broad expansion.

TrustedMathlibVerifier only; 80–200 verified rows; failed rows kept for taxonomy; no
held-out leakage (v25–v32 + stress + fresh guarded). Metadata: source,
target_residual/family/category, expected_skill, proof_head, repair_type
(vocabulary | API | projection | density | token_surface), uses_canonicalization.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mini_elf_lean.mathlib_batched_verifier import TrustedMathlibVerifier, MATHLIB_IMPORT  # noqa: E402
from generate_v25_mathlib_tierc_corpus import state_before  # noqa: E402
from generate_v27_mathlib_expanded_corpus import _v18_sets, proof_head  # noqa: E402

FD = "(α : Type) [DecidableEq α]"


def _e(name, stmt, cands, cat, fam, repair):
    return {"theorem_name": f"v33_{name}", "theorem_statement": stmt, "candidates": cands,
            "category": cat, "theorem_family": fam, "repair_type": repair}


def build_plan() -> List[Dict[str, Any]]:
    out = []
    # vocabulary: min/max/inf/sup comm (order)
    for i, (a, b) in enumerate([("a", "b"), ("x", "y"), ("p", "q"), ("m", "n"), ("c", "d"), ("u", "v"),
                                ("i", "j"), ("r", "w"), ("g", "h")]):
        out.append(_e(f"ord_min_comm_{i}", f"(α : Type) [LinearOrder α] ({a} {b} : α) : min {a} {b} = min {b} {a}", [f"exact min_comm {a} {b}"], "order", "min_max", "vocabulary"))
        out.append(_e(f"ord_max_comm_{i}", f"(α : Type) [LinearOrder α] ({a} {b} : α) : max {a} {b} = max {b} {a}", [f"exact max_comm {a} {b}"], "order", "min_max", "vocabulary"))
        out.append(_e(f"ord_inf_comm_{i}", f"(α : Type) [Lattice α] ({a} {b} : α) : {a} ⊓ {b} = {b} ⊓ {a}", [f"exact inf_comm {a} {b}"], "order", "lattice", "vocabulary"))
        out.append(_e(f"ord_sup_comm_{i}", f"(α : Type) [Lattice α] ({a} {b} : α) : {a} ⊔ {b} = {b} ⊔ {a}", [f"exact sup_comm {a} {b}"], "order", "lattice", "vocabulary"))
    # density: le_trans 3-4 hop chains
    for i, (a, b, c, d) in enumerate([("a", "b", "c", "d"), ("x", "y", "z", "w"), ("p", "q", "r", "s"), ("m", "n", "k", "l")]):
        out.append(_e(f"ord_le_trans4_{i}",
                      f"(α : Type) [Preorder α] ({a} {b} {c} {d} : α) (h1 : {a} ≤ {b}) (h2 : {b} ≤ {c}) (h3 : {c} ≤ {d}) : {a} ≤ {d}",
                      ["exact le_trans (le_trans h1 h2) h3", "exact h1.trans (h2.trans h3)"], "order", "le_trans", "density"))
        out.append(_e(f"ord_le_trans3_{i}",
                      f"(α : Type) [Preorder α] ({a} {b} {c} : α) (h1 : {a} ≤ {b}) (h2 : {b} ≤ {c}) : {a} ≤ {c}",
                      ["exact le_trans h1 h2", "exact h1.trans h2"], "order", "le_trans", "density"))
    # density: inter_assoc / union_assoc (set + finset)
    for i, (a, b, c) in enumerate([("s", "t", "u"), ("a", "b", "c"), ("p", "q", "r")]):
        out.append(_e(f"set_inter_assoc_{i}", f"(α : Type) ({a} {b} {c} : Set α) : {a} ∩ {b} ∩ {c} = {a} ∩ ({b} ∩ {c})", [f"exact Set.inter_assoc {a} {b} {c}", "ext x; simp [and_assoc]"], "set", "inter_assoc", "density"))
        out.append(_e(f"set_union_assoc_{i}", f"(α : Type) ({a} {b} {c} : Set α) : {a} ∪ {b} ∪ {c} = {a} ∪ ({b} ∪ {c})", [f"exact Set.union_assoc {a} {b} {c}", "ext x; simp [or_assoc]"], "set", "union_assoc", "density"))
        out.append(_e(f"fs_inter_assoc_{i}", f"{FD} ({a} {b} {c} : Finset α) : {a} ∩ {b} ∩ {c} = {a} ∩ ({b} ∩ {c})", [f"exact Finset.inter_assoc {a} {b} {c}"], "finset", "inter_assoc", "density"))
    # density: ∅∩ shapes (reinforce the v32 repair)
    for i, (s, t) in enumerate([("s", "t"), ("a", "b"), ("p", "q")]):
        out.append(_e(f"set_empty_inter_{i}", f"(α : Type) ({s} {t} : Set α) : (∅ : Set α) ∩ {s} ⊆ {t}", ["simp", "intro x hx; cases hx.1"], "set", "empty_subset", "density"))
        out.append(_e(f"set_empty_inter_eq_{i}", f"(α : Type) ({s} : Set α) : (∅ : Set α) ∩ {s} = ∅", ["simp", f"exact Set.empty_inter {s}"], "set", "empty_subset", "density"))
    # token_surface: projection/membership with SUBSCRIPT identifiers (canonicalization reinforce)
    for i, (s, t, e, h) in enumerate([("s", "t", "x", "h₁"), ("a", "b", "y", "h₂"), ("p", "q", "z", "proof₁")]):
        out.append(_e(f"set_mem_inter_left_sub_{i}", f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {s}", [f"exact {h}.1"], "set", "mem_inter_proj", "token_surface"))
        out.append(_e(f"set_mem_inter_right_sub_{i}", f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {t}", [f"exact {h}.2"], "set", "mem_inter_proj", "token_surface"))
        out.append(_e(f"set_mem_union_left_sub_{i}", f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s}) : {e} ∈ {s} ∪ {t}", [f"exact Or.inl {h}"], "set", "mem_union_intro", "token_surface"))
        out.append(_e(f"fs_mem_inter_left_sub_{i}", f"{FD} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {s}", [f"exact (Finset.mem_inter.mp {h}).1"], "finset", "mem_inter_proj", "token_surface"))
        out.append(_e(f"fs_mem_union_right_sub_{i}", f"{FD} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {t}) : {e} ∈ {s} ∪ {t}", [f"exact Finset.mem_union.mpr (Or.inr {h})"], "finset", "mem_union_intro", "token_surface"))
    return out


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _heldout_guard() -> Tuple[Set, Set]:
    triples: Set = set(); pairs: Set = set()
    def add_rows(rows):
        for r in rows:
            triples.add((r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", "")))
            pairs.add((r.get("theorem_statement", ""), r.get("state_before", "")))
    def add_seeds(rows):
        for s in rows:
            pairs.add((s.get("theorem_statement", ""), s.get("state_before", "")))
    v25 = ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"
    v25n = {s["theorem_name"] for s in _read(v25)}; add_seeds(_read(v25))
    add_rows([r for r in _read(ROOT / "data" / "traces" / "v25_mathlib_tierc_verified.jsonl") if r.get("theorem_name") in v25n])
    P = ROOT / "data" / "processed"
    dirs = [P / "v26_mathlib_specialist_splits" / "theorem_holdout", P / "v27_mathlib_specialist" / "theorem_holdout",
            P / "v28_mathlib_specialist" / "theorem_holdout", P / "v29_mathlib_specialist" / "theorem_holdout",
            P / "v29_mathlib_specialist" / "family_density_holdout", P / "v29_mathlib_specialist" / "low_density_holdout",
            P / "v30_mathlib_specialist" / "theorem_holdout", P / "v30_mathlib_specialist" / "targeted_family_holdout",
            P / "v31_canonical_mathlib" / "token_diversity_holdout"]
    for th in dirs:
        add_rows(_read(th / "test_rows.jsonl")); add_seeds(_read(th / "test_seeds.jsonl"))
    for sp in (ROOT / "data" / "seeds" / "v32_identifier_stress_seeds.jsonl",
               ROOT / "data" / "seeds" / "v32_fresh_mathlib_holdout_seeds.jsonl",
               ROOT / "data" / "seeds" / "v33_fresh_robustness_holdout_seeds.jsonl"):
        add_seeds(_read(sp))
    return triples, pairs


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("v33_residual_coverage")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(ROOT.parent / "mini_elf_mathlib_probe"))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--out-seeds", default=str(ROOT / "data" / "seeds" / "v33_residual_coverage_seeds.jsonl"))
    ap.add_argument("--out-candidates", default=str(ROOT / "data" / "manual" / "v33_residual_coverage_candidates.jsonl"))
    ap.add_argument("--out-train", default=str(ROOT / "data" / "processed" / "v33_mathlib_specialist" / "residual_coverage_rows.jsonl"))
    ap.add_argument("--out-failed", default=str(ROOT / "data" / "traces" / "v33_residual_coverage_failed.jsonl"))
    ap.add_argument("--out-summary", default=str(ROOT / "data" / "processed" / "v33_mathlib_specialist" / "residual_coverage_summary.json"))
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    plan = build_plan()
    names = [e["theorem_name"] for e in plan]
    assert len(names) == len(set(names)), "dup names: " + str([n for n in names if names.count(n) > 1][:5])
    verifier = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=300)
    if not verifier.warmup():
        logger.error("warmup failed"); return 2

    work, meta = [], []
    for e in plan:
        for c in dict.fromkeys(x.strip() for x in e["candidates"]):
            work.append((e["theorem_name"], e["theorem_statement"], c)); meta.append(e)
    verdicts = verifier.verify_many(work, confirm=True)
    v18n, v18t = _v18_sets()
    ho_t, ho_p = _heldout_guard()

    verified, failed, train_rows, seeds, seen_seed = [], [], [], [], set()
    n_fail = dropped = 0
    for vd, e in zip(verdicts, meta):
        st = state_before(vd.statement)
        if e["theorem_name"] not in seen_seed:
            seeds.append({"theorem_name": e["theorem_name"], "theorem_statement": e["theorem_statement"], "state_before": st,
                          "category": e["category"], "theorem_family": e["theorem_family"], "source": "v33_residual_coverage",
                          "mathlib": True, "imports": [MATHLIB_IMPORT]})
            seen_seed.add(e["theorem_name"])
        if not vd.success:
            n_fail += 1
            failed.append({"theorem_name": vd.theorem_name, "tactic": vd.tactic, "error_head": (vd.error or "")[:120], "verified": False})
            continue
        triple = (vd.statement, st, vd.tactic)
        if vd.theorem_name in v18n or triple in v18t or triple in ho_t or (vd.statement, st) in ho_p:
            dropped += 1; continue
        rec = {"theorem_name": vd.theorem_name, "theorem_statement": vd.statement, "state_before": st, "tactic": vd.tactic,
               "category": e["category"], "theorem_family": e["theorem_family"], "family": e["category"],
               "expected_skill": e["category"], "required_operation": e["category"], "source": "v33_residual_coverage",
               "corpus_source": "v33_residual_coverage", "target_residual": e["theorem_family"], "repair_type": e["repair_type"],
               "uses_canonicalization": True, "tactic_source": "verified", "split": "train", "transfer": "mathlib",
               "imports": [MATHLIB_IMPORT], "proof_head": proof_head(vd.tactic), "verified": True, "mathlib": True}
        verified.append(rec); train_rows.append(rec)

    for p in (args.out_seeds, args.out_candidates, args.out_train, args.out_failed, args.out_summary):
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    for path, rows in ((args.out_seeds, seeds), (args.out_candidates, verified), (args.out_train, train_rows), (args.out_failed, failed)):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"config": "v33_residual_coverage", "n_theorems": len(plan), "n_proposed": len(work),
               "n_verified": len(verified), "n_failed": n_fail, "n_dropped_guard": dropped,
               "by_family": dict(Counter(r["theorem_family"] for r in verified)),
               "by_repair_type": dict(Counter(r["repair_type"] for r in verified)),
               "verifier": "TrustedMathlibVerifier", "total_lean_seconds": round(verifier.total_lean_seconds, 1),
               "uses_state_after": False, "uses_manual_oracle": False, "uses_mathlib": True}
    Path(args.out_summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("v33 residual coverage: verified=%d failed=%d dropped=%d by_repair=%s",
                len(verified), n_fail, dropped, summary["by_repair_type"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
