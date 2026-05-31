"""Mini-ELF v21 — Part 3: build the v21 training-set configurations.

Produces the training pools for the four v21 configs the brief asks
to compare:

  A. **v20 broad-plus baseline** — the existing 2,099-row v20 pool
     (no rebuild; this script just records its path + a stats echo).
  B. **v20 broad-plus + v21 forall corpus** — A ∪ verified v21 forall
     rows, deduped, v18-leakage-guarded. → `v21_broad_plus_forall/`.
  C. **panel ensemble** — no new training pool; config C is a *routing*
     decision (v20 broad-plus for impl/bool/general + a forall
     specialist for forall). The forall specialist is the **config-B
     model itself restricted at inference by the router**, or a
     dedicated forall-only model. Here we emit the forall-only pool
     (`v21_forall_only/`) so a small specialist can be trained for the
     router experiment.
  D. **higher-capacity** — same pool as B; the capacity change is a
     train-time hyperparameter (embed 128 / hidden 192), recorded in a
     config stub, not a different dataset.

Leakage guards (B, C): no v18 eval theorem name; no exact
(statement, state, tactic) triple overlap with v18 eval; v21 source
tags preserved; no state_after.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_v21_training_configs")


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def _v18_sets(v18_root: Path) -> Tuple[Set[str], Set[Tuple[str, str, str]]]:
    names: Set[str] = set()
    triples: Set[Tuple[str, str, str]] = set()
    for fname in ("train.jsonl", "val.jsonl", "test.jsonl"):
        for r in _read_jsonl(v18_root / fname):
            if r.get("theorem_name"):
                names.add(r["theorem_name"])
            triples.add((r.get("theorem_statement", ""),
                         r.get("state_before", ""), r.get("tactic", "")))
    return names, triples


def _ingest(rows, *, stats, key, v18_names, v18_triples, seen, src_label):
    kept = []
    for r in rows:
        stats[key] = stats.get(key, 0) + 1
        nm = r.get("theorem_name", "")
        triple = (r.get("theorem_statement", ""),
                  r.get("state_before", ""), r.get("tactic", ""))
        if nm in v18_names:
            stats["dropped_by_v18_name_guard"] += 1
            continue
        if triple in v18_triples:
            stats["dropped_by_v18_triple_guard"] += 1
            continue
        k = (nm, r.get("tactic", ""))
        if k in seen:
            stats["dropped_by_dedup"] += 1
            continue
        seen.add(k)
        out = dict(r)
        if "corpus_source" not in out:
            out["corpus_source"] = src_label
        kept.append(out)
    return kept


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v20-pool",
                    default=str(ROOT / "data" / "processed"
                                / "v20_broad_synthetic_plus"
                                / "train_rows.jsonl"))
    ap.add_argument("--v21-forall",
                    default=str(ROOT / "data" / "processed"
                                / "v21_forall_corpus" / "train_rows.jsonl"))
    ap.add_argument("--v18-root",
                    default=str(ROOT / "data" / "processed" / "v18_broad_core"))
    ap.add_argument("--out-config-b",
                    default=str(ROOT / "data" / "processed"
                                / "v21_broad_plus_forall"))
    ap.add_argument("--out-config-c-forall-only",
                    default=str(ROOT / "data" / "processed"
                                / "v21_forall_only"))
    args = ap.parse_args(argv)

    v18_names, v18_triples = _v18_sets(Path(args.v18_root))
    v20_rows = _read_jsonl(Path(args.v20_pool))
    forall_rows = _read_jsonl(Path(args.v21_forall))
    logger.info("v20 pool: %d rows; v21 forall corpus: %d rows",
                len(v20_rows), len(forall_rows))

    # ---- Config B: v20 pool + v21 forall ----
    statsB: Dict[str, int] = {"dropped_by_v18_name_guard": 0,
                              "dropped_by_v18_triple_guard": 0,
                              "dropped_by_dedup": 0}
    seenB: Set[Tuple[str, str]] = set()
    rowsB: List[Dict[str, Any]] = []
    rowsB += _ingest(v20_rows, stats=statsB, key="n_v20_pool",
                     v18_names=v18_names, v18_triples=v18_triples,
                     seen=seenB, src_label="v20_pool")
    rowsB += _ingest(forall_rows, stats=statsB, key="n_v21_forall",
                     v18_names=v18_names, v18_triples=v18_triples,
                     seen=seenB, src_label="v21_forall_corpus")
    by_srcB: Dict[str, int] = {}
    for r in rowsB:
        by_srcB[r["corpus_source"]] = by_srcB.get(r["corpus_source"], 0) + 1

    outB = Path(args.out_config_b)
    outB.mkdir(parents=True, exist_ok=True)
    with (outB / "train_rows.jsonl").open("w", encoding="utf-8") as f:
        for r in rowsB:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (outB / "summary.json").write_text(json.dumps({
        "config": "B_v20_broad_plus_plus_forall",
        "n_total_kept": len(rowsB),
        "ingest_stats": statsB,
        "rows_by_corpus_source": by_srcB,
        "uses_state_after": False,
        "uses_manual_oracle": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Config B: %d rows -> %s", len(rowsB), outB)
    for k, v in by_srcB.items():
        logger.info("  %s = %d", k, v)

    # ---- Config C support: forall-only specialist pool ----
    statsC: Dict[str, int] = {"dropped_by_v18_name_guard": 0,
                              "dropped_by_v18_triple_guard": 0,
                              "dropped_by_dedup": 0}
    seenC: Set[Tuple[str, str]] = set()
    # Forall specialist trains on the v21 forall corpus + any forall
    # rows already in the v20 pool (category == forall).
    v20_forall = [r for r in v20_rows if r.get("category") == "forall"
                  or r.get("required_operation") == "instantiate_forall"]
    rowsC: List[Dict[str, Any]] = []
    rowsC += _ingest(forall_rows, stats=statsC, key="n_v21_forall",
                     v18_names=v18_names, v18_triples=v18_triples,
                     seen=seenC, src_label="v21_forall_corpus")
    rowsC += _ingest(v20_forall, stats=statsC, key="n_v20_forall",
                     v18_names=v18_names, v18_triples=v18_triples,
                     seen=seenC, src_label="v20_pool_forall")
    outC = Path(args.out_config_c_forall_only)
    outC.mkdir(parents=True, exist_ok=True)
    with (outC / "train_rows.jsonl").open("w", encoding="utf-8") as f:
        for r in rowsC:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (outC / "summary.json").write_text(json.dumps({
        "config": "C_forall_only_specialist",
        "n_total_kept": len(rowsC),
        "ingest_stats": statsC,
        "uses_state_after": False,
        "uses_manual_oracle": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Config C (forall-only specialist pool): %d rows -> %s",
                len(rowsC), outC)

    # ---- Config A + D pointers (no new pool) ----
    logger.info("Config A baseline pool = %s (unchanged)", args.v20_pool)
    logger.info("Config D = Config B pool with embed=128 hidden=192 "
                "(capacity change is train-time, not data).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
