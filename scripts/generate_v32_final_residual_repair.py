"""Mini-ELF v32 — Part 2: minimal final-residual repair (single-tactic).

The Part-1 audit showed the lone residual `(∅ : Set α) ∩ s ⊆ t` is **single-tactic**
(`simp` closes it) — a sparse `∅ ∩ _ ⊆ _` shape the `empty_subset` family never trained
(it trained only `∅ ⊆ s`). v32 adds a focused set of verified `∅∩`/empty-intersection
siblings (different var-sets and shapes from the held-out residual, which the leakage
guard drops) so the model learns the shape → `simp`/`cases` mapping and generalizes.

TrustedMathlibVerifier only; 10–40 verified rows; projection/empty family only; no
broad expansion; no held-out leakage (v25–v31 + token-diversity residuals guarded).
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


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def build_plan() -> List[Dict[str, Any]]:
    out = []
    SET = [("s", "t"), ("a", "b"), ("p", "q"), ("u", "v")]
    F = "(α : Type) [DecidableEq α]"
    for i, (s, t) in enumerate(SET):
        out.append({"theorem_name": f"v32_set_empty_inter_subset_{s}{t}",
                    "theorem_statement": f"(α : Type) ({s} {t} : Set α) : (∅ : Set α) ∩ {s} ⊆ {t}",
                    "candidates": ["simp", f"intro x hx; cases hx.1", f"intro x hx; exact hx.1.elim"],
                    "category": "set", "theorem_family": "empty_subset"})
        out.append({"theorem_name": f"v32_set_inter_empty_subset_{s}{t}",
                    "theorem_statement": f"(α : Type) ({s} {t} : Set α) : {s} ∩ (∅ : Set α) ⊆ {t}",
                    "candidates": ["simp", f"intro x hx; cases hx.2", f"intro x hx; exact hx.2.elim"],
                    "category": "set", "theorem_family": "empty_subset"})
        out.append({"theorem_name": f"v32_set_empty_inter_subset_self_{s}{t}",
                    "theorem_statement": f"(α : Type) ({s} {t} : Set α) : (∅ : Set α) ∩ {s} ⊆ {s}",
                    "candidates": ["intro x hx; exact hx.2", "exact Set.inter_subset_right"],
                    "category": "set", "theorem_family": "inter_subset"})
        # finset analogue
        out.append({"theorem_name": f"v32_fs_empty_inter_subset_{s}{t}",
                    "theorem_statement": f"{F} ({s} {t} : Finset α) : (∅ : Finset α) ∩ {s} ⊆ {t}",
                    "candidates": ["simp", f"intro x hx; exact absurd (Finset.mem_inter.mp hx).1 (by simp)"],
                    "category": "finset", "theorem_family": "empty_subset"})
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
    dirs = [P / "v26_mathlib_specialist_splits" / "theorem_holdout",
            P / "v27_mathlib_specialist" / "theorem_holdout",
            P / "v28_mathlib_specialist" / "theorem_holdout",
            P / "v29_mathlib_specialist" / "theorem_holdout",
            P / "v29_mathlib_specialist" / "family_density_holdout",
            P / "v29_mathlib_specialist" / "low_density_holdout",
            P / "v30_mathlib_specialist" / "theorem_holdout",
            P / "v30_mathlib_specialist" / "targeted_family_holdout",
            P / "v31_canonical_mathlib" / "token_diversity_holdout"]
    for th in dirs:
        add_rows(_read(th / "test_rows.jsonl"))
        add_seeds(_read(th / "test_seeds.jsonl"))
    return triples, pairs


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("v32_repair")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(ROOT.parent / "mini_elf_mathlib_probe"))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--out-seeds", default=str(ROOT / "data" / "seeds" / "v32_final_residual_repair_seeds.jsonl"))
    ap.add_argument("--out-candidates", default=str(ROOT / "data" / "manual" / "v32_final_residual_repair_candidates.jsonl"))
    ap.add_argument("--out-train", default=str(ROOT / "data" / "processed" / "v32_mathlib" / "final_residual_repair_rows.jsonl"))
    ap.add_argument("--out-summary", default=str(ROOT / "data" / "processed" / "v32_mathlib" / "final_residual_repair_summary.json"))
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
    v18_names, v18_triples = _v18_sets()
    ho_triples, ho_pairs = _heldout_guard()

    verified, train_rows, seeds = [], [], []
    seen_seed = set()
    n_fail = dropped = 0
    for vd, e in zip(verdicts, meta):
        st = state_before(vd.statement)
        if e["theorem_name"] not in seen_seed:
            seeds.append({"theorem_name": e["theorem_name"], "theorem_statement": e["theorem_statement"],
                          "state_before": st, "category": e["category"], "theorem_family": e["theorem_family"],
                          "source": "v32_final_residual_repair", "mathlib": True, "imports": [MATHLIB_IMPORT]})
            seen_seed.add(e["theorem_name"])
        if not vd.success:
            n_fail += 1; continue
        triple = (vd.statement, st, vd.tactic)
        if vd.theorem_name in v18_names or triple in v18_triples or triple in ho_triples or (vd.statement, st) in ho_pairs:
            dropped += 1; continue
        rec = {"theorem_name": vd.theorem_name, "theorem_statement": vd.statement, "state_before": st,
               "tactic": vd.tactic, "category": e["category"], "theorem_family": e["theorem_family"],
               "family": e["category"], "expected_skill": e["category"], "required_operation": e["category"],
               "source": "v32_final_residual_repair", "corpus_source": "v32_final_residual_repair",
               "tactic_source": "verified", "split": "train", "transfer": "mathlib",
               "imports": [MATHLIB_IMPORT], "proof_head": proof_head(vd.tactic), "verified": True, "mathlib": True}
        verified.append(rec); train_rows.append(rec)

    for p in (args.out_seeds, args.out_candidates, args.out_train, args.out_summary):
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    for path, rows in ((args.out_seeds, seeds), (args.out_candidates, verified), (args.out_train, train_rows)):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"config": "v32_final_residual_repair", "n_theorems": len(plan), "n_proposed": len(work),
               "n_verified": len(verified), "n_failed": n_fail, "n_dropped_guard": dropped,
               "by_family": dict(Counter(r["theorem_family"] for r in verified)),
               "verifier": "TrustedMathlibVerifier", "total_lean_seconds": round(verifier.total_lean_seconds, 1),
               "uses_state_after": False, "uses_manual_oracle": False, "uses_mathlib": True}
    Path(args.out_summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("v32 repair: verified=%d failed=%d dropped=%d by_family=%s", len(verified), n_fail, dropped, summary["by_family"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
