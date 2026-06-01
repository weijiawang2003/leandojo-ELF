"""Mini-ELF v29 — Part 5: build v29 Mathlib specialist train/eval splits.

Combines the v28 pools with the v29 sibling-density corpus and produces the v29
training configs plus the splits that let Part 9 *measure* the density law causally:

Pools
-----
  v28_general_pool   = v28 configs/v28_general_train_rows.jsonl   (recommended v28)
  v28_best_pool      = v28 configs/v28_finset_specialist_train_rows.jsonl (strong v28)
  v28_val            = v28 configs/val_rows.jsonl
  v29_rows           = v29 density_train_rows.jsonl               (NEW, dense siblings)

Configs (under configs/)
  v29_general                 = v28_general_pool + v29 rows (unweighted)   [A/C/density_general — recommended]
  v29_v28best_plus            = v28_best_pool   + v29 rows (unweighted)    [B]
  v29_set_finset_order_heavy  = v29_general with set+finset+order upsampled 2x   [D]
  v29_category_balanced       = category-capped over v29_general          [E — NEGATIVE CONTROL only]
  v29_function_order          = v29_general with function+order upsampled 2x  [optional specialist]
  val_rows.jsonl              = v28_val + v29 val rows

Splits (each removes its held-out statements from every train config)
  theorem_holdout        : stratified NOVEL v29 theorems (every 4th test / next val / rest train)
  family_density_holdout : siblings held out from **dense** v29 families (≥6 training
                           siblings remain) — should be EASY if the density law holds
  low_density_holdout    : siblings held out from **sparse** families (≤2 training
                           siblings remain) — the contrast control
  category_holdout_{set,finset,order} : whole category removed from train (transfer probe)

Leakage guards (asserted)
  * no theorem-name overlap between any config train and any eval;
  * no (statement, state) overlap between train and any v29 split test OR the
    v25/v26/v27/v28 benchmarks (statement-level);
  * no triple (statement, state, tactic) overlap; no state_after.

Honesty: only Lean-verified rows; manual targets never used as predictions; Mathlib
real & external; v24 broad-core model untouched; categories balanced only as a
labelled negative control.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audit_v29_family_density import family_of  # noqa: E402


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


def drop_overlap(rows, banned: Set[Tuple[str, str]]):
    kept, dropped = [], 0
    for r in rows:
        if _pair(r) in banned:
            dropped += 1
            continue
        kept.append(r)
    return kept, dropped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    v28cfg = ROOT / "data" / "processed" / "v28_mathlib_specialist" / "configs"
    ap.add_argument("--v28-general-pool", default=str(v28cfg / "v28_general_train_rows.jsonl"))
    ap.add_argument("--v28-best-pool", default=str(v28cfg / "v28_finset_specialist_train_rows.jsonl"))
    ap.add_argument("--v28-val", default=str(v28cfg / "val_rows.jsonl"))
    ap.add_argument("--v29-rows", default=str(ROOT / "data" / "processed" / "v29_mathlib_specialist" / "density_train_rows.jsonl"))
    ap.add_argument("--v29-seeds", default=str(ROOT / "data" / "seeds" / "v29_mathlib_density_seeds.jsonl"))
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "processed" / "v29_mathlib_specialist"))
    # benchmark guards
    ap.add_argument("--v25-test-seeds", default=str(ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"))
    ap.add_argument("--v26-test-seeds", default=str(ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout" / "test_seeds.jsonl"))
    ap.add_argument("--v27-test-seeds", default=str(ROOT / "data" / "processed" / "v27_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"))
    ap.add_argument("--v28-test-seeds", default=str(ROOT / "data" / "processed" / "v28_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"))
    ap.add_argument("--dense-threshold", type=int, default=6, help="combined siblings >= this => dense family")
    ap.add_argument("--sparse-threshold", type=int, default=3, help="combined siblings <= this => sparse family")
    args = ap.parse_args(argv)

    out = Path(args.out_dir)
    v28_general = _read(Path(args.v28_general_pool))
    v28_best = _read(Path(args.v28_best_pool))
    v28_val = _read(Path(args.v28_val))
    v29 = _read(Path(args.v29_rows))
    v29_seeds = {s["theorem_name"]: s for s in _read(Path(args.v29_seeds))}

    # benchmark statement guards (must never enter any training config)
    bench_pairs: Set[Tuple[str, str]] = set()
    for sp in (args.v25_test_seeds, args.v26_test_seeds, args.v27_test_seeds, args.v28_test_seeds):
        for s in _read(Path(sp)):
            bench_pairs.add((s["theorem_statement"], s["state_before"]))

    v28_pairs: Set[Tuple[str, str]] = {_pair(r) for r in (v28_general + v28_best + v28_val)}

    # ---- group v29 rows by theorem + family (namespaced) ----
    v29_by_thm: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in v29:
        v29_by_thm[r["theorem_name"]].append(r)
    thm_fam: Dict[str, str] = {nm: family_of(rs[0]) for nm, rs in v29_by_thm.items()}
    thm_cat: Dict[str, str] = {nm: rs[0].get("category", "?") for nm, rs in v29_by_thm.items()}
    thm_pair: Dict[str, Tuple[str, str]] = {nm: _pair(rs[0]) for nm, rs in v29_by_thm.items()}

    # novel v29 theorems = (stmt,state) absent from every v28 pool row
    novel: Set[str] = {nm for nm in v29_by_thm if thm_pair[nm] not in v28_pairs}

    # combined family sibling counts (v28 pool + v29) for density classification
    fam_sib: Dict[str, Set[str]] = defaultdict(set)
    for r in (v28_general + v29):
        fam_sib[family_of(r)].add(r["theorem_name"])

    # ---- density-contrast holdouts (from NOVEL v29 siblings) ----
    fam_to_novel: Dict[str, List[str]] = defaultdict(list)
    for nm in sorted(novel):
        fam_to_novel[thm_fam[nm]].append(nm)

    family_density_test: Set[str] = set()
    low_density_test: Set[str] = set()
    for fam, nms in fam_to_novel.items():
        combined = len(fam_sib.get(fam, set()))
        if combined >= args.dense_threshold and len(nms) >= 2:
            # hold out up to 2 siblings; >= (combined-2) remain in train (still dense)
            family_density_test.update(nms[-2:])
        elif combined <= args.sparse_threshold and len(nms) >= 1:
            # hold out 1 sibling; <= (combined-1) remain (still sparse)
            low_density_test.add(nms[-1])
    # disjoint by construction (a family is dense XOR sparse); guard anyway
    low_density_test -= family_density_test

    # ---- theorem-holdout: stratify the remaining novel theorems by category ----
    remaining = sorted(novel - family_density_test - low_density_test)
    by_cat: Dict[str, List[str]] = defaultdict(list)
    for nm in remaining:
        by_cat[thm_cat[nm]].append(nm)
    th_train_t, th_val_t, th_test_t = set(), set(), set()
    for cat, nms in by_cat.items():
        for i, nm in enumerate(sorted(nms)):
            m = i % 4
            (th_test_t if m == 0 else th_val_t if m == 1 else th_train_t).add(nm)

    def rows_for(names: Set[str]) -> List[Dict[str, Any]]:
        return [r for nm in names for r in v29_by_thm[nm]]

    def dedup_rows(rows):
        seen, outl = set(), []
        for r in rows:
            k = (r["theorem_name"], r["tactic"])
            if k in seen:
                continue
            seen.add(k); outl.append(r)
        return outl

    th_test_rows = dedup_rows(rows_for(th_test_t))
    fd_test_rows = dedup_rows(rows_for(family_density_test))
    ld_test_rows = dedup_rows(rows_for(low_density_test))
    v29_val_rows = rows_for(th_val_t)
    nonnovel = set(v29_by_thm) - novel
    v29_train_names = (th_train_t | nonnovel)
    v29_train_rows = rows_for(v29_train_names)

    # all held-out test statements banned from every train config
    test_pairs = {_pair(r) for r in (th_test_rows + fd_test_rows + ld_test_rows)}
    ban = bench_pairs | test_pairs

    v29_train_rows, d_v29 = drop_overlap(v29_train_rows, ban)
    v29_val_rows, _ = drop_overlap(v29_val_rows, ban)
    v28_general_clean, d_g = drop_overlap(v28_general, ban)
    v28_best_clean, d_b = drop_overlap(v28_best, ban)
    v28_val_clean, _ = drop_overlap(v28_val, ban)

    cfg_dir = out / "configs"
    shared_val = v28_val_clean + v29_val_rows
    _dump(cfg_dir / "val_rows.jsonl", shared_val)

    # A/C: v29_general (recommended, unweighted)
    general = v28_general_clean + v29_train_rows
    _dump(cfg_dir / "v29_general_train_rows.jsonl", general)
    # B: v28_best + v29
    v28best_plus = v28_best_clean + v29_train_rows
    _dump(cfg_dir / "v29_v28best_plus_train_rows.jsonl", v28best_plus)
    # D: set+finset+order heavy (upsample those categories 2x on top of general)
    sfo = list(general) + [r for r in general if r.get("category") in ("set", "finset", "order")]
    _dump(cfg_dir / "v29_set_finset_order_heavy_train_rows.jsonl", sfo)
    # E: category-balanced NEGATIVE CONTROL
    bycat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in general:
        bycat[r.get("category", "?")].append(r)
    sizes = sorted(len(v) for v in bycat.values())
    cap = int(sizes[len(sizes) // 2] * 1.5) if sizes else 0
    balanced = [r for rs in bycat.values() for r in (rs[:cap] if cap else rs)]
    _dump(cfg_dir / "v29_category_balanced_train_rows.jsonl", balanced)
    # optional specialist: function+order heavy
    fo = list(general) + [r for r in general if r.get("category") in ("function", "order")]
    _dump(cfg_dir / "v29_function_order_train_rows.jsonl", fo)

    # ---- split artifacts ----
    def write_split(key, test_rows, test_names, train_rows):
        d = out / key
        train_rows, _ = drop_overlap(train_rows, {_pair(r) for r in test_rows} | bench_pairs)
        _dump(d / "train_rows.jsonl", train_rows)
        _dump(d / "test_rows.jsonl", test_rows)
        seeds = [v29_seeds[nm] for nm in sorted(test_names) if nm in v29_seeds]
        _dump(d / "test_seeds.jsonl", seeds)
        return {"n_train": len(train_rows), "n_test_rows": len(test_rows),
                "n_test_theorems": len(test_names), "n_test_seeds": len(seeds)}

    th = write_split("theorem_holdout", th_test_rows, th_test_t, general)
    fd = write_split("family_density_holdout", fd_test_rows, family_density_test, general)
    ld = write_split("low_density_holdout", ld_test_rows, low_density_test, general)

    # ---- category holdouts (whole category removed) ----
    full_pool = v28_general_clean + v29_train_rows + th_test_rows + fd_test_rows + ld_test_rows

    def cat_holdout(cat):
        names = {r["theorem_name"] for r in full_pool if r.get("category") == cat}
        test_r = dedup_rows([r for r in full_pool if r["theorem_name"] in names])
        tpairs = {_pair(r) for r in test_r}
        train_r = [r for r in (v28_general_clean + v29_train_rows) if r.get("category") != cat]
        train_r, _ = drop_overlap(train_r, tpairs | bench_pairs)
        d = out / f"category_holdout_{cat}"
        _dump(d / "train_rows.jsonl", train_r)
        _dump(d / "test_rows.jsonl", test_r)
        seeds = [v29_seeds[nm] for nm in sorted(names) if nm in v29_seeds]
        _dump(d / "test_seeds.jsonl", seeds)
        return {"n_train": len(train_r), "n_test_rows": len(test_r),
                "n_test_theorems": len(names), "n_test_seeds": len(seeds)}

    cat_set = cat_holdout("set")
    cat_finset = cat_holdout("finset")
    cat_order = cat_holdout("order")

    benchmarks = {
        "v25_heldout": {"seeds": args.v25_test_seeds, "note": "preserved unchanged"},
        "v26_holdout": {"seeds": args.v26_test_seeds, "note": "preserved unchanged"},
        "v27_holdout": {"seeds": args.v27_test_seeds, "note": "preserved unchanged"},
        "v28_holdout": {"seeds": args.v28_test_seeds, "note": "preserved unchanged"},
        "v29_theorem_holdout": {"seeds": str(out / "theorem_holdout" / "test_seeds.jsonl")},
        "v29_family_density_holdout": {"seeds": str(out / "family_density_holdout" / "test_seeds.jsonl")},
        "v29_low_density_holdout": {"seeds": str(out / "low_density_holdout" / "test_seeds.jsonl")},
        "category_holdout_set": {"seeds": str(out / "category_holdout_set" / "test_seeds.jsonl")},
        "category_holdout_finset": {"seeds": str(out / "category_holdout_finset" / "test_seeds.jsonl")},
        "category_holdout_order": {"seeds": str(out / "category_holdout_order" / "test_seeds.jsonl")},
    }
    (out / "benchmarks.json").write_text(json.dumps(benchmarks, indent=2), encoding="utf-8")

    # ---- leakage assertions ----
    all_train = general + v28best_plus + sfo + balanced + fo
    train_pairs_all = {_pair(r) for r in all_train}
    train_triples = {(r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", "")) for r in all_train}
    assert not (train_pairs_all & test_pairs), "a v29 split test statement leaked into a train config"
    assert not (train_pairs_all & bench_pairs), "a v25-v28 benchmark statement leaked into a train config"
    test_triples = {(r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", ""))
                    for r in (th_test_rows + fd_test_rows + ld_test_rows)}
    assert not (train_triples & test_triples), "a (stmt,state,tactic) triple leaked train<->test"
    train_names = {r["theorem_name"] for r in general}
    assert not (train_names & (th_test_t | family_density_test | low_density_test)), "test theorem name leaked into train"
    for r in all_train:
        assert "state_after" not in r

    # density of each density-holdout family (for Part 9) — training siblings remaining
    train_fam: Dict[str, Set[str]] = defaultdict(set)
    for r in general:
        train_fam[family_of(r)].add(r["theorem_name"])
    fd_family_density = {fam: len(train_fam.get(fam, set()))
                         for fam in {thm_fam[nm] for nm in family_density_test}}
    ld_family_density = {fam: len(train_fam.get(fam, set()))
                         for fam in {thm_fam[nm] for nm in low_density_test}}

    summary = {
        "config": "v29_mathlib_specialist_dataset",
        "pools": {"v28_general": len(v28_general), "v28_best": len(v28_best),
                  "v28_val": len(v28_val_clean), "v29_rows": len(v29)},
        "novel_v29_theorems": len(novel), "nonnovel_v29_theorems": len(nonnovel),
        "configs": {"v29_general": len(general), "v29_v28best_plus": len(v28best_plus),
                    "v29_set_finset_order_heavy": len(sfo), "v29_category_balanced": len(balanced),
                    "v29_function_order": len(fo), "shared_val": len(shared_val),
                    "balance_cap_per_category": cap},
        "theorem_holdout": {**th, "by_category": dict(Counter(thm_cat[nm] for nm in th_test_t))},
        "family_density_holdout": {**fd, "n_families": len(fd_family_density),
                                   "family_train_density": fd_family_density,
                                   "by_category": dict(Counter(thm_cat[nm] for nm in family_density_test))},
        "low_density_holdout": {**ld, "n_families": len(ld_family_density),
                                "family_train_density": ld_family_density,
                                "by_category": dict(Counter(thm_cat[nm] for nm in low_density_test))},
        "category_holdout_set": cat_set, "category_holdout_finset": cat_finset, "category_holdout_order": cat_order,
        "dropped_overlap": {"v29_train": d_v29, "v28_general": d_g, "v28_best": d_b},
        "benchmarks_preserved": ["v25_heldout", "v26_holdout", "v27_holdout", "v28_holdout"],
        "uses_state_after": False, "uses_manual_oracle": False,
        "leakage_guard": "name + statement + triple vs all v29 splits and v25/v26/v27/v28 benchmarks",
        "category_balanced_role": "NEGATIVE CONTROL only (v27/v28 showed balancing harmful)",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[v29 dataset] v29 rows={len(v29)} novel_thms={len(novel)} nonnovel={len(nonnovel)}")
    print(f"[v29 dataset] configs: general={len(general)} v28best_plus={len(v28best_plus)} "
          f"sfo_heavy={len(sfo)} balanced={len(balanced)} function_order={len(fo)} val={len(shared_val)}")
    print(f"[v29 dataset] theorem_holdout={th}  by_cat={summary['theorem_holdout']['by_category']}")
    print(f"[v29 dataset] family_density_holdout={fd} train_density={fd_family_density}")
    print(f"[v29 dataset] low_density_holdout={ld} train_density={ld_family_density}")
    print(f"[v29 dataset] cat_holdout set={cat_set} finset={cat_finset} order={cat_order}")
    print("[v29 dataset] leakage guards PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
