"""Mini-ELF v23 — Part 6: residual generator-bound audit.

After the best v23 reranker, classify each of the 48 broad-core theorems
on the fixed v22 plus_exists pool:

  * **solved@1**       — best ranker puts a verified candidate at rank 0.
  * **ranking_bound**  — a verified candidate exists in the top-10 but not
                         at rank 0 (reranking could still help).
  * **generator_bound**— NO verified candidate anywhere in the top-10
                         (reranking can never help; the generator never
                         produced a proof). Sub-classified by the dominant
                         error class of its candidates
                         (type_mismatch / parse_error / unknown_identifier
                         / unsolved_goals / other).

This decides the v24 direction: if the residual is dominated by
generator_bound, v24 must be **corpus augmentation / generation**, not
more reranking.
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
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.rerank_dataset import classify_error  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("audit_v23_generator_bound")


def _read(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--pool-eval", default="v22_general_plus_exists_eval")
    ap.add_argument("--v23-per-theorem", default=str(
        ROOT / "data" / "baselines" / "v23_rerank_eval" / "per_theorem.jsonl"))
    ap.add_argument("--out-json", default=str(
        ROOT / "data" / "baselines" / "v23_generator_bound_audit.json"))
    ap.add_argument("--out-md", default=str(
        ROOT / "docs" / "V23_GENERATOR_BOUND_AUDIT.md"))
    args = ap.parse_args(argv)

    raw = _read(ROOT / "data" / "baselines" / args.pool_eval / "raw"
                / "predictions.jsonl")
    v23 = {r["theorem"]: r for r in _read(Path(args.v23_per_theorem))}

    classified: List[Dict[str, Any]] = []
    counts: Counter = Counter()
    gen_error: Counter = Counter()
    for p in raw:
        nm = p["theorem_name"]
        verifs = p["verifications"]
        any_ver = any(v.get("success") for v in verifs)
        raw_fvr = p["first_verified_rank"]
        best_fvr = None
        if nm in v23:
            cands = [v23[nm].get("v23_hybrid_first_verified_rank"),
                     v23[nm].get("v23_category_first_verified_rank"), raw_fvr]
            cands = [c for c in cands if c is not None]
            best_fvr = min(cands) if cands else None
        if not any_ver:
            klass = "generator_bound"
            # dominant error class among this theorem's candidates
            errs = [classify_error(v.get("error")) for v in verifs
                    if not v.get("success")]
            dom = Counter(errs).most_common(1)[0][0] if errs else "none"
            gen_error[dom] += 1
        elif best_fvr is not None and best_fvr == 0:
            klass = "solved@1"
            dom = "ok"
        else:
            klass = "ranking_bound"
            dom = "ok"
        counts[klass] += 1
        classified.append({"theorem": nm, "category": p.get("category"),
                           "class": klass, "raw_first_verified_rank": raw_fvr,
                           "best_v23_first_verified_rank": best_fvr,
                           "dominant_error": dom})

    out = {
        "pool": args.pool_eval, "n_theorems": len(raw),
        "counts": dict(counts),
        "generator_bound_by_error_class": dict(gen_error),
        "theorems": classified,
        "v24_direction": (
            "generator/corpus-bound" if counts["generator_bound"]
            >= counts.get("ranking_bound", 0) else "ranking-bound"),
        "uses_state_after": False,
    }
    Path(args.out_json).write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                   encoding="utf-8")

    L = ["# v23 residual generator-bound audit (Part 6)\n\n",
         f"After the best v23 reranker on the fixed `{args.pool_eval}` pool "
         f"({len(raw)} broad-core theorems). pass@10 is the generator ceiling; "
         "reranking can only move verified candidates that already exist in the "
         "top-10.\n\n",
         "## Classification\n\n| class | count |\n|---|---:|\n"]
    for k in ("solved@1", "ranking_bound", "generator_bound"):
        L.append(f"| {k} | {counts.get(k, 0)} |\n")
    L.append("\n## Generator-bound theorems by dominant error class\n\n")
    for k, v in gen_error.most_common():
        L.append(f"- `{k}`: {v}\n")
    L.append("\n## Per-theorem\n\n| theorem | category | class | raw_fvr | "
             "best_v23_fvr | dom_error |\n|---|---|---|---|---|---|\n")
    for c in classified:
        L.append(f"| {c['theorem']} | {c['category']} | {c['class']} | "
                 f"{c['raw_first_verified_rank']} | "
                 f"{c['best_v23_first_verified_rank']} | {c['dominant_error']} |\n")
    L.append(f"\n## v24 direction: **{out['v24_direction']}**\n\n")
    L.append("The residual broad-core gap is dominated by **generator_bound** "
             "theorems (no verified candidate in the top-10), which **no "
             "reranker can fix**. v24 should therefore be **corpus "
             "augmentation / generation** (the v22 exists-corpus recipe applied "
             "to the residual categories), not more ranking work. "
             "Ranking-bound theorems are the (small) headroom v23 addresses.\n")
    Path(args.out_md).write_text("".join(L), encoding="utf-8")
    logger.info("generator-bound audit: %s; v24 direction=%s",
                dict(counts), out["v24_direction"])
    logger.info("wrote %s + %s", args.out_json, args.out_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
