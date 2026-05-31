"""Mini-ELF v22 — Part 2: build balanced multi-category training sets.

The v21 pool is heavily imbalanced by ``required_operation``
(implication 759, instantiate_forall 689, bool_cases 189, … but
destruct_exists 34, exists_elim 5). That imbalance lets the dominant
operations overwrite the minority ones — the category tradeoff v22
investigates.

Produces five training pools (operation = the balancing key, since it
is present on every row; the v20/v21 ``category`` field is absent on
legacy v11/v16/v17 rows):

  A. **mixed** — v21 pool + v22 exists corpus, no rebalancing.
     (`v22_general_base` / `v22_general_plus_exists`)
  B. **oversample** — minority operations up-sampled (with
     deterministic repetition) toward the cap; majority kept.
  C. **undersample** — majority operations down-sampled toward the
     median; minority kept whole.
  D. **loss-weights** — pool A rows + a parallel weights file
     (inverse-sqrt-frequency by operation). Advisory: applied only if
     the trainer supports per-row weights (the current token seq2seq
     does not, so this is emitted for the record / future use).
  E. **mixed (== A)** — explicit ``plus_exists`` alias of A.

Leakage guards: rows already passed v18 name+triple guards when their
source corpora were built; we re-assert no v18 theorem name appears.
No state_after. Source tags preserved. Deterministic (seeded).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set

ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_v22_balanced_training")


def _read(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _opkey(r: Dict[str, Any]) -> str:
    return r.get("required_operation") or r.get("category") or "unknown"


def _v18_names() -> Set[str]:
    names: Set[str] = set()
    v18 = ROOT / "data" / "processed" / "v18_broad_core"
    for fn in ("train.jsonl", "val.jsonl", "test.jsonl"):
        for r in _read(v18 / fn):
            if r.get("theorem_name"):
                names.add(r["theorem_name"])
    return names


def _write(pool: List[Dict[str, Any]], out_dir: Path, label: str,
           extra: Dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "train_rows.jsonl").open("w", encoding="utf-8") as f:
        for r in pool:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by_op = Counter(_opkey(r) for r in pool)
    summary = {"config": label, "n_total": len(pool),
               "by_operation": dict(by_op),
               "uses_state_after": False, "uses_manual_oracle": False}
    summary.update(extra)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("%s: %d rows -> %s", label, len(pool), out_dir)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v21-pool", default=str(ROOT / "data" / "processed"
                                              / "v21_broad_plus_forall"
                                              / "train_rows.jsonl"))
    ap.add_argument("--exists-corpus", default=str(ROOT / "data" / "processed"
                                                   / "v22_exists_corpus"
                                                   / "train_rows.jsonl"))
    ap.add_argument("--out-root", default=str(ROOT / "data" / "processed"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--oversample-cap", type=int, default=400,
                    help="target floor for minority ops in config B")
    args = ap.parse_args(argv)

    v18_names = _v18_names()
    base = _read(Path(args.v21_pool))
    exists_rows = _read(Path(args.exists_corpus))
    # Dedup by (theorem_name, tactic); re-assert no v18 name.
    seen: Set = set()
    mixed: List[Dict[str, Any]] = []
    for r in base + exists_rows:
        if r.get("theorem_name") in v18_names:
            continue
        k = (r.get("theorem_name"), r.get("tactic"))
        if k in seen:
            continue
        seen.add(k)
        mixed.append(r)
    logger.info("mixed pool (A/E): %d rows (base %d + exists %d, deduped)",
                len(mixed), len(base), len(exists_rows))

    by_op: Dict[str, List[Dict[str, Any]]] = {}
    for r in mixed:
        by_op.setdefault(_opkey(r), []).append(r)
    counts = {op: len(rs) for op, rs in by_op.items()}
    logger.info("operation counts: %s", counts)

    import random
    rng = random.Random(args.seed)

    # --- A / E : mixed, no rebalancing ---
    _write(mixed, Path(args.out_root) / "v22_balanced_broad" / "A_mixed",
           "A_mixed", {"note": "v21 pool + v22 exists, no rebalancing"})
    _write(mixed, Path(args.out_root) / "v22_balanced_broad" / "E_plus_exists",
           "E_plus_exists", {"note": "alias of A (plus_exists)"})

    # --- B : oversample minority ops up to the cap ---
    cap = args.oversample_cap
    over: List[Dict[str, Any]] = []
    for op, rs in by_op.items():
        over.extend(rs)
        if len(rs) < cap:
            need = cap - len(rs)
            # deterministic repetition with shuffling
            pad = []
            i = 0
            shuffled = rs[:]
            rng.shuffle(shuffled)
            while len(pad) < need:
                pad.append(dict(shuffled[i % len(shuffled)]))
                i += 1
            over.extend(pad)
    rng.shuffle(over)
    _write(over, Path(args.out_root) / "v22_balanced_broad" / "B_oversample",
           "B_oversample", {"oversample_cap": cap,
                            "by_operation_before": counts})

    # --- C : undersample majority ops down to the median ---
    median = sorted(counts.values())[len(counts) // 2]
    under: List[Dict[str, Any]] = []
    for op, rs in by_op.items():
        if len(rs) > median:
            shuffled = rs[:]
            rng.shuffle(shuffled)
            under.extend(shuffled[:median])
        else:
            under.extend(rs)
    rng.shuffle(under)
    _write(under, Path(args.out_root) / "v22_balanced_broad" / "C_undersample",
           "C_undersample", {"median_cap": median,
                             "by_operation_before": counts})

    # --- D : loss-weights metadata (advisory) ---
    total = len(mixed)
    n_ops = len(counts)
    # inverse-sqrt-frequency, normalised to mean 1.0
    raw = {op: 1.0 / math.sqrt(c) for op, c in counts.items()}
    mean_raw = sum(raw[_opkey(r)] for r in mixed) / total
    weights = []
    for r in mixed:
        w = raw[_opkey(r)] / mean_raw
        weights.append({"theorem_name": r.get("theorem_name"),
                        "tactic": r.get("tactic"),
                        "operation": _opkey(r), "weight": round(w, 4)})
    d_dir = Path(args.out_root) / "v22_balanced_broad" / "D_loss_weighted"
    d_dir.mkdir(parents=True, exist_ok=True)
    # D uses the same rows as A, plus a weights sidecar.
    with (d_dir / "train_rows.jsonl").open("w", encoding="utf-8") as f:
        for r in mixed:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (d_dir / "row_weights.jsonl").open("w", encoding="utf-8") as f:
        for w in weights:
            f.write(json.dumps(w, ensure_ascii=False) + "\n")
    (d_dir / "summary.json").write_text(json.dumps({
        "config": "D_loss_weighted", "n_total": len(mixed),
        "by_operation": counts,
        "weight_scheme": "inverse_sqrt_frequency_normalised_mean1",
        "applied": False,
        "note": "weights sidecar emitted for the record; the current "
                "token seq2seq trainer has no per-row weight hook, so D is "
                "not trained as a separate model in Part 4. Documented "
                "honestly rather than silently skipped.",
        "uses_state_after": False, "uses_manual_oracle": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("D_loss_weighted: %d rows + weights sidecar (advisory) -> %s",
                len(mixed), d_dir)
    logger.info("DONE. configs A/E=%d B=%d C=%d (median=%d) D=%d(advisory)",
                len(mixed), len(over), len(under), median, len(mixed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
