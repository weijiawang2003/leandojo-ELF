"""Mini-ELF v24 — Part 4: build the broad-plus-residual training set.

Base = the v22 ``A_mixed`` pool (v21 broad-plus + forall + v22 exists,
3,247 rows) — i.e. exactly what the winning v22 ``plus_exists`` generator
trained on. Add the v24 residual shape corpus (verified rows only).
Dedup by (theorem_name, tactic); re-assert no v18 eval leakage; preserve
source tags; report every dropped row. No state_after, no manual oracle.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_v24_training_set")


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _v18_sets():
    names: Set[str] = set()
    triples: Set = set()
    v18 = ROOT / "data" / "processed" / "v18_broad_core"
    for fn in ("train.jsonl", "val.jsonl", "test.jsonl"):
        for r in _read(v18 / fn):
            if r.get("theorem_name"):
                names.add(r["theorem_name"])
            triples.add((r.get("theorem_statement", ""),
                         r.get("state_before", ""), r.get("tactic", "")))
    return names, triples


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base", default=str(ROOT / "data" / "processed"
                                          / "v22_balanced_broad" / "A_mixed" / "train_rows.jsonl"))
    ap.add_argument("--residual", default=str(ROOT / "data" / "processed"
                                              / "v24_residual_shape_corpus" / "train_rows.jsonl"))
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "processed"
                                             / "v24_broad_plus_residual"))
    args = ap.parse_args(argv)

    base = _read(Path(args.base))
    residual = _read(Path(args.residual))
    v18_names, v18_triples = _v18_sets()

    stats = {"n_base": len(base), "n_residual": len(residual),
             "dropped_v18_name": 0, "dropped_v18_triple": 0, "dropped_dedup": 0}
    seen: Set = set()
    pool: List[Dict[str, Any]] = []
    for r in base + residual:
        nm = r.get("theorem_name")
        if nm in v18_names:
            stats["dropped_v18_name"] += 1
            continue
        triple = (r.get("theorem_statement", ""), r.get("state_before", ""),
                  r.get("tactic", ""))
        if triple in v18_triples:
            stats["dropped_v18_triple"] += 1
            continue
        k = (nm, r.get("tactic"))
        if k in seen:
            stats["dropped_dedup"] += 1
            continue
        seen.add(k)
        if "corpus_source" not in r:
            r = {**r, "corpus_source": "v22_base"}
        pool.append(r)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "train_rows.jsonl").open("w", encoding="utf-8") as f:
        for r in pool:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by_src = Counter(r.get("corpus_source", "?") for r in pool)
    by_cat = Counter(r.get("category") or r.get("required_operation") or "?" for r in pool)
    summary = {"config": "v24_broad_plus_residual", "n_total": len(pool),
               "by_corpus_source": dict(by_src), "by_category": dict(by_cat),
               "ingest_stats": stats, "uses_state_after": False,
               "uses_manual_oracle": False}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                          encoding="utf-8")
    logger.info("v24 training set: %d rows (base %d + residual %d); drops name/triple/dedup=%d/%d/%d",
                len(pool), len(base), len(residual), stats["dropped_v18_name"],
                stats["dropped_v18_triple"], stats["dropped_dedup"])
    logger.info("by_corpus_source: %s", dict(by_src))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
