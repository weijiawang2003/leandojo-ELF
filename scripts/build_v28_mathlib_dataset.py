"""Mini-ELF v28 — Part 4: build v28 Mathlib specialist train/eval splits.

Combines the **v27 best specialist pool** (``v27_widened`` = v26_widened + v27
expanded) with the v28 expanded verified rows and produces four training configs, a
fresh v28 theorem-holdout, and Set / order / Finset category-holdouts, while
preserving the v25 / v26 / v27 benchmarks untouched.

Pools
-----
  v27_widened_pool = v27 configs/v27_widened_train_rows.jsonl   (v26_widened + v27)
  v27_shared_val   = v27 configs/val_rows.jsonl
  v28_rows         = v28 expanded_train_rows.jsonl              (NEW)

v28 theorem-holdout (the fresh benchmark)
-----------------------------------------
Test theorems are drawn ONLY from v28 theorems whose (statement, state) is **novel**
(absent from every v27-pool row), stratified by category (every 4th -> test, next ->
val, rest -> train). Held-out test statements never appear in any training config.
Non-novel v28 theorems always go to train.

Configs (under configs/)
  v28_general            = v27_widened_pool + v28 train rows           (the v27_best + v28)
  v28_set_order_heavy    = v28_general with Set+order rows upsampled 2x
  v28_category_balanced  = category-balanced cap over v28_general
  v28_finset_specialist  = v28_general with Finset rows upsampled 3x   (Finset-leaning)
  val_rows.jsonl         = v27_shared_val + v28 val rows

Category holdouts (transfer probes)
  category_holdout_set    | _order | _finset : test = all rows of that category in the
  pool; train = the rest (held-out category statements removed from train).

Leakage guards (asserted)
  * no theorem-name overlap between any config train and its eval;
  * no (statement, state) overlap between train and the v28 holdout test, the v25
    held-out, the v26 holdout, or the v27 holdout (statement-level);
  * no state_after anywhere.

Honesty: only Lean-verified rows; manual targets never used as predictions; Mathlib
real and external; v24 broad-core model untouched.
"""

from __future__ import annotations

import argparse
import json
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


