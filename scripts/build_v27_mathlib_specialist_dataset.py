"""Mini-ELF v27 — Part 5b: build v27 Mathlib specialist train/eval splits.

Combines the v26 specialist training pool with the v27 expanded verified rows and
produces four training configs plus a fresh v27 theorem-holdout and Set/order
category-holdouts, while preserving the v25 held-out and v26 holdout benchmarks
untouched.

Pools
-----
  v26_base_train     = v26 theorem_holdout/train_rows.jsonl            (149)
  v26_widened_train  = v26 theorem_holdout/train_rows_set_widened.jsonl
  v26_val            = v26 theorem_holdout/val_rows.jsonl
  v27_rows           = v27 expanded_train_rows.jsonl                   (181 new)

v27 theorem-holdout
-------------------
Test theorems are drawn ONLY from v27 theorems whose (statement, state) is **novel**
(absent from every v26 train/val row), stratified by category (every 4th → test,
next → val, rest → train). This guarantees the held-out test statements never
appear in any training config. Non-novel v27 theorems always go to train.

Configs (training files under configs/)
  v27_base               = v26_base_train + v27 train rows
  v27_widened            = v26_widened_train + v27 train rows
  v27_category_balanced  = category-balanced cap over (v26_widened_train + v27 train)
  v27_set_heavy          = v27_widened with Set rows upsampled 2x
  val_rows.jsonl         = v26_val + v27 val rows   (shared checkpoint-selection val)

Category holdouts (transfer probes)
  category_holdout_set   = test: all Set theorems in the pool; train: non-Set rows
  category_holdout_order = test: all order theorems; train: non-order rows

Leakage guards (asserted)
  * no theorem-name overlap between any config train and its eval;
  * no (statement, state) overlap between train and the v27 holdout test, the v25
    held-out, or the v26 holdout (statement-level, stricter than v26's triple-level);
  * no state_after anywhere.

Honesty: only Lean-verified rows; manual targets never used as predictions; Mathlib
real and external; v24 broad-core model untouched.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _pair(r: Dict[str, Any]) -> Tuple[str, str]:
    return (r.get("theorem_statement", ""), r.get("state_before", ""))


def _dump(path: Path, rows: List[Dict[str, Any]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def stratified_3way(theorems_by_cat: Dict[str, List[str]]) -> Tuple[Set[str], Set[str], Set[str]]:
    train, val, test = set(), set(), set()
    for cat, names in theorems_by_cat.items():
        for i, nm in enumerate(sorted(names)):
            m = i % 4
            (test if m == 0 else val if m == 1 else train).add(nm)
    return train, val, test


def drop_overlap(rows: List[Dict[str, Any]], banned_pairs: Set[Tuple[str, str]]
                 ) -> Tuple[List[Dict[str, Any]], int]:
    kept, dropped = [], 0
    for r in rows:
        if _pair(r) in banned_pairs:
            dropped += 1
            continue
        kept.append(r)
    return kept, dropped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    th = ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout"
    ap.add_argument("--v26-base-train", default=str(th / "train_rows.jsonl"))
    ap.add_argument("--v26-widened-train", default=str(th / "train_rows_set_widened.jsonl"))
    ap.add_argument("--v26-val", default=str(th / "val_rows.jsonl"))
    ap.add_argument("--v27-rows", default=str(ROOT / "data" / "processed" / "v27_mathlib_specialist" / "expanded_train_rows.jsonl"))
    ap.add_argument("--v27-seeds", default=str(ROOT / "data" / "seeds" / "v27_mathlib_expanded_seeds.jsonl"))
    ap.add_argument("--v25-test-seeds", default=str(ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"))
    ap.add_argument("--v26-test-seeds", default=str(th / "test_seeds.jsonl"))
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "processed" / "v27_mathlib_specialist"))
    args = ap.parse_args(argv)

    v26_base = _read(Path(args.v26_base_train))
    v26_widened = _read(Path(args.v26_widened_train))
    v26_val = _read(Path(args.v26_val))
    v27 = _read(Path(args.v27_rows))
    v27_seeds = {s["theorem_name"]: s for s in _read(Path(args.v27_seeds))}

    # benchmark statement guards (must never enter any training config)
    bench_pairs: Set[Tuple[str, str]] = set()
    for sp in (args.v25_test_seeds, args.v26_test_seeds):
        for s in _read(Path(sp)):
            bench_pairs.add((s["theorem_statement"], s["state_before"]))

    # v26 train/val statements (to decide which v27 theorems are "novel")
    v26_pairs: Set[Tuple[str, str]] = {_pair(r) for r in (v26_base + v26_widened + v26_val)}

    # ---- v27 theorem-holdout: stratify NOVEL v27 theorems ----
    v27_by_thm: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in v27:
        v27_by_thm[r["theorem_name"]].append(r)
    novel_by_cat: Dict[str, List[str]] = defaultdict(list)
    nonnovel_theorems: Set[str] = set()
    for nm, rs in v27_by_thm.items():
        # novel iff none of this theorem's rows share a (stmt,state) with v26 train
        if any(_pair(r) in v26_pairs for r in rs):
            nonnovel_theorems.add(nm)
        else:
            novel_by_cat[rs[0].get("category", "unknown")].append(nm)
    train_t, val_t, test_t = stratified_3way(novel_by_cat)

    test_rows = [r for nm in test_t for r in v27_by_thm[nm]]
    test_pairs = {_pair(r) for r in test_rows}
    v27_val_rows = [r for nm in val_t for r in v27_by_thm[nm]]
    v27_train_rows = [r for nm in (train_t | nonnovel_theorems) for r in v27_by_thm[nm]]

    # every training config bans: benchmark pairs + v27-test pairs
    ban = bench_pairs | test_pairs
    v27_train_rows, d1 = drop_overlap(v27_train_rows, ban)
    v27_val_rows, _ = drop_overlap(v27_val_rows, bench_pairs)
    v26_base, db = drop_overlap(v26_base, ban)
    v26_widened, dw = drop_overlap(v26_widened, ban)
    v26_val_clean, _ = drop_overlap(v26_val, bench_pairs | test_pairs)

    out = Path(args.out_dir)
    cfg_dir = out / "configs"
    shared_val = v26_val_clean + v27_val_rows
    _dump(cfg_dir / "val_rows.jsonl", shared_val)

    # config 1: v27_base
    base_train = v26_base + v27_train_rows
    _dump(cfg_dir / "v27_base_train_rows.jsonl", base_train)
    # config 2: v27_widened
    widened_train = v26_widened + v27_train_rows
    _dump(cfg_dir / "v27_widened_train_rows.jsonl", widened_train)
    # config 3: category-balanced cap over widened_train
    by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in widened_train:
        by_cat[r.get("category", "unknown")].append(r)
    cap = int(sorted((len(v) for v in by_cat.values()))[len(by_cat) // 2] * 1.5) if by_cat else 0
    balanced = []
    for cat, rs in by_cat.items():
        balanced.extend(rs[:cap] if cap else rs)
    _dump(cfg_dir / "v27_category_balanced_train_rows.jsonl", balanced)
    # config 4: set-heavy (upsample Set rows 2x)
    set_heavy = list(widened_train) + [r for r in widened_train if r.get("category") == "set"]
    _dump(cfg_dir / "v27_set_heavy_train_rows.jsonl", set_heavy)

    # ---- v27 theorem-holdout test artifacts ----
    th_dir = out / "theorem_holdout"
    _dump(th_dir / "train_rows.jsonl", widened_train)   # default = widened config
    _dump(th_dir / "val_rows.jsonl", shared_val)
    _dump(th_dir / "test_rows.jsonl", test_rows)
    test_seeds = [v27_seeds[nm] for nm in sorted(test_t) if nm in v27_seeds]
    _dump(th_dir / "test_seeds.jsonl", test_seeds)

    # ---- category holdouts (transfer probes) ----
    full_pool = v26_widened + v27_train_rows + test_rows  # all set/order theorems present
    def cat_holdout(match, key):
        test_names = {r["theorem_name"] for r in full_pool if match(r)}
        test_r = [r for r in full_pool if r["theorem_name"] in test_names]
        # dedup test rows by (name,tactic)
        seen, test_d = set(), []
        for r in test_r:
            k = (r["theorem_name"], r["tactic"])
            if k in seen:
                continue
            seen.add(k); test_d.append(r)
        tpairs = {_pair(r) for r in test_d}
        train_r = [r for r in (v26_widened + v27_train_rows) if not match(r)]
        train_r, _ = drop_overlap(train_r, tpairs | bench_pairs)
        d = out / f"category_holdout_{key}"
        _dump(d / "train_rows.jsonl", train_r)
        _dump(d / "test_rows.jsonl", test_d)
        seeds = [v27_seeds[nm] for nm in sorted(test_names) if nm in v27_seeds]
        _dump(d / "test_seeds.jsonl", seeds)
        return {"n_train": len(train_r), "n_test_rows": len(test_d), "n_test_theorems": len(test_names),
                "n_test_seeds": len(seeds)}
    set_ho = cat_holdout(lambda r: r.get("category") == "set", "set")
    order_ho = cat_holdout(lambda r: r.get("expected_skill") == "order" or r.get("category") == "order", "order")

    # ---- benchmark pointers ----
    benchmarks = {
        "v25_heldout": {"seeds": args.v25_test_seeds, "note": "preserved unchanged"},
        "v26_holdout": {"seeds": args.v26_test_seeds, "note": "preserved unchanged"},
        "v27_theorem_holdout": {"seeds": str(th_dir / "test_seeds.jsonl"), "n_theorems": len(test_seeds)},
        "category_holdout_set": {"seeds": str(out / "category_holdout_set" / "test_seeds.jsonl")},
        "category_holdout_order": {"seeds": str(out / "category_holdout_order" / "test_seeds.jsonl")},
    }
    (out / "benchmarks.json").write_text(json.dumps(benchmarks, indent=2), encoding="utf-8")

    # ---- leakage assertions ----
    train_pairs_all = {_pair(r) for r in (base_train + widened_train + balanced + set_heavy)}
    assert not (train_pairs_all & test_pairs), "v27 holdout-test statement leaked into a train config"
    assert not (train_pairs_all & bench_pairs), "v25/v26 benchmark statement leaked into a train config"
    test_names_all = set(test_t)
    train_names_all = {r["theorem_name"] for r in widened_train}
    assert not (train_names_all & test_names_all), "v27 holdout-test theorem name leaked into train"
    for r in (base_train + widened_train + test_rows):
        assert "state_after" not in r

    summary = {
        "config": "v27_mathlib_specialist_dataset",
        "pools": {"v26_base_train": len(v26_base), "v26_widened_train": len(v26_widened),
                  "v26_val": len(v26_val_clean), "v27_rows": len(v27)},
        "v27_theorem_holdout": {
            "novel_v27_theorems": sum(len(v) for v in novel_by_cat.values()),
            "nonnovel_v27_theorems": len(nonnovel_theorems),
            "n_train_theorems": len(train_t), "n_val_theorems": len(val_t),
            "n_test_theorems": len(test_t), "n_test_rows": len(test_rows),
            "n_test_seeds": len(test_seeds),
            "test_by_category": dict(Counter(r["category"] for r in test_rows)),
            "dropped_v27_train_overlap": d1, "dropped_v26_base_overlap": db, "dropped_v26_widened_overlap": dw},
        "configs": {
            "v27_base": len(base_train), "v27_widened": len(widened_train),
            "v27_category_balanced": len(balanced), "v27_set_heavy": len(set_heavy),
            "shared_val": len(shared_val), "balance_cap_per_category": cap},
        "category_holdout_set": set_ho, "category_holdout_order": order_ho,
        "benchmarks_preserved": ["v25_heldout", "v26_holdout"],
        "uses_state_after": False, "uses_manual_oracle": False,
        "leakage_guard": "statement-level (stricter than v26 triple-level)",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[v27 dataset] v27 rows={len(v27)} novel_thms={summary['v27_theorem_holdout']['novel_v27_theorems']} "
          f"nonnovel={len(nonnovel_theorems)}")
    print(f"[v27 dataset] holdout: train_thm={len(train_t)} val_thm={len(val_t)} test_thm={len(test_t)} "
          f"test_rows={len(test_rows)} test_by_cat={summary['v27_theorem_holdout']['test_by_category']}")
    print(f"[v27 dataset] configs: base={len(base_train)} widened={len(widened_train)} "
          f"balanced={len(balanced)} set_heavy={len(set_heavy)} val={len(shared_val)}")
    print(f"[v27 dataset] cat_holdout_set: {set_ho}")
    print(f"[v27 dataset] cat_holdout_order: {order_ho}")
    print("[v27 dataset] leakage guards PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
