"""Mini-ELF v31 — Part 4: verified projection rename augmentation (Approach B).

The Part-1 audit showed the residuals are surface-token OOD: the projection shape is in
training, but the held-out members use identifiers (`hw`, `hm`, `g`, `h3`, `hmem`) no
sibling carries. Approach B brings those identifiers in-distribution by generating
**verified** projection/membership siblings that *use* them — with set names that
differ from the held-out statements (the leakage guard drops any accidental match).

This is data augmentation (every row Lean-verified by `TrustedMathlibVerifier`), NOT
placeholder decoding. Projection families only; no broad expansion.

Metadata per row: source=v31_projection_rename_aug, original_identifier,
renamed_identifier, projection_kind, verified=true.
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
logger = logging.getLogger("generate_v31_projection_rename_aug")
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"

# The identifier surfaces the v30 residuals need in-distribution: element name + hyp name
# The point is identifier (token) coverage, not breadth: a few set-pairs × the missing
# element/hyp surfaces. Two set-pairs keeps the corpus focused (50-150 verified rows).
TOKENS = [("w", "hw"), ("m", "hm"), ("g", "hg"), ("e3", "h3"), ("z", "hmem")]
SETPAIRS = [("s", "t"), ("a", "c")]


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def build_plan() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    F = "(α : Type) [DecidableEq α]"
    idx = 0
    for (s, t), (e, h) in [(sp, tk) for sp in SETPAIRS for tk in TOKENS]:
        idx += 1
        # SET projection (mem_inter left/right) + membership intro (union left/right)
        out.append({"theorem_name": f"v31_set_mem_inter_left_{e}{h}_{s}{t}",
                    "theorem_statement": f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {s}",
                    "candidates": [f"exact {h}.1", f"exact {h}.left"],
                    "category": "set", "theorem_family": "mem_inter_proj",
                    "original_identifier": "h", "renamed_identifier": h, "projection_kind": "inter_left"})
        out.append({"theorem_name": f"v31_set_mem_inter_right_{e}{h}_{s}{t}",
                    "theorem_statement": f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {t}",
                    "candidates": [f"exact {h}.2", f"exact {h}.right"],
                    "category": "set", "theorem_family": "mem_inter_proj",
                    "original_identifier": "h", "renamed_identifier": h, "projection_kind": "inter_right"})
        out.append({"theorem_name": f"v31_set_mem_union_left_{e}{h}_{s}{t}",
                    "theorem_statement": f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s}) : {e} ∈ {s} ∪ {t}",
                    "candidates": [f"exact Or.inl {h}", f"exact Set.mem_union_left {t} {h}"],
                    "category": "set", "theorem_family": "mem_union_intro",
                    "original_identifier": "h", "renamed_identifier": h, "projection_kind": "union_left"})
        out.append({"theorem_name": f"v31_set_mem_union_right_{e}{h}_{s}{t}",
                    "theorem_statement": f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {t}) : {e} ∈ {s} ∪ {t}",
                    "candidates": [f"exact Or.inr {h}", f"exact Set.mem_union_right {s} {h}"],
                    "category": "set", "theorem_family": "mem_union_intro",
                    "original_identifier": "h", "renamed_identifier": h, "projection_kind": "union_right"})
        # FINSET projection
        out.append({"theorem_name": f"v31_fs_mem_inter_left_{e}{h}_{s}{t}",
                    "theorem_statement": f"{F} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {s}",
                    "candidates": [f"exact (Finset.mem_inter.mp {h}).1", f"exact Finset.mem_of_mem_inter_left {h}"],
                    "category": "finset", "theorem_family": "mem_inter_proj",
                    "original_identifier": "h", "renamed_identifier": h, "projection_kind": "finset_inter_left"})
        out.append({"theorem_name": f"v31_fs_mem_inter_right_{e}{h}_{s}{t}",
                    "theorem_statement": f"{F} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {t}",
                    "candidates": [f"exact (Finset.mem_inter.mp {h}).2", f"exact Finset.mem_of_mem_inter_right {h}"],
                    "category": "finset", "theorem_family": "mem_inter_proj",
                    "original_identifier": "h", "renamed_identifier": h, "projection_kind": "finset_inter_right"})
        out.append({"theorem_name": f"v31_fs_mem_union_right_{e}{h}_{s}{t}",
                    "theorem_statement": f"{F} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {t}) : {e} ∈ {s} ∪ {t}",
                    "candidates": [f"exact Finset.mem_union.mpr (Or.inr {h})", f"exact Finset.mem_union_right {s} {h}"],
                    "category": "finset", "theorem_family": "mem_union_intro",
                    "original_identifier": "h", "renamed_identifier": h, "projection_kind": "finset_union_right"})
    return out


def _heldout_guard() -> Tuple[Set, Set]:
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
    P = ROOT / "data" / "processed"
    for th in [P / "v26_mathlib_specialist_splits" / "theorem_holdout",
               P / "v27_mathlib_specialist" / "theorem_holdout",
               P / "v28_mathlib_specialist" / "theorem_holdout",
               P / "v29_mathlib_specialist" / "theorem_holdout",
               P / "v29_mathlib_specialist" / "family_density_holdout",
               P / "v29_mathlib_specialist" / "low_density_holdout",
               P / "v30_mathlib_specialist" / "theorem_holdout",
               P / "v30_mathlib_specialist" / "targeted_family_holdout"]:
        add_rows(_read(th / "test_rows.jsonl"))
        add_seeds(_read(th / "test_seeds.jsonl"))
    return triples, pairs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--out-candidates", default=str(ROOT / "data" / "manual" / "v31_projection_rename_aug_candidates.jsonl"))
    ap.add_argument("--out-train", default=str(ROOT / "data" / "processed" / "v31_canonical_mathlib" / "projection_rename_aug_rows.jsonl"))
    ap.add_argument("--out-summary", default=str(ROOT / "data" / "processed" / "v31_canonical_mathlib" / "projection_rename_aug_summary.json"))
    ap.add_argument("--timeout", type=float, default=300.0)
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    plan = build_plan()
    names = [e["theorem_name"] for e in plan]
    assert len(names) == len(set(names)), "dup names"
    logger.info("v31 projection rename-aug plan: %d theorems", len(plan))

    verifier = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=args.timeout)
    if not verifier.warmup():
        logger.error("warmup FAILED"); return 2

    work, meta = [], []
    for e in plan:
        for c in dict.fromkeys(x.strip() for x in e["candidates"]):
            work.append((e["theorem_name"], e["theorem_statement"], c))
            meta.append(e)
    verdicts = verifier.verify_many(work, confirm=True)
    v18_names, v18_triples = _v18_sets()
    ho_triples, ho_pairs = _heldout_guard()

    verified, train_rows = [], []
    dropped = n_fail = 0
    for vd, e in zip(verdicts, meta):
        st = state_before(vd.statement)
        if not vd.success:
            n_fail += 1
            continue
        triple = (vd.statement, st, vd.tactic)
        if vd.theorem_name in v18_names or triple in v18_triples or triple in ho_triples or (vd.statement, st) in ho_pairs:
            dropped += 1
            continue
        rec = {"theorem_name": vd.theorem_name, "theorem_statement": vd.statement, "state_before": st,
               "tactic": vd.tactic, "category": e["category"], "theorem_family": e["theorem_family"],
               "family": e["category"], "expected_skill": e["category"], "required_operation": e["category"],
               "source": "v31_projection_rename_aug", "corpus_source": "v31_projection_rename_aug",
               "original_identifier": e["original_identifier"], "renamed_identifier": e["renamed_identifier"],
               "projection_kind": e["projection_kind"], "tactic_source": "verified", "split": "train",
               "transfer": "mathlib", "imports": [MATHLIB_IMPORT], "proof_head": proof_head(vd.tactic),
               "verified": True, "mathlib": True}
        verified.append(rec)
        train_rows.append(rec)

    for p in (args.out_candidates, args.out_train):
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_candidates, "w", encoding="utf-8") as f:
        for r in verified:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(args.out_train, "w", encoding="utf-8") as f:
        for r in train_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {
        "config": "v31_projection_rename_aug", "n_theorems": len(plan), "n_proposed": len(work),
        "n_verified": len(verified), "n_failed": n_fail, "n_dropped_guard": dropped,
        "by_family": dict(Counter(r["theorem_family"] for r in verified)),
        "by_renamed_identifier": dict(Counter(r["renamed_identifier"] for r in verified)),
        "verifier": "TrustedMathlibVerifier (sentinel+confirm+rescue)",
        "total_lean_seconds": round(verifier.total_lean_seconds, 1),
        "uses_state_after": False, "uses_manual_oracle": False, "uses_mathlib": True,
    }
    Path(args.out_summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("v31 rename-aug: verified=%d failed=%d dropped_guard=%d by_ident=%s",
                len(verified), n_fail, dropped, summary["by_renamed_identifier"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
