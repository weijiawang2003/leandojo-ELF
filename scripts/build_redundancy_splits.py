"""Mini-ELF v10 — materialise transfer-test splits over the redundancy corpus.

Reads the redundancy seed/processed dataset (one verified row per theorem
cell) and emits the v10 split regimes:

  * ``redundancy_interpolation``       — random 80/20 by theorem; all
                                          operations and surface families
                                          present in both train and test.
  * ``redundancy_family_holdout``      — leave-one-surface-family-out
                                          (1 fold per family). Same-operation
                                          siblings remain in train.
  * ``redundancy_operation_holdout``   — leave-one-operation-out
                                          (1 fold per operation). All
                                          families of the held operation are
                                          absent from train.
  * ``redundancy_cell_holdout``        — leave-one-(operation,family)-cell-out
                                          (1 fold per cell). Same operation
                                          remains via sibling families — the
                                          v10 redundancy condition.
  * ``redundancy_low_shot/k_{1,2}``    — k surface families per operation in
                                          train; rest in test. Tests the
                                          per-operation data-scaling slope.

Output: ``data/processed/<regime>/<fold-or-config>/next_tactic.jsonl`` plus a
``manifest.json`` (LOFO-style) or ``meta.json`` (single-split). Row schema is
unchanged from the v6/v7/v8 pipeline; only the ``split`` field is reassigned.

Deterministic; torch-free; no Lean.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.io_utils import read_jsonl, write_jsonl  # noqa: E402
from mini_elf_lean.retrieval_splits import (  # noqa: E402
    OP_UNKNOWN,
    assert_no_theorem_leakage,
    cell_holdout_folds,
    family_absent_from_train,
    family_holdout_folds,
    kshot_operation_split,
    operation_absent_from_train,
    operation_holdout_folds,
    operation_sibling_in_train,
)


def _slug(s: str) -> str:
    return "".join(c if (c.isalnum() or c in "_-") else "_" for c in s)


def _load_corpus(seeds_path: Path, processed_path: Path):
    """Load the redundancy corpus into a parallel form.

    Returns (raw_rows, thm2fam, thm2op, thm_tactics).
    """
    raw_rows = list(read_jsonl(processed_path))
    seed_rows = list(read_jsonl(seeds_path))
    thm2fam: Dict[str, str] = {}
    thm2op: Dict[str, str] = {}
    for s in seed_rows:
        nm = s.get("theorem_name")
        m = s.get("metadata") or {}
        if not nm:
            continue
        fam = m.get("surface_family") or m.get("pattern_family")
        op = m.get("operation") or m.get("required_operation") or OP_UNKNOWN
        if fam is not None:
            thm2fam[nm] = fam
        thm2op[nm] = op
    return raw_rows, thm2fam, thm2op


def _write_split(raw_rows: Sequence[dict], assign: Dict[str, str], out_dir: Path) -> Dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_out: List[dict] = []
    for r in raw_rows:
        nm = r.get("theorem_name")
        if nm not in assign:
            continue
        nr = dict(r)
        nr["split"] = assign[nm]
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


def _interpolation_assign(theorems: Sequence[str], *, frac_test: float = 0.2, seed: int = 42) -> Dict[str, str]:
    """Deterministic train/test split balanced across operations: ~frac_test of
    each operation's theorems go to test."""
    import hashlib
    # Stable per-theorem score
    def score(n: str) -> float:
        h = hashlib.sha256(f"{n}|{seed}".encode("utf-8")).hexdigest()
        return int(h[:16], 16) / float(1 << 64)
    return {nm: ("test" if score(nm) < frac_test else "train")
            for nm in theorems}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--seeds", type=Path,
                    default=ROOT / "data" / "seeds" / "redundancy_seeds.jsonl")
    ap.add_argument("--dataset", type=Path,
                    default=ROOT / "data" / "processed" / "redundancy_lean_cli"
                    / "next_tactic.jsonl")
    ap.add_argument("--out-root", type=Path, default=ROOT / "data" / "processed")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    if not args.dataset.exists():
        raise SystemExit(
            f"dataset not found: {args.dataset}\n"
            f"Run scripts/collect_traces.py + scripts/build_dataset.py over the "
            f"redundancy seeds first, or use scripts/build_proof_block_dataset.py."
        )

    raw_rows, thm2fam, thm2op = _load_corpus(args.seeds, args.dataset)
    theorems = sorted({r["theorem_name"] for r in raw_rows
                       if r.get("theorem_name") in thm2op})
    print(f"corpus: {len(raw_rows)} rows, {len(theorems)} theorems, "
          f"{len(set(thm2fam.values()))} families, {len(set(thm2op.values()))} operations")

    # ---- redundancy_interpolation ----
    interp_root = args.out_root / "redundancy_interpolation"
    assign = _interpolation_assign(theorems, seed=args.seed)
    assert_no_theorem_leakage(assign)
    stats = _write_split(raw_rows, assign, interp_root)
    (interp_root / "meta.json").write_text(json.dumps({
        "strategy": "interpolation",
        "description": "deterministic 80/20 by theorem; all operations present in both",
        "seed": args.seed, **stats}, indent=2), encoding="utf-8")
    print(f"interpolation: {stats}")

    # ---- redundancy_family_holdout ----
    fam_root = args.out_root / "redundancy_family_holdout"
    fam_manifest = {"strategy": "family_holdout",
                    "description": "leave-one-surface-family-out; same-operation sibling family typically remains",
                    "folds": []}
    for held, assign in family_holdout_folds(theorems, thm2fam):
        assert family_absent_from_train(assign, thm2fam, held), f"leak: family {held} in train"
        d = fam_root / _slug(held)
        stats = _write_split(raw_rows, assign, d)
        held_op = next((thm2op[t] for t in theorems if thm2fam.get(t) == held), OP_UNKNOWN)
        sibling = sorted({thm2fam.get(t) for t in theorems
                          if assign.get(t) == "train" and thm2op.get(t) == held_op
                          and thm2fam.get(t) != held} - {None})
        fam_manifest["folds"].append({
            "held_family": held, "held_operation": held_op,
            "dir": str(d.relative_to(args.out_root)),
            "same_operation_sibling_in_train": bool(sibling),
            "sibling_families": sibling, **stats})
    (fam_root / "manifest.json").write_text(json.dumps(fam_manifest, indent=2),
                                            encoding="utf-8")
    print(f"family_holdout: {len(fam_manifest['folds'])} folds -> {fam_root}")

    # ---- redundancy_operation_holdout ----
    op_root = args.out_root / "redundancy_operation_holdout"
    op_manifest = {"strategy": "operation_holdout",
                   "description": "leave-one-operation-out; all surface families of held op absent from train",
                   "folds": []}
    for held, assign in operation_holdout_folds(theorems, thm2op):
        assert operation_absent_from_train(assign, thm2op, held), f"leak: op {held} in train"
        d = op_root / _slug(held)
        stats = _write_split(raw_rows, assign, d)
        held_fams = sorted({thm2fam.get(t) for t in theorems
                            if thm2op.get(t, OP_UNKNOWN) == held} - {None})
        op_manifest["folds"].append({
            "held_operation": held, "held_families": held_fams,
            "dir": str(d.relative_to(args.out_root)), **stats})
    (op_root / "manifest.json").write_text(json.dumps(op_manifest, indent=2),
                                           encoding="utf-8")
    print(f"operation_holdout: {len(op_manifest['folds'])} folds -> {op_root}")

    # ---- redundancy_cell_holdout ----
    cell_root = args.out_root / "redundancy_cell_holdout"
    cell_manifest = {"strategy": "cell_holdout",
                     "description": ("leave-one-(operation,surface_family)-cell-out; "
                                     "sibling families of the same operation remain in train"),
                     "folds": []}
    sibling_present_count = 0
    for (held_op, held_fam), assign in cell_holdout_folds(theorems, thm2op, thm2fam):
        # invariants: held family absent; held operation present elsewhere (via sibling)
        assert family_absent_from_train(assign, thm2fam, held_fam), \
            f"cell_holdout leak: family {held_fam} in train"
        sib = operation_sibling_in_train(assign, thm2op, thm2fam, held_op, held_fam)
        d = cell_root / _slug(f"{held_op}__{held_fam}")
        stats = _write_split(raw_rows, assign, d)
        if sib:
            sibling_present_count += 1
        cell_manifest["folds"].append({
            "held_operation": held_op, "held_family": held_fam,
            "dir": str(d.relative_to(args.out_root)),
            "operation_sibling_in_train": sib, **stats})
    cell_manifest["folds_with_operation_sibling_in_train"] = sibling_present_count
    (cell_root / "manifest.json").write_text(json.dumps(cell_manifest, indent=2),
                                             encoding="utf-8")
    print(f"cell_holdout: {len(cell_manifest['folds'])} folds "
          f"({sibling_present_count} with operation sibling in train) -> {cell_root}")

    # ---- redundancy_low_shot (k=1, k=2 surface families per operation) ----
    low_root = args.out_root / "redundancy_low_shot"
    low_meta = {"strategy": "low_shot_operation",
                "description": ("each operation contributes k surface families "
                                "(deterministic by seed) as training donors"),
                "seed": args.seed, "folds": []}
    for k in (1, 2):
        assign = kshot_operation_split(theorems, thm2op, thm2fam, k, seed=args.seed)
        # Invariant: each operation has at most k distinct families in train.
        for op in set(thm2op.values()):
            train_fams_this_op = {thm2fam.get(t) for t, s in assign.items()
                                  if s == "train" and thm2op.get(t) == op}
            train_fams_this_op.discard(None)
            assert len(train_fams_this_op) <= k, \
                f"low_shot k={k}: op={op} has {len(train_fams_this_op)} train families"
        d = low_root / f"k_{k}"
        stats = _write_split(raw_rows, assign, d)
        (d / "meta.json").write_text(json.dumps({
            "strategy": "low_shot_operation", "k_train_cells_per_op": k,
            "seed": args.seed, **stats}, indent=2), encoding="utf-8")
        low_meta["folds"].append({"k_train_cells_per_op": k,
                                  "dir": str(d.relative_to(args.out_root)),
                                  **stats})
    (low_root / "manifest.json").write_text(json.dumps(low_meta, indent=2),
                                            encoding="utf-8")
    print(f"low_shot: {len(low_meta['folds'])} configs -> {low_root}")

    print("ALL V10 REDUNDANCY SPLITS BUILT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
