"""Mini-ELF v30 — Part 5: build v30 Mathlib specialist train/eval splits.

Combines the v29 pools with the v30 targeted density-repair corpus. Because v30 is a
*repair* (not new benchmarks), the headline eval runs on the preserved v25–v29
benchmarks; v30 adds a small fresh holdout + a targeted-family holdout to check the
density repair generalises.

Pools
  v29_general_pool = v29 configs/v29_general_train_rows.jsonl
  v29_best_pool    = v29 configs/v29_set_finset_order_heavy_train_rows.jsonl
  v29_val          = v29 configs/val_rows.jsonl
  v30_rows         = v30 targeted_train_rows.jsonl                 (NEW, repair)

Configs (configs/)
  v30_general_targeted   = v29_general_pool + v30 rows (unweighted)         [A — recommended]
  v30_v29best_plus       = v29_best_pool    + v30 rows                      [B]
  v30_targeted_only      = v30 rows only                                    [C — ablation]
  v30_targeted_upsample  = general_targeted + v30 rows again (2× repair)    [D — NOT balanced]

Splits
  theorem_holdout         : stratified NOVEL v30 theorems (fresh holdout)
  targeted_family_holdout : one sibling held out per repaired family (density-repair probe)
  (preserved v25/v26/v27/v28/v29 + v29 family/low-density holdouts — pointers only)

Leakage guards (asserted): no name/statement/triple overlap train↔any v30 split, no
v25–v29 benchmark statement in train, no state_after.
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


def _pair(r):
    return (r.get("theorem_statement", ""), r.get("state_before", ""))


def _dump(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def drop_overlap(rows, banned):
    kept, n = [], 0
    for r in rows:
        if _pair(r) in banned:
            n += 1; continue
        kept.append(r)
    return kept, n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    v29cfg = ROOT / "data" / "processed" / "v29_mathlib_specialist" / "configs"
    ap.add_argument("--v29-general-pool", default=str(v29cfg / "v29_general_train_rows.jsonl"))
    ap.add_argument("--v29-best-pool", default=str(v29cfg / "v29_set_finset_order_heavy_train_rows.jsonl"))
    ap.add_argument("--v29-val", default=str(v29cfg / "val_rows.jsonl"))
    ap.add_argument("--v30-rows", default=str(ROOT / "data" / "processed" / "v30_mathlib_specialist" / "targeted_train_rows.jsonl"))
    ap.add_argument("--v30-seeds", default=str(ROOT / "data" / "seeds" / "v30_targeted_density_seeds.jsonl"))
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "processed" / "v30_mathlib_specialist"))
    P = ROOT / "data" / "processed"
    ap.add_argument("--bench-seeds", nargs="*", default=[
        str(ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"),
        str(P / "v26_mathlib_specialist_splits" / "theorem_holdout" / "test_seeds.jsonl"),
        str(P / "v27_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"),
        str(P / "v28_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"),
        str(P / "v29_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"),
        str(P / "v29_mathlib_specialist" / "family_density_holdout" / "test_seeds.jsonl"),
        str(P / "v29_mathlib_specialist" / "low_density_holdout" / "test_seeds.jsonl"),
    ])
    args = ap.parse_args(argv)

    out = Path(args.out_dir)
    v29_general = _read(Path(args.v29_general_pool))
    v29_best = _read(Path(args.v29_best_pool))
    v29_val = _read(Path(args.v29_val))
    v30 = _read(Path(args.v30_rows))
    v30_seeds = {s["theorem_name"]: s for s in _read(Path(args.v30_seeds))}

    bench_pairs: Set[Tuple[str, str]] = set()
    for sp in args.bench_seeds:
        for s in _read(Path(sp)):
            bench_pairs.add((s["theorem_statement"], s["state_before"]))
    v29_pairs = {_pair(r) for r in (v29_general + v29_best + v29_val)}

    v30_by_thm: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in v30:
        v30_by_thm[r["theorem_name"]].append(r)
    thm_fam = {nm: family_of(rs[0]) for nm, rs in v30_by_thm.items()}
    thm_cat = {nm: rs[0].get("category", "?") for nm, rs in v30_by_thm.items()}
    novel = {nm for nm in v30_by_thm if _pair(v30_by_thm[nm][0]) not in v29_pairs}

    # targeted-family holdout: one (last) novel sibling per repaired family
    fam_to_novel: Dict[str, List[str]] = defaultdict(list)
    for nm in sorted(novel):
        fam_to_novel[thm_fam[nm]].append(nm)
    tf_test: Set[str] = set()
    for fam, nms in fam_to_novel.items():
        if len(nms) >= 3:        # keep >=2 siblings in train (still a repair)
            tf_test.add(nms[-1])

    # fresh theorem holdout: stratify the remaining novel theorems
    remaining = sorted(novel - tf_test)
    by_cat: Dict[str, List[str]] = defaultdict(list)
    for nm in remaining:
        by_cat[thm_cat[nm]].append(nm)
    th_test, th_val, th_train = set(), set(), set()
    for cat, nms in by_cat.items():
        for i, nm in enumerate(sorted(nms)):
            m = i % 4
            (th_test if m == 0 else th_val if m == 1 else th_train).add(nm)

    def rows_for(names):
        return [r for nm in names for r in v30_by_thm[nm]]

    def dedup(rows):
        seen, o = set(), []
        for r in rows:
            k = (r["theorem_name"], r["tactic"])
            if k in seen:
                continue
            seen.add(k); o.append(r)
        return o

    th_test_rows = dedup(rows_for(th_test))
    tf_test_rows = dedup(rows_for(tf_test))
    v30_val_rows = rows_for(th_val)
    nonnovel = set(v30_by_thm) - novel
    v30_train_rows = rows_for(th_train | nonnovel)

    test_pairs = {_pair(r) for r in (th_test_rows + tf_test_rows)}
    ban = bench_pairs | test_pairs
    v30_train_rows, _ = drop_overlap(v30_train_rows, ban)
    v30_val_rows, _ = drop_overlap(v30_val_rows, ban)
    v29_general_clean, dg = drop_overlap(v29_general, ban)
    v29_best_clean, db = drop_overlap(v29_best, ban)
    v29_val_clean, _ = drop_overlap(v29_val, ban)

    cfg = out / "configs"
    shared_val = v29_val_clean + v30_val_rows
    _dump(cfg / "val_rows.jsonl", shared_val)
    general = v29_general_clean + v30_train_rows
    _dump(cfg / "v30_general_targeted_train_rows.jsonl", general)
    _dump(cfg / "v30_v29best_plus_train_rows.jsonl", v29_best_clean + v30_train_rows)
    _dump(cfg / "v30_targeted_only_train_rows.jsonl", v30_train_rows)
    _dump(cfg / "v30_targeted_upsample_train_rows.jsonl", general + v30_train_rows)

    def write_split(key, test_rows, test_names):
        d = out / key
        tr, _ = drop_overlap(general, {_pair(r) for r in test_rows} | bench_pairs)
        _dump(d / "train_rows.jsonl", tr)
        _dump(d / "test_rows.jsonl", test_rows)
        seeds = [v30_seeds[nm] for nm in sorted(test_names) if nm in v30_seeds]
        _dump(d / "test_seeds.jsonl", seeds)
        return {"n_train": len(tr), "n_test_rows": len(test_rows), "n_test_theorems": len(test_names),
                "n_test_seeds": len(seeds)}

    th = write_split("theorem_holdout", th_test_rows, th_test)
    tf = write_split("targeted_family_holdout", tf_test_rows, tf_test)

    # density of each targeted-family-holdout family in the final train
    train_fam: Dict[str, set] = defaultdict(set)
    for r in general:
        train_fam[family_of(r)].add(r["theorem_name"])
    tf_density = {fam: len(train_fam.get(fam, set())) for fam in {thm_fam[nm] for nm in tf_test}}

    benchmarks = {b: {"seeds": sp, "note": "preserved unchanged"} for b, sp in zip(
        ["v25_heldout", "v26_holdout", "v27_holdout", "v28_holdout", "v29_holdout",
         "v29_family_density_holdout", "v29_low_density_holdout"], args.bench_seeds)}
    benchmarks["v30_theorem_holdout"] = {"seeds": str(out / "theorem_holdout" / "test_seeds.jsonl")}
    benchmarks["v30_targeted_family_holdout"] = {"seeds": str(out / "targeted_family_holdout" / "test_seeds.jsonl")}
    (out / "benchmarks.json").write_text(json.dumps(benchmarks, indent=2), encoding="utf-8")

    # leakage assertions
    all_train = general + (v29_best_clean + v30_train_rows) + v30_train_rows + (general + v30_train_rows)
    tp = {_pair(r) for r in all_train}
    tri = {(r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", "")) for r in all_train}
    assert not (tp & test_pairs), "v30 split test statement leaked into train"
    assert not (tp & bench_pairs), "v25-v29 benchmark statement leaked into train"
    test_tri = {(r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", ""))
                for r in (th_test_rows + tf_test_rows)}
    assert not (tri & test_tri), "triple leaked train<->test"
    assert not ({r["theorem_name"] for r in general} & (th_test | tf_test)), "test name leaked into train"
    for r in all_train:
        assert "state_after" not in r

    summary = {
        "config": "v30_mathlib_specialist_dataset",
        "pools": {"v29_general": len(v29_general), "v29_best": len(v29_best), "v30_rows": len(v30)},
        "novel_v30_theorems": len(novel), "nonnovel_v30_theorems": len(nonnovel),
        "configs": {"v30_general_targeted": len(general),
                    "v30_v29best_plus": len(v29_best_clean + v30_train_rows),
                    "v30_targeted_only": len(v30_train_rows),
                    "v30_targeted_upsample": len(general + v30_train_rows),
                    "shared_val": len(shared_val)},
        "theorem_holdout": {**th, "by_category": dict(Counter(thm_cat[nm] for nm in th_test))},
        "targeted_family_holdout": {**tf, "family_train_density": tf_density,
                                    "by_family": dict(Counter(thm_fam[nm] for nm in tf_test))},
        "dropped_overlap": {"v29_general": dg, "v29_best": db},
        "benchmarks_preserved": ["v25", "v26", "v27", "v28", "v29", "v29_family_density", "v29_low_density"],
        "uses_state_after": False, "uses_manual_oracle": False,
        "leakage_guard": "name + statement + triple vs all v30 splits and v25-v29 benchmarks",
        "category_balanced": "NOT built (v29 confirmed harmful negative control)",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[v30 dataset] v30 rows={len(v30)} novel={len(novel)} nonnovel={len(nonnovel)}")
    print(f"[v30 dataset] configs: {summary['configs']}")
    print(f"[v30 dataset] theorem_holdout={th} by_cat={summary['theorem_holdout']['by_category']}")
    print(f"[v30 dataset] targeted_family_holdout={tf} train_density={tf_density}")
    print("[v30 dataset] leakage guards PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
