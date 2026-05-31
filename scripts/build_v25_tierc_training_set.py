"""Mini-ELF v25 — Part 5: tiny Mathlib-tier-augmented training set.

Base = the v24 broad-plus-residual pool (3,410 rows) — exactly what the
fixed v24 generator trained on. Add the **verified** v25 Mathlib tier-C
rows, but only from a **theorem-level train split**: the corpus's 36
theorems are stratified by category into train / held-out-test, and only
train-theorem rows enter the training set. The held-out tier-C theorems
are written out so both v24 (zero-shot) and v25 (augmented) are scored on
the *same* unseen set.

Leakage controls:
  * split **by theorem** (no tier-C test theorem appears in train);
  * re-assert no v18 eval leakage (name + (statement,state,tactic) triple);
  * triple-guard against the held-out tier-C test rows too;
  * dedup by (theorem_name, tactic). No state_after, no manual oracle.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_v25_tierc_training_set")


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _v18_sets() -> Tuple[Set[str], Set]:
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


def stratified_split(rows: List[Dict[str, Any]], hold_every: int = 3
                     ) -> Tuple[Set[str], Set[str]]:
    """Deterministic per-category split. Within each category, theorems are
    sorted by name and every ``hold_every``-th one is held out for test."""
    by_cat: Dict[str, List[str]] = defaultdict(list)
    seen: Set[str] = set()
    for r in rows:
        nm, cat = r["theorem_name"], r.get("category", "unknown")
        if nm not in seen:
            seen.add(nm)
            by_cat[cat].append(nm)
    train_t: Set[str] = set()
    test_t: Set[str] = set()
    for cat, names in by_cat.items():
        for i, nm in enumerate(sorted(names)):
            (test_t if i % hold_every == 0 else train_t).add(nm)
    return train_t, test_t


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base", default=str(ROOT / "data" / "processed"
                                          / "v24_broad_plus_residual" / "train_rows.jsonl"))
    ap.add_argument("--tierc", default=str(ROOT / "data" / "processed"
                                           / "v25_mathlib_tierc_corpus" / "train_rows.jsonl"))
    ap.add_argument("--seeds", default=str(ROOT / "data" / "seeds"
                                           / "v25_mathlib_tierc_seeds.jsonl"))
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "processed"
                                             / "v25_tierc_augmented"))
    ap.add_argument("--test-seeds-out", default=str(ROOT / "data" / "seeds"
                                                    / "v25_mathlib_tierc_test_seeds.jsonl"))
    ap.add_argument("--hold-every", type=int, default=3)
    args = ap.parse_args(argv)

    base = _read(Path(args.base))
    tierc = _read(Path(args.tierc))
    all_seeds = _read(Path(args.seeds))
    if not tierc:
        logger.error("no verified tier-C rows at %s — augmentation aborted", args.tierc)
        return 2
    train_t, test_t = stratified_split(tierc, args.hold_every)
    logger.info("tier-C theorem split: %d train / %d test", len(train_t), len(test_t))

    v18_names, v18_triples = _v18_sets()
    # triple-guard against held-out tier-C test rows
    test_triples = {(r.get("theorem_statement", ""), r.get("state_before", ""),
                     r.get("tactic", "")) for r in tierc
                    if r["theorem_name"] in test_t}

    stats = {"n_base": len(base), "n_tierc_total": len(tierc),
             "n_tierc_train_theorems": len(train_t),
             "n_tierc_test_theorems": len(test_t),
             "dropped_v18_name": 0, "dropped_v18_triple": 0,
             "dropped_test_theorem": 0, "dropped_test_triple": 0,
             "dropped_dedup": 0}
    seen: Set = set()
    pool: List[Dict[str, Any]] = []
    n_tierc_train_rows = 0
    for r in base + tierc:
        nm = r.get("theorem_name")
        src_is_tierc = r.get("corpus_source") == "v25_mathlib_tierc"
        if src_is_tierc and nm in test_t:
            stats["dropped_test_theorem"] += 1
            continue
        if nm in v18_names:
            stats["dropped_v18_name"] += 1
            continue
        triple = (r.get("theorem_statement", ""), r.get("state_before", ""),
                  r.get("tactic", ""))
        if triple in v18_triples:
            stats["dropped_v18_triple"] += 1
            continue
        if triple in test_triples:
            stats["dropped_test_triple"] += 1
            continue
        k = (nm, r.get("tactic"))
        if k in seen:
            stats["dropped_dedup"] += 1
            continue
        seen.add(k)
        if "corpus_source" not in r:
            r = {**r, "corpus_source": "v24_base"}
        pool.append(r)
        if src_is_tierc:
            n_tierc_train_rows += 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "train_rows.jsonl").open("w", encoding="utf-8") as f:
        for r in pool:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # held-out test seeds (for both zero-shot and augmented eval)
    test_seeds = [s for s in all_seeds if s["theorem_name"] in test_t]
    with open(args.test_seeds_out, "w", encoding="utf-8") as f:
        for s in test_seeds:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    (out_dir / "test_theorems.json").write_text(
        json.dumps({"test_theorems": sorted(test_t),
                    "train_theorems": sorted(train_t)}, indent=2),
        encoding="utf-8")

    by_src = Counter(r.get("corpus_source", "?") for r in pool)
    summary = {"config": "v25_tierc_augmented", "n_total": len(pool),
               "n_tierc_train_rows_added": n_tierc_train_rows,
               "n_test_seeds": len(test_seeds),
               "by_corpus_source": dict(by_src), "ingest_stats": stats,
               "hold_every": args.hold_every,
               "uses_state_after": False, "uses_manual_oracle": False,
               "split_by_theorem": True}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                          encoding="utf-8")
    logger.info("v25 augmented set: %d rows (base %d + tier-C train %d); "
                "drops v18name/v18triple/testthm/testtriple/dedup=%d/%d/%d/%d/%d",
                len(pool), len(base), n_tierc_train_rows,
                stats["dropped_v18_name"], stats["dropped_v18_triple"],
                stats["dropped_test_theorem"], stats["dropped_test_triple"],
                stats["dropped_dedup"])
    logger.info("by_corpus_source: %s ; held-out test seeds: %d",
                dict(by_src), len(test_seeds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
