"""Mini-ELF v30 — Part 3: targeted density-repair corpus.

The v29 density law (pass@10 0.68→0.83→0.94 by training siblings, reliable at ~4–6) is
now actionable. v30 uses it for a **surgical** repair — NOT broad expansion — of the
families Part 1/2 flagged:

  A. nat `add_assoc`        (v25 regression; density 0 → 6)         — `Nat.add_assoc`/`omega`/`ring`
  B. set `empty_subset`     (v25 regression; density 0 → 6)         — `Set.empty_subset`/`simp`
  C. order `le_refl`/`le_rfl`(residual; density 3 → 6)              — `le_rfl`/`le_refl`
  D. set projection         (token-diversity for the `_3` residual) — `hw.1`/`.2`, `mem_inter_iff`
  E. set `union_subset`/`subset_inter` (low-density 4 → 6)
  F. finset projection      (token-diversity + finset `empty_subset`)
  G. function `comp_assoc`  (low-density 3 → 6, renamed incl. φ ψ χ)

Token-diversity families (D, F) get **fresh element/hyp/set tokens** (`w/hw`, `e/he`,
`k/hk`, sets `u,v`/`c,d`/`g,h`) so the projection shape generalises across identifiers
— the held-out `_3` (`u,v,w,hw`) members themselves are guard-dropped, never trained.

Every candidate is verified by `TrustedMathlibVerifier` (sentinel+confirm+rescue).
Leakage guards: v18 + v25/v26/v27/v28/**v29** held-out test benchmarks (including the
v29 theorem / family-density / low-density holdouts). All names `v30_*`.

Outputs:
  data/seeds/v30_targeted_density_seeds.jsonl
  data/manual/v30_targeted_density_candidates.jsonl   (verified targets)
  data/traces/v30_targeted_density_{verified,failed}.jsonl
  data/processed/v30_mathlib_specialist/targeted_train_rows.jsonl
  data/processed/v30_mathlib_specialist/targeted_summary.json

Honesty: real import-Mathlib typecheck; trusted verifier only; no state_after; no
manual oracle as predictions; Mathlib real & external.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_v30_targeted_density_corpus")
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"

Entry = Dict[str, Any]
# previous (v29 train) density per target family — from Part 2 audit
PREV_DENSITY = {
    "add_assoc": 0, "empty_subset": 0, "le_refl": 3, "mem_inter_proj": 8,
    "mem_union_intro": 9, "union_subset": 4, "subset_inter": 4, "comp_assoc": 3,
}


def _entry(name, stmt, cands, cat, fam, skill) -> Entry:
    return {"theorem_name": f"v30_{name}", "theorem_statement": stmt, "candidates": cands,
            "category": cat, "theorem_family": fam, "expected_skill": skill}


# A. nat add_assoc — fresh var-sets (a,b,c/m,n,k/i,j,l already in v28/v29; avoid them)
def add_assoc_family() -> List[Entry]:
    out = []
    for x, y, z in [("x", "y", "z"), ("p", "q", "r"), ("g", "h", "i"), ("u", "v", "w"), ("d", "e", "f"), ("r", "s", "t")]:
        out.append(_entry(f"nat_add_assoc_{x}{y}{z}", f"({x} {y} {z} : Nat) : {x} + {y} + {z} = {x} + ({y} + {z})",
                          [f"exact Nat.add_assoc {x} {y} {z}", "omega", "ring", "simp [Nat.add_assoc]"],
                          "nat", "add_assoc", "arithmetic"))
        out.append(_entry(f"nat_add_assoc_rev_{x}{y}{z}", f"({x} {y} {z} : Nat) : {x} + ({y} + {z}) = {x} + {y} + {z}",
                          [f"exact (Nat.add_assoc {x} {y} {z}).symm", "omega", "ring", "simp [Nat.add_assoc]"],
                          "nat", "add_assoc", "arithmetic"))
    return out


# B. set empty_subset + variants
def set_empty_family() -> List[Entry]:
    out = []
    for s in ["s", "t", "a", "u", "A", "B"]:
        out.append(_entry(f"set_empty_subset_{s}", f"(α : Type) ({s} : Set α) : (∅ : Set α) ⊆ {s}",
                          [f"exact Set.empty_subset {s}", "simp", "intro x hx; cases hx"],
                          "set", "empty_subset", "set"))
    out.append(_entry("set_empty_inter_subset", "(α : Type) (s t : Set α) : (∅ : Set α) ∩ s ⊆ t",
                      ["intro x hx; cases hx.1", "simp"], "set", "empty_subset", "set"))
    out.append(_entry("set_empty_subset_union", "(α : Type) (s t : Set α) : (∅ : Set α) ⊆ s ∪ t",
                      ["exact Set.empty_subset _", "simp"], "set", "empty_subset", "set"))
    return out


# C. order le_refl / le_rfl
def le_refl_family() -> List[Entry]:
    out = []
    for a in ["a", "b", "x", "y", "m", "n"]:
        out.append(_entry(f"ord_le_refl_{a}", f"(α : Type) [Preorder α] ({a} : α) : {a} ≤ {a}",
                          ["exact le_rfl", f"exact le_refl {a}"], "order", "le_refl", "order"))
    for n in ["n", "m", "k"]:
        out.append(_entry(f"nat_le_refl_{n}", f"({n} : Nat) : {n} ≤ {n}",
                          ["exact le_rfl", f"exact Nat.le_refl {n}", "omega"], "order", "le_refl", "order"))
    return out


# D. set projection — fresh element/hyp/set tokens (NOT the held-out _3 u,v,w,hw shapes)
def set_proj_tokens() -> List[Entry]:
    out = []
    combos = [("u", "v", "k", "hk"), ("c", "d", "e", "he"), ("g", "h", "m", "hm"), ("u", "v", "e", "he")]
    for s, t, e, h in combos:
        out.append(_entry(f"set_mem_inter_left_{e}{s}{t}",
                          f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {s}",
                          [f"exact {h}.1", f"exact (Set.mem_inter_iff.mp {h}).1"], "set", "mem_inter_proj", "set"))
        out.append(_entry(f"set_mem_inter_right_{e}{s}{t}",
                          f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {t}",
                          [f"exact {h}.2", f"exact (Set.mem_inter_iff.mp {h}).2"], "set", "mem_inter_proj", "set"))
        out.append(_entry(f"set_mem_union_left_{e}{s}{t}",
                          f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s}) : {e} ∈ {s} ∪ {t}",
                          [f"exact Or.inl {h}", f"exact Set.mem_union_left {t} {h}"], "set", "mem_union_intro", "set"))
        out.append(_entry(f"set_mem_union_right_{e}{s}{t}",
                          f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {t}) : {e} ∈ {s} ∪ {t}",
                          [f"exact Or.inr {h}", f"exact Set.mem_union_right {s} {h}"], "set", "mem_union_intro", "set"))
    return out


# E. set union_subset / subset_inter — fresh 3-var sets
def set_union_subset_family() -> List[Entry]:
    out = []
    for s, t, u in [("g", "h", "i"), ("d", "e", "f"), ("r", "s", "w")]:
        out.append(_entry(f"set_union_subset_{s}{t}{u}",
                          f"(α : Type) ({s} {t} {u} : Set α) (hs : {s} ⊆ {u}) (ht : {t} ⊆ {u}) : {s} ∪ {t} ⊆ {u}",
                          ["exact Set.union_subset hs ht", "rintro x (h | h); exact hs h; exact ht h"],
                          "set", "union_subset", "set"))
        out.append(_entry(f"set_subset_inter_{s}{t}{u}",
                          f"(α : Type) ({s} {t} {u} : Set α) (hs : {u} ⊆ {s}) (ht : {u} ⊆ {t}) : {u} ⊆ {s} ∩ {t}",
                          ["exact Set.subset_inter hs ht", "intro x hx; exact ⟨hs hx, ht hx⟩"],
                          "set", "subset_inter", "set"))
    return out


# F. finset projection + empty_subset — fresh tokens
def finset_family() -> List[Entry]:
    out = []
    F = "(α : Type) [DecidableEq α]"
    for s, t, e, h in [("u", "v", "k", "hk"), ("c", "d", "e", "he"), ("g", "h", "m", "hm")]:
        out.append(_entry(f"fs_mem_inter_left_{e}{s}{t}",
                          f"{F} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {s}",
                          [f"exact (Finset.mem_inter.mp {h}).1", f"exact Finset.mem_of_mem_inter_left {h}"],
                          "finset", "mem_inter_proj", "finset"))
        out.append(_entry(f"fs_mem_inter_right_{e}{s}{t}",
                          f"{F} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {t}",
                          [f"exact (Finset.mem_inter.mp {h}).2", f"exact Finset.mem_of_mem_inter_right {h}"],
                          "finset", "mem_inter_proj", "finset"))
        out.append(_entry(f"fs_mem_union_left_{e}{s}{t}",
                          f"{F} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {s}) : {e} ∈ {s} ∪ {t}",
                          [f"exact Finset.mem_union.mpr (Or.inl {h})", f"exact Finset.mem_union_left {t} {h}"],
                          "finset", "mem_union_intro", "finset"))
    for s in ["s", "t", "a", "u"]:
        out.append(_entry(f"fs_empty_subset_{s}", f"{F} ({s} : Finset α) : (∅ : Finset α) ⊆ {s}",
                          [f"exact Finset.empty_subset {s}", "simp"], "finset", "empty_subset", "finset"))
    return out


# G. function comp_assoc — fresh renamed triples incl. greek
def comp_assoc_family() -> List[Entry]:
    out = []
    for f, g, h in [("k", "l", "m"), ("u", "v", "w"), ("φ", "ψ", "χ"), ("a", "b", "c"), ("r", "s", "t")]:
        out.append(_entry(f"fun_comp_assoc_{f}{g}{h}",
                          f"(α β γ δ : Type) ({f} : α → β) ({g} : β → γ) ({h} : γ → δ) : ({h} ∘ {g}) ∘ {f} = {h} ∘ ({g} ∘ {f})",
                          ["rfl", "funext x; rfl", "ext x; rfl"], "function", "comp_assoc", "function"))
    return out


def build_plan() -> List[Entry]:
    plan: List[Entry] = []
    plan += add_assoc_family()
    plan += set_empty_family()
    plan += le_refl_family()
    plan += set_proj_tokens()
    plan += set_union_subset_family()
    plan += finset_family()
    plan += comp_assoc_family()
    return plan


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _heldout_guard() -> Tuple[Set, Set]:
    """(triples, stmt_state_pairs) for v25..v29 held-out test benchmarks (incl. v29
    theorem / family-density / low-density holdouts)."""
    triples: Set = set()
    pairs: Set = set()

    def add_rows(rows):
        for r in rows:
            triples.add((r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", "")))
            pairs.add((r.get("theorem_statement", ""), r.get("state_before", "")))

    def add_seeds(rows):
        for s in rows:
            pairs.add((s.get("theorem_statement", ""), s.get("state_before", "")))

    v25 = ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"
    v25_names = {s["theorem_name"] for s in _read(v25)}
    add_seeds(_read(v25))
    add_rows([r for r in _read(ROOT / "data" / "traces" / "v25_mathlib_tierc_verified.jsonl")
              if r.get("theorem_name") in v25_names])
    th_dirs = [
        ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout",
        ROOT / "data" / "processed" / "v27_mathlib_specialist" / "theorem_holdout",
        ROOT / "data" / "processed" / "v28_mathlib_specialist" / "theorem_holdout",
        ROOT / "data" / "processed" / "v29_mathlib_specialist" / "theorem_holdout",
        ROOT / "data" / "processed" / "v29_mathlib_specialist" / "family_density_holdout",
        ROOT / "data" / "processed" / "v29_mathlib_specialist" / "low_density_holdout",
    ]
    for th in th_dirs:
        add_rows(_read(th / "test_rows.jsonl"))
        add_seeds(_read(th / "test_seeds.jsonl"))
    return triples, pairs


def _bool(s: str, sub: str) -> bool:
    return sub in (s or "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--out-seeds", default=str(ROOT / "data" / "seeds" / "v30_targeted_density_seeds.jsonl"))
    ap.add_argument("--out-candidates", default=str(ROOT / "data" / "manual" / "v30_targeted_density_candidates.jsonl"))
    ap.add_argument("--out-verified", default=str(ROOT / "data" / "traces" / "v30_targeted_density_verified.jsonl"))
    ap.add_argument("--out-failed", default=str(ROOT / "data" / "traces" / "v30_targeted_density_failed.jsonl"))
    ap.add_argument("--out-train-rows", default=str(ROOT / "data" / "processed" / "v30_mathlib_specialist" / "targeted_train_rows.jsonl"))
    ap.add_argument("--summary", default=str(ROOT / "data" / "processed" / "v30_mathlib_specialist" / "targeted_summary.json"))
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--batch-size", type=int, default=80)
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    plan = build_plan()
    names = [e["theorem_name"] for e in plan]
    assert len(names) == len(set(names)), "duplicate v30 names: " + str([n for n in names if names.count(n) > 1][:5])
    logger.info("v30 targeted plan: %d theorems", len(plan))

    verifier = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=args.timeout, batch_size=args.batch_size)
    if not verifier.warmup():
        logger.error("Mathlib warmup FAILED"); return 2
    logger.info("warmup ok")

    work: List[Tuple[str, str, str]] = []
    work_meta: List[Entry] = []
    for entry in plan:
        seen_c: Set[str] = set()
        for cand in entry["candidates"]:
            c = cand.strip()
            if c in seen_c:
                continue
            seen_c.add(c)
            work.append((entry["theorem_name"], entry["theorem_statement"], c))
            work_meta.append(entry)
    logger.info("verifying %d candidate rows (trusted) ...", len(work))
    verdicts = verifier.verify_many(work, confirm=True)
    logger.info("verification done: %d invocations, %.1fs", verifier.n_invocations, verifier.total_lean_seconds)

    v18_names, v18_triples = _v18_sets()
    ho_triples, ho_pairs = _heldout_guard()
    for p in (args.out_seeds, args.out_candidates, args.out_verified, args.out_failed, args.out_train_rows):
        Path(p).parent.mkdir(parents=True, exist_ok=True)

    seeds = []
    for e in plan:
        seeds.append({"theorem_name": e["theorem_name"], "theorem_statement": e["theorem_statement"],
                      "state_before": state_before(e["theorem_statement"]),
                      "template": f"example {e['theorem_statement']} := by\n  __TACTIC__", "placeholder": "__TACTIC__",
                      "imports": [MATHLIB_IMPORT], "category": e["category"], "expected_skill": e["expected_skill"],
                      "theorem_family": e["theorem_family"], "source": "v30_targeted_density", "mathlib": True})

    verified, failed, train_rows = [], [], []
    per_cat: Dict[str, Dict[str, int]] = defaultdict(lambda: {"theorems": 0, "proposed": 0, "verified": 0, "failed": 0})
    per_fam: Dict[str, Set[str]] = defaultdict(set)
    for e in plan:
        per_cat[e["category"]]["theorems"] += 1
    lean_ok = {e["theorem_name"]: False for e in plan}
    has_row = {e["theorem_name"]: False for e in plan}
    n_timeout = n_rejected = dn = dt = dpair = 0

    for vd, entry in zip(verdicts, work_meta):
        nm, stmt, cand = vd.theorem_name, vd.statement, vd.tactic
        cat, fam = entry["category"], entry["theorem_family"]
        st = state_before(stmt)
        per_cat[cat]["proposed"] += 1
        rec = {"theorem_name": nm, "theorem_statement": stmt, "state_before": st, "tactic": cand,
               "category": cat, "theorem_family": fam, "expected_skill": entry["expected_skill"],
               "transfer": "mathlib", "imports": [MATHLIB_IMPORT], "corpus_source": "v30_targeted_density",
               "source": "v30_targeted_density", "target_family": fam,
               "previous_density": PREV_DENSITY.get(fam, 0), "target_density": 6,
               "verifier": "TrustedMathlibVerifier (sentinel+confirm+rescue, import Mathlib)",
               "proof_head": proof_head(cand),
               "uses_set": cat == "set", "uses_finset": cat == "finset", "uses_order": cat == "order",
               "uses_nat": cat == "nat", "uses_function": cat == "function", "density_repair": True,
               "uses_simp": _bool(cand, "simp"), "uses_ext": _bool(cand, "ext") or _bool(cand, "funext"),
               "uses_omega": _bool(cand, "omega"), "mathlib": True}
        if not vd.success:
            per_cat[cat]["failed"] += 1; n_rejected += 1
            if vd.error and "timeout" in vd.error:
                n_timeout += 1
            failed.append({**rec, "verified": False, "error_head": (vd.error or "")[:120]})
            continue
        lean_ok[nm] = True
        if nm in v18_names:
            dn += 1; continue
        triple = (stmt, st, cand)
        if triple in v18_triples:
            dt += 1; continue
        if triple in ho_triples or (stmt, st) in ho_pairs:
            dpair += 1; continue
        per_cat[cat]["verified"] += 1
        per_fam[fam].add(nm)
        has_row[nm] = True
        verified.append({**rec, "verified": True})
        train_rows.append({"theorem_name": nm, "theorem_statement": stmt, "state_before": st, "tactic": cand,
                           "category": cat, "family": cat, "theorem_family": fam,
                           "expected_skill": entry["expected_skill"], "required_operation": entry["expected_skill"],
                           "target_family": fam, "density_repair": True, "corpus_source": "v30_targeted_density",
                           "tactic_source": "verified", "split": "train", "transfer": "mathlib",
                           "proof_head": proof_head(cand), "mathlib": True})

    zero_lean = sorted(nm for nm, ok in lean_ok.items() if not ok)
    stripped = sorted(nm for nm in lean_ok if lean_ok[nm] and not has_row[nm])

    def _dump(path, rows):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    _dump(args.out_seeds, seeds)
    _dump(args.out_candidates, verified)
    _dump(args.out_verified, verified)
    _dump(args.out_failed, failed)
    _dump(args.out_train_rows, train_rows)

    added = {f"{cat}::{fam}" if "::" not in fam else fam: 0 for fam in []}
    fam_added = {fam: len(nms) for fam, nms in sorted(per_fam.items())}
    summary = {
        "config": "v30_targeted_density", "mathlib_available": True,
        "lean_verifier": "TrustedMathlibVerifier (sentinel+confirm+rescue, import Mathlib)",
        "n_theorems": len(plan), "n_candidates_proposed": len(work),
        "n_candidates_verified": len(verified), "n_candidates_lean_rejected": n_rejected,
        "n_timeout": n_timeout, "n_zero_lean_success_theorems": len(zero_lean),
        "zero_lean_success_theorems": zero_lean,
        "n_theorems_stripped_to_zero_by_guards": len(stripped),
        "dropped_v18_name": dn, "dropped_v18_triple": dt, "dropped_heldout": dpair,
        "by_category": {k: dict(v) for k, v in per_cat.items()},
        "family_theorems_added": fam_added,
        "previous_density": PREV_DENSITY,
        "verified_proof_heads": dict(Counter(r["proof_head"] for r in verified).most_common()),
        "total_lean_seconds": round(verifier.total_lean_seconds, 1),
        "n_lean_invocations": verifier.n_invocations,
        "uses_state_after": False, "uses_manual_oracle": False, "uses_mathlib": True,
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("v30 targeted corpus: theorems=%d verified_rows=%d rejected=%d drops v18/heldout=%d/%d",
                len(plan), len(verified), n_rejected, dn + dt, dpair)
    for fam, n in fam_added.items():
        logger.info("  +%-22s theorems_added=%d (prev_density=%d)", fam, n, PREV_DENSITY.get(fam, 0))
    if zero_lean:
        logger.warning("coverage gaps (Lean rejected ALL candidates): %s", zero_lean)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
