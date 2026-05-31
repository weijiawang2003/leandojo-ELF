"""Mini-ELF v26 — Part 4: Mathlib specialist train/eval splits.

Specialist pool = **v26 verified rows** (237) + **v25 verified rows from v25
TRAIN theorems only** (68). The v25 held-out *test* rows (35) are never in the
pool — they remain the established benchmark.

Builds three split families under
``data/processed/v26_mathlib_specialist_splits/``:

  theorem_holdout/    train / val / test, stratified by theorem within category
                      (every 5th theorem -> test, next -> val, rest -> train).
                      Also writes train_rows_plus_core.jsonl (train + a small
                      curated v18 broad-core subset for logic/list/nat skills —
                      NOT the whole v24 corpus).
  category_holdout_set/    hold out *all Set theorems* as test (Q3: is Set
                           reachable from cross-category transfer alone?).
  category_holdout_order/  hold out all order/≤ theorems as test.

Leakage guards (asserted + reported):
  * no theorem_name appears in both a split's train and its eval;
  * no (statement, state_before, tactic) triple overlaps train and eval
    (statements can coincide across v26/v25 even when names differ — those
    train rows are dropped);
  * the v25 held-out test theorems never enter any train set;
  * no state_after anywhere (it is never present in these rows).

Honesty: only Lean-verified rows; no manual oracle as predictions; Mathlib real
and external.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]

CORE_PLUS_CATEGORIES = {  # small v18 subset for the plus_core config
    "implication", "conjunction", "disjunction", "negation",
    "equality_rewrite", "nat_succ", "list",
}


def _read(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def _triple(r: Dict[str, Any]) -> Tuple[str, str, str]:
    return (r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", ""))


def _norm_row(r: Dict[str, Any]) -> Dict[str, Any]:
    """Project a verified-trace row onto the training-row schema."""
    return {
        "theorem_name": r["theorem_name"], "theorem_statement": r["theorem_statement"],
        "state_before": r["state_before"], "tactic": r["tactic"],
        "category": r.get("category", "unknown"),
        "family": r.get("category", "unknown"),
        "expected_skill": r.get("expected_skill", r.get("category", "unknown")),
        "required_operation": r.get("required_operation", "unknown"),
        "transfer": r.get("transfer", "mathlib"),
        "corpus_source": r.get("corpus_source", "v25_mathlib_tierc"),
        "tactic_source": "verified", "split": "train",
        "proof_head": (r.get("tactic", "").strip().split() or [""])[0].split(";")[0],
        "mathlib": True,
    }


def stratified_3way(theorems_by_cat: Dict[str, List[str]]
                    ) -> Tuple[Set[str], Set[str], Set[str]]:
    train, val, test = set(), set(), set()
    for cat, names in theorems_by_cat.items():
        for i, nm in enumerate(sorted(names)):
            m = i % 5
            (test if m == 0 else val if m == 1 else train).add(nm)
    return train, val, test


def split_rows(rows: List[Dict[str, Any]], train_t: Set[str], val_t: Set[str],
               test_t: Set[str]) -> Tuple[List, List, List, Dict[str, int]]:
    """Assign rows to splits by theorem; drop train rows whose triple appears
    in val/test (statement collisions across different theorem names)."""
    by_split = {"train": [], "val": [], "test": []}
    for r in rows:
        nm = r["theorem_name"]
        if nm in test_t:
            by_split["test"].append(r)
        elif nm in val_t:
            by_split["val"].append(r)
        elif nm in train_t:
            by_split["train"].append(r)
    eval_triples = {_triple(r) for r in by_split["val"]} | {_triple(r) for r in by_split["test"]}
    kept_train, dropped = [], 0
    for r in by_split["train"]:
        if _triple(r) in eval_triples:
            dropped += 1
            continue
        kept_train.append(r)
    by_split["train"] = kept_train
    report = {"dropped_train_triple_overlap": dropped}
    # hard assertions
    names = {"train": {r["theorem_name"] for r in by_split["train"]},
             "val": {r["theorem_name"] for r in by_split["val"]},
             "test": {r["theorem_name"] for r in by_split["test"]}}
    assert not (names["train"] & names["test"]), "theorem leak train/test"
    assert not (names["train"] & names["val"]), "theorem leak train/val"
    tr_tri = {_triple(r) for r in by_split["train"]}
    assert not (tr_tri & {_triple(r) for r in by_split["test"]}), "triple leak train/test"
    return by_split["train"], by_split["val"], by_split["test"], report


def write_split(out_dir: Path, train, val, test, test_seeds, meta, *, plus_core=None):
    out_dir.mkdir(parents=True, exist_ok=True)

    def dump(name, rows):
        with (out_dir / name).open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    dump("train_rows.jsonl", train)
    if val is not None:
        dump("val_rows.jsonl", val)
    dump("test_rows.jsonl", test)
    dump("test_seeds.jsonl", test_seeds)
    if plus_core is not None:
        dump("train_rows_plus_core.jsonl", plus_core)
    (out_dir / "split.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                                        encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v26-verified", default=str(ROOT / "data" / "traces" / "v26_mathlib_specialist_verified.jsonl"))
    ap.add_argument("--v25-verified", default=str(ROOT / "data" / "traces" / "v25_mathlib_tierc_verified.jsonl"))
    ap.add_argument("--v25-test-theorems", default=str(ROOT / "data" / "processed" / "v25_tierc_augmented" / "test_theorems.json"))
    ap.add_argument("--v26-seeds", default=str(ROOT / "data" / "seeds" / "v26_mathlib_specialist_seeds.jsonl"))
    ap.add_argument("--v25-seeds", default=str(ROOT / "data" / "seeds" / "v25_mathlib_tierc_seeds.jsonl"))
    ap.add_argument("--v18-core-train", default=str(ROOT / "data" / "processed" / "v18_broad_core" / "train.jsonl"))
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "processed" / "v26_mathlib_specialist_splits"))
    args = ap.parse_args(argv)

    tt = json.loads(Path(args.v25_test_theorems).read_text())
    v25_test = set(tt["test_theorems"])

    v26_rows = [_norm_row(r) for r in _read(Path(args.v26_verified))]
    v25_all = _read(Path(args.v25_verified))
    v25_train_rows = [_norm_row(r) for r in v25_all if r["theorem_name"] not in v25_test]
    pool = v26_rows + v25_train_rows
    # dedup identical (name, tactic)
    seen, dpool = set(), []
    for r in pool:
        k = (r["theorem_name"], r["tactic"])
        if k in seen:
            continue
        seen.add(k); dpool.append(r)
    pool = dpool

    # seed map for test benchmarks
    seed_map: Dict[str, Dict[str, Any]] = {}
    for sp in (args.v26_seeds, args.v25_seeds):
        for s in _read(Path(sp)):
            seed_map[s["theorem_name"]] = s

    # theorems-by-category over the pool
    by_cat: Dict[str, List[str]] = defaultdict(list)
    seen_t: Set[str] = set()
    for r in pool:
        nm, cat = r["theorem_name"], r["category"]
        if nm not in seen_t:
            seen_t.add(nm); by_cat[cat].append(nm)

    out_root = Path(args.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    splits_summary: Dict[str, Any] = {"pool_rows": len(pool),
                                      "pool_theorems": len(seen_t),
                                      "pool_by_category": {k: len(v) for k, v in by_cat.items()},
                                      "v25_test_theorems_excluded": sorted(v25_test),
                                      "splits": {}}

    # ---- 1. theorem_holdout ---- #
    train_t, val_t, test_t = stratified_3way(by_cat)
    tr, va, te, rep = split_rows(pool, train_t, val_t, test_t)
    test_seeds = [seed_map[nm] for nm in sorted(test_t) if nm in seed_map]

    # plus_core: train + curated small v18 core subset
    core_pool = [r for r in _read(Path(args.v18_core_train))
                 if r.get("category") in CORE_PLUS_CATEGORIES and r.get("verified", True)]
    core_norm = []
    for r in core_pool:
        core_norm.append({
            "theorem_name": r["theorem_name"], "theorem_statement": r["theorem_statement"],
            "state_before": r.get("state_before", ""), "tactic": r["tactic"],
            "category": r.get("category", "core"), "family": r.get("category", "core"),
            "expected_skill": "core-shaped",
            "required_operation": r.get("required_operation", "unknown"),
            "transfer": "core", "corpus_source": "v18_broad_core",
            "tactic_source": "verified", "split": "train",
            "proof_head": (r.get("tactic", "").strip().split() or [""])[0].split(";")[0],
            "mathlib": False,
        })
    plus_core = tr + core_norm

    write_split(out_root / "theorem_holdout", tr, va, te, test_seeds, {
        "split": "theorem_holdout", "stratified_by": "category, every 5th->test, next->val",
        "n_train": len(tr), "n_val": len(va), "n_test": len(te),
        "n_train_plus_core": len(plus_core), "n_core_added": len(core_norm),
        "train_theorems": sorted(train_t), "val_theorems": sorted(val_t),
        "test_theorems": sorted(test_t), "n_test_seeds": len(test_seeds),
        "leakage": rep, "uses_state_after": False,
    }, plus_core=plus_core)
    splits_summary["splits"]["theorem_holdout"] = {
        "n_train": len(tr), "n_val": len(va), "n_test": len(te),
        "n_test_theorems": len(test_t), "n_core_added": len(core_norm), **rep,
        "test_by_category": dict(Counter(r["category"] for r in te))}

    # ---- 2 & 3. category holdouts ---- #
    for cat_key, match in (("set", lambda r: r["category"] == "set"),
                           ("order", lambda r: r.get("expected_skill") == "order")):
        test_names = {r["theorem_name"] for r in pool if match(r)}
        train_names = {r["theorem_name"] for r in pool if r["theorem_name"] not in test_names}
        ctr, _cv, cte, crep = split_rows(pool, train_names, set(), test_names)
        cseeds = [seed_map[nm] for nm in sorted(test_names) if nm in seed_map]
        d = out_root / f"category_holdout_{cat_key}"
        write_split(d, ctr, None, cte, cseeds, {
            "split": f"category_holdout_{cat_key}",
            "held_out_category": cat_key, "n_train": len(ctr), "n_test": len(cte),
            "n_test_theorems": len(test_names), "test_theorems": sorted(test_names),
            "n_test_seeds": len(cseeds), "leakage": crep, "uses_state_after": False})
        splits_summary["splits"][f"category_holdout_{cat_key}"] = {
            "n_train": len(ctr), "n_test": len(cte), "n_test_theorems": len(test_names), **crep}

    # ---- v25 held-out benchmark pointer ---- #
    v25_bench = out_root / "v25_heldout_benchmark"
    v25_bench.mkdir(parents=True, exist_ok=True)
    v25_test_seeds = _read(ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl")
    with (v25_bench / "test_seeds.jsonl").open("w", encoding="utf-8") as f:
        for s in v25_test_seeds:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    (v25_bench / "README.json").write_text(json.dumps({
        "note": "v25 held-out tier-C benchmark, preserved unchanged for v24/v25/v26 comparison.",
        "n_theorems": len(v25_test_seeds), "source": "data/seeds/v25_mathlib_tierc_test_seeds.jsonl"},
        indent=2), encoding="utf-8")
    splits_summary["splits"]["v25_heldout_benchmark"] = {"n_theorems": len(v25_test_seeds)}

    splits_summary["uses_state_after"] = False
    splits_summary["uses_manual_oracle"] = False
    (out_root / "summary.json").write_text(json.dumps(splits_summary, indent=2, ensure_ascii=False),
                                           encoding="utf-8")

    print(f"[splits] pool={len(pool)} rows / {len(seen_t)} theorems")
    print(f"[splits] theorem_holdout: train={len(tr)} val={len(va)} test={len(te)} "
          f"(+core={len(core_norm)} -> plus_core={len(plus_core)}); dropped_overlap={rep['dropped_train_triple_overlap']}")
    for k in ("category_holdout_set", "category_holdout_order"):
        s = splits_summary["splits"][k]
        print(f"[splits] {k}: train={s['n_train']} test={s['n_test']} ({s['n_test_theorems']} thms)")
    print(f"[splits] v25 held-out benchmark: {len(v25_test_seeds)} theorems (preserved)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