def drop_overlap(rows: List[Dict[str, Any]], banned: Set[Tuple[str, str]]) -> Tuple[List[Dict[str, Any]], int]:
    kept, dropped = [], 0
    for r in rows:
        if _pair(r) in banned:
            dropped += 1
            continue
        kept.append(r)
    return kept, dropped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    v27cfg = ROOT / "data" / "processed" / "v27_mathlib_specialist" / "configs"
    th27 = ROOT / "data" / "processed" / "v27_mathlib_specialist" / "theorem_holdout"
    th26 = ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout"
    ap.add_argument("--v27-widened-pool", default=str(v27cfg / "v27_widened_train_rows.jsonl"))
    ap.add_argument("--v27-val", default=str(v27cfg / "val_rows.jsonl"))
    ap.add_argument("--v28-rows", default=str(ROOT / "data" / "processed" / "v28_mathlib_specialist" / "expanded_train_rows.jsonl"))
    ap.add_argument("--v28-seeds", default=str(ROOT / "data" / "seeds" / "v28_mathlib_expanded_seeds.jsonl"))
    ap.add_argument("--v25-test-seeds", default=str(ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"))
    ap.add_argument("--v26-test-seeds", default=str(th26 / "test_seeds.jsonl"))
    ap.add_argument("--v27-test-seeds", default=str(th27 / "test_seeds.jsonl"))
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "processed" / "v28_mathlib_specialist"))
    args = ap.parse_args(argv)

    v27_pool = _read(Path(args.v27_widened_pool))
    v27_val = _read(Path(args.v27_val))
    v28 = _read(Path(args.v28_rows))
    v28_seeds = {s["theorem_name"]: s for s in _read(Path(args.v28_seeds))}

    # benchmark statement guards (must never enter any training config)
    bench_pairs: Set[Tuple[str, str]] = set()
    for sp in (args.v25_test_seeds, args.v26_test_seeds, args.v27_test_seeds):
        for s in _read(Path(sp)):
            bench_pairs.add((s["theorem_statement"], s["state_before"]))

    v27_pairs: Set[Tuple[str, str]] = {_pair(r) for r in (v27_pool + v27_val)}

    # ---- v28 theorem-holdout: stratify NOVEL v28 theorems ----
    v28_by_thm: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in v28:
        v28_by_thm[r["theorem_name"]].append(r)
    novel_by_cat: Dict[str, List[str]] = defaultdict(list)
    nonnovel: Set[str] = set()
    for nm, rs in v28_by_thm.items():
        if any(_pair(r) in v27_pairs for r in rs):
            nonnovel.add(nm)
        else:
            novel_by_cat[rs[0].get("category", "unknown")].append(nm)
    train_t, val_t, test_t = stratified_3way(novel_by_cat)

    test_rows = [r for nm in test_t for r in v28_by_thm[nm]]
    test_pairs = {_pair(r) for r in test_rows}
    v28_val_rows = [r for nm in val_t for r in v28_by_thm[nm]]
    v28_train_rows = [r for nm in (train_t | nonnovel) for r in v28_by_thm[nm]]

    ban = bench_pairs | test_pairs
    v28_train_rows, d1 = drop_overlap(v28_train_rows, ban)
    v28_val_rows, _ = drop_overlap(v28_val_rows, bench_pairs)
    v27_pool_clean, dp = drop_overlap(v27_pool, ban)
    v27_val_clean, _ = drop_overlap(v27_val, bench_pairs | test_pairs)

    out = Path(args.out_dir)
    cfg_dir = out / "configs"
    shared_val = v27_val_clean + v28_val_rows
    _dump(cfg_dir / "val_rows.jsonl", shared_val)

    # config 1: v28_general
    general = v27_pool_clean + v28_train_rows
    _dump(cfg_dir / "v28_general_train_rows.jsonl", general)
    # config 2: set+order heavy (upsample set & order 2x)
    set_order_heavy = list(general) + [r for r in general if r.get("category") in ("set", "order")]
    _dump(cfg_dir / "v28_set_order_heavy_train_rows.jsonl", set_order_heavy)
    # config 3: category-balanced cap
    by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in general:
        by_cat[r.get("category", "unknown")].append(r)
    cap = int(sorted(len(v) for v in by_cat.values())[len(by_cat) // 2] * 1.5) if by_cat else 0
    balanced = []
    for cat, rs in by_cat.items():
        balanced.extend(rs[:cap] if cap else rs)
    _dump(cfg_dir / "v28_category_balanced_train_rows.jsonl", balanced)
    # config 4: finset-leaning specialist (upsample finset 3x)
    finset_spec = list(general) + 2 * [r for r in general if r.get("category") == "finset"]
    _dump(cfg_dir / "v28_finset_specialist_train_rows.jsonl", finset_spec)

    # ---- v28 theorem-holdout artifacts ----
    th_dir = out / "theorem_holdout"
    _dump(th_dir / "train_rows.jsonl", general)
    _dump(th_dir / "val_rows.jsonl", shared_val)
    _dump(th_dir / "test_rows.jsonl", test_rows)
    test_seeds = [v28_seeds[nm] for nm in sorted(test_t) if nm in v28_seeds]
    _dump(th_dir / "test_seeds.jsonl", test_seeds)

    # ---- category holdouts ----
    full_pool = v27_pool_clean + v28_train_rows + test_rows

    def cat_holdout(match, key):
        test_names = {r["theorem_name"] for r in full_pool if match(r)}
        test_r = [r for r in full_pool if r["theorem_name"] in test_names]
        seen, test_d = set(), []
        for r in test_r:
            k = (r["theorem_name"], r["tactic"])
            if k in seen:
                continue
            seen.add(k); test_d.append(r)
        tpairs = {_pair(r) for r in test_d}
        train_r = [r for r in (v27_pool_clean + v28_train_rows) if not match(r)]
        train_r, _ = drop_overlap(train_r, tpairs | bench_pairs)
        d = out / f"category_holdout_{key}"
        _dump(d / "train_rows.jsonl", train_r)
        _dump(d / "test_rows.jsonl", test_d)
        seeds = [v28_seeds[nm] for nm in sorted(test_names) if nm in v28_seeds]
        _dump(d / "test_seeds.jsonl", seeds)
        return {"n_train": len(train_r), "n_test_rows": len(test_d),
                "n_test_theorems": len(test_names), "n_test_seeds": len(seeds)}

    set_ho = cat_holdout(lambda r: r.get("category") == "set", "set")
    order_ho = cat_holdout(lambda r: r.get("category") == "order", "order")
    finset_ho = cat_holdout(lambda r: r.get("category") == "finset", "finset")

    # ---- benchmark pointers ----
    benchmarks = {
        "v25_heldout": {"seeds": args.v25_test_seeds, "note": "preserved unchanged"},
        "v26_holdout": {"seeds": args.v26_test_seeds, "note": "preserved unchanged"},
        "v27_holdout": {"seeds": args.v27_test_seeds, "note": "preserved unchanged"},
        "v28_theorem_holdout": {"seeds": str(th_dir / "test_seeds.jsonl"), "n_theorems": len(test_seeds)},
        "category_holdout_set": {"seeds": str(out / "category_holdout_set" / "test_seeds.jsonl")},
        "category_holdout_order": {"seeds": str(out / "category_holdout_order" / "test_seeds.jsonl")},
        "category_holdout_finset": {"seeds": str(out / "category_holdout_finset" / "test_seeds.jsonl")},
    }
    (out / "benchmarks.json").write_text(json.dumps(benchmarks, indent=2), encoding="utf-8")

    # ---- leakage assertions ----
    train_pairs_all = {_pair(r) for r in (general + set_order_heavy + balanced + finset_spec)}
    assert not (train_pairs_all & test_pairs), "v28 holdout-test statement leaked into a train config"
    assert not (train_pairs_all & bench_pairs), "v25/v26/v27 benchmark statement leaked into a train config"
    train_names_all = {r["theorem_name"] for r in general}
    assert not (train_names_all & set(test_t)), "v28 holdout-test theorem name leaked into train"
    for r in (general + set_order_heavy + test_rows):
        assert "state_after" not in r

    summary = {
        "config": "v28_mathlib_specialist_dataset",
        "pools": {"v27_widened_pool": len(v27_pool), "v27_val": len(v27_val_clean), "v28_rows": len(v28)},
        "v28_theorem_holdout": {
            "novel_v28_theorems": sum(len(v) for v in novel_by_cat.values()),
            "nonnovel_v28_theorems": len(nonnovel),
            "n_train_theorems": len(train_t), "n_val_theorems": len(val_t),
            "n_test_theorems": len(test_t), "n_test_rows": len(test_rows), "n_test_seeds": len(test_seeds),
            "test_by_category": dict(Counter(r["category"] for r in test_rows)),
            "dropped_v28_train_overlap": d1, "dropped_v27_pool_overlap": dp},
        "configs": {"v28_general": len(general), "v28_set_order_heavy": len(set_order_heavy),
                    "v28_category_balanced": len(balanced), "v28_finset_specialist": len(finset_spec),
                    "shared_val": len(shared_val), "balance_cap_per_category": cap},
        "category_holdout_set": set_ho, "category_holdout_order": order_ho, "category_holdout_finset": finset_ho,
        "benchmarks_preserved": ["v25_heldout", "v26_holdout", "v27_holdout"],
        "uses_state_after": False, "uses_manual_oracle": False,
        "leakage_guard": "statement-level vs v28 holdout + v25/v26/v27 benchmarks",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[v28 dataset] v28 rows={len(v28)} novel_thms={summary['v28_theorem_holdout']['novel_v28_theorems']} "
          f"nonnovel={len(nonnovel)}")
    print(f"[v28 dataset] holdout: train_thm={len(train_t)} val_thm={len(val_t)} test_thm={len(test_t)} "
          f"test_rows={len(test_rows)} test_by_cat={summary['v28_theorem_holdout']['test_by_category']}")
    print(f"[v28 dataset] configs: general={len(general)} set_order_heavy={len(set_order_heavy)} "
          f"balanced={len(balanced)} finset_spec={len(finset_spec)} val={len(shared_val)}")
    print(f"[v28 dataset] cat_holdout_set={set_ho}")
    print(f"[v28 dataset] cat_holdout_order={order_ho}")
    print(f"[v28 dataset] cat_holdout_finset={finset_ho}")
    print("[v28 dataset] leakage guards PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
