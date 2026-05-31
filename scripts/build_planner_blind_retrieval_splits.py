"""V7 Part 2 — materialise donor-scarcity retrieval splits from the planner-blind
corpus.

Reads the base planner-blind dataset (the same rows v6 used) and re-assigns each
row's ``split`` under the v7 strategies in :mod:`mini_elf_lean.retrieval_splits`,
writing fresh ``next_tactic.jsonl`` files (all original fields preserved; only
``split`` changes; no val). Leave-one-out regimes write one fold sub-directory per
held family/operation plus a ``manifest.json``; k-shot/literal write a single
split plus ``meta.json``.

Outputs under ``data/processed/``:
  planner_blind_family_holdout/<family>/next_tactic.jsonl   (+ manifest.json)
  planner_blind_operation_holdout/<operation>/next_tactic.jsonl (+ manifest.json)
  planner_blind_kshot_0|1|2/next_tactic.jsonl               (+ meta.json)
  planner_blind_literal_holdout/next_tactic.jsonl           (+ meta.json)

Deterministic; torch-free; no Lean; no ``state_after``."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_elf_lean.baselines import load_dataset  # noqa: E402
from mini_elf_lean.io_utils import read_jsonl, write_jsonl  # noqa: E402
from mini_elf_lean.retrieval_features import OP_UNKNOWN, extract_features  # noqa: E402
from mini_elf_lean.retrieval_splits import (  # noqa: E402
    family_absent_from_train,
    family_holdout_folds,
    family_train_count,
    kshot_family_split,
    literal_holdout_split,
    operation_absent_from_train,
    operation_holdout_folds,
)


def _slug(s: str) -> str:
    return "".join(c if (c.isalnum() or c in "_-") else "_" for c in s)


def _family_map(seeds: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in read_jsonl(seeds):
        m = row.get("metadata") or {}
        if row.get("theorem_name") and m.get("pattern_family"):
            out[row["theorem_name"]] = m["pattern_family"]
    return out


def _write_split(raw_rows: Sequence[dict], assign: Dict[str, str], out_dir: Path) -> Dict[str, int]:
    """Write a next_tactic.jsonl with each row's split overridden by ``assign``.
    Rows whose theorem is unassigned are dropped (should not happen)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_out: List[dict] = []
    for r in raw_rows:
        name = r.get("theorem_name")
        if name not in assign:
            continue
        nr = dict(r)
        nr["split"] = assign[name]
        rows_out.append(nr)
    write_jsonl(out_dir / "next_tactic.jsonl", rows_out)
    n_train = sum(1 for r in rows_out if r["split"] == "train")
    n_test = sum(1 for r in rows_out if r["split"] == "test")
    thms = {r["theorem_name"] for r in rows_out}
    tr_thms = {r["theorem_name"] for r in rows_out if r["split"] == "train"}
    te_thms = {r["theorem_name"] for r in rows_out if r["split"] == "test"}
    return {"n_rows": len(rows_out), "n_train_rows": n_train, "n_test_rows": n_test,
            "n_theorems": len(thms), "n_train_theorems": len(tr_thms),
            "n_test_theorems": len(te_thms)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dataset", type=Path,
                    default=ROOT / "data/processed/planner_blind_split_lean_cli/next_tactic.jsonl")
    ap.add_argument("--seeds", type=Path, default=ROOT / "data/seeds/planner_blind_seeds.jsonl")
    ap.add_argument("--out-root", type=Path, default=ROOT / "data/processed")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    raw_rows = list(read_jsonl(args.dataset))
    examples = load_dataset(args.dataset)
    theorems = sorted({e.theorem_name for e in examples})
    thm2fam = _family_map(args.seeds)
    thm2op: Dict[str, str] = {}
    thm_tactics: Dict[str, List[str]] = defaultdict(list)
    for e in examples:
        thm2op.setdefault(e.theorem_name, extract_features(e.theorem_statement, e.state_before).required_operation)
        thm_tactics[e.theorem_name].append(e.tactic)

    print(f"base: {len(raw_rows)} rows, {len(theorems)} theorems, {len(set(thm2fam.values()))} families")

    # ---- family_holdout (leave-one-family-out) ----
    fam_root = args.out_root / "planner_blind_family_holdout"
    fam_manifest = {"strategy": "family_holdout", "description":
                    "leave-one-family-out; test family has no same-family train donor",
                    "folds": []}
    for held, assign in family_holdout_folds(theorems, thm2fam):
        assert family_absent_from_train(assign, thm2fam, held), f"leak: {held} in train"
        d = fam_root / _slug(held)
        stats = _write_split(raw_rows, assign, d)
        held_op = next((thm2op[t] for t in theorems if thm2fam.get(t) == held), OP_UNKNOWN)
        # does a *different* family with the same operation remain in train?
        sib = sorted({thm2fam.get(t) for t in theorems
                      if assign.get(t) == "train" and thm2op.get(t) == held_op
                      and thm2fam.get(t) != held} - {None})
        fam_manifest["folds"].append({
            "held_family": held, "held_operation": held_op, "dir": str(d.relative_to(args.out_root)),
            "same_operation_sibling_in_train": bool(sib), "sibling_families": sib, **stats})
    (fam_root / "manifest.json").write_text(json.dumps(fam_manifest, indent=2), encoding="utf-8")
    print(f"family_holdout: {len(fam_manifest['folds'])} folds -> {fam_root}")

    # ---- operation_holdout (leave-one-operation-out) ----
    op_root = args.out_root / "planner_blind_operation_holdout"
    op_manifest = {"strategy": "operation_holdout", "description":
                   "leave-one-operation-out; all families of the held operation absent from train",
                   "folds": []}
    for held, assign in operation_holdout_folds(theorems, thm2op):
        assert operation_absent_from_train(assign, thm2op, held), f"leak: op {held} in train"
        d = op_root / _slug(held)
        stats = _write_split(raw_rows, assign, d)
        held_fams = sorted({thm2fam.get(t) for t in theorems if thm2op.get(t, OP_UNKNOWN) == held} - {None})
        op_manifest["folds"].append({
            "held_operation": held, "held_families": held_fams,
            "dir": str(d.relative_to(args.out_root)), **stats})
    (op_root / "manifest.json").write_text(json.dumps(op_manifest, indent=2), encoding="utf-8")
    print(f"operation_holdout: {len(op_manifest['folds'])} folds -> {op_root}")

    # ---- k-shot ----
    for k in (0, 1, 2):
        assign = kshot_family_split(theorems, thm2fam, k, seed=args.seed)
        # invariant: each family has at most k train theorems
        for fam in set(thm2fam.values()):
            assert family_train_count(assign, thm2fam, fam) <= k, f"kshot {k}: {fam} exceeds k"
        d = args.out_root / f"planner_blind_kshot_{k}"
        stats = _write_split(raw_rows, assign, d)
        (d / "meta.json").write_text(json.dumps(
            {"strategy": "k_shot_family", "k": k,
             "description": f"each family keeps {k} train donor theorem(s); rest -> test",
             **stats}, indent=2), encoding="utf-8")
        print(f"kshot_{k}: {stats}")

    # ---- literal_holdout ----
    assign, held_lits = literal_holdout_split(dict(thm_tactics), seed=args.seed)
    d = args.out_root / "planner_blind_literal_holdout"
    stats = _write_split(raw_rows, assign, d)
    # invariant: each held literal absent from every train tactic
    train_tacs = [t for e in examples if assign.get(e.theorem_name) == "train" for t in [e.tactic]]
    import re
    NUM = re.compile(r"(?<![\w.])\d+(?!\w)")
    train_lits = {m.group(0) for t in train_tacs for m in NUM.finditer(t)}
    for thm, lits in held_lits.items():
        assert not (set(lits) & train_lits), f"literal leak: {thm} literals {lits} in train"
    (d / "meta.json").write_text(json.dumps(
        {"strategy": "literal_holdout",
         "description": "schema present in train; each test theorem's literal globally unseen in train tactics",
         "held_literals": held_lits, "train_literals": sorted(train_lits), **stats}, indent=2), encoding="utf-8")
    print(f"literal_holdout: held {list(held_lits)} ; {stats}")
    print("ALL SPLITS BUILT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
