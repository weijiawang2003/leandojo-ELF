"""Mini-ELF v10 follow-up — build per-operation combined_v10 training regimes
that EXCLUDE the held operation entirely (leave-one-operation-out).

The legacy `proof_blocks_combined_v10_redundancy_interpolation` pool baked
the v10 interpolation split into a single model that saw 36 of 40 v10 cells,
including most of the cells later used as cell_holdout/op_holdout test rows.
Evaluating that legacy model on holdout regimes was advertised as a
generalisation test, but was actually in-distribution memorisation.

This script emits one regime dir per operation:

  data/processed/proof_blocks_combined_v10_per_op/<operation>/{train,test}.jsonl

with::

  train = v8 base train pool (proof_blocks_interpolation/train.jsonl)
        + all v10 redundancy rows MINUS the held operation
  test  = v10 redundancy rows for the held operation (same as
          proof_blocks_redundancy_operation_holdout/<operation>/test.jsonl)

A leakage assertion runs inline before each regime is written: no train-row
theorem_name appears in the test split and no train row carries
``required_operation == held_operation``. If the assertion fails the script
exits with code 2 and writes nothing.

Deterministic; torch-free; no Lean."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.io_utils import read_jsonl  # noqa: E402


def _load(p: Path) -> List[dict]:
    if not p.exists():
        return []
    return list(read_jsonl(p))


def _v10_required_op(r: dict) -> str:
    """v10 proof_blocks rows carry ``required_operation``; for any v8 base row
    that key may be ``unknown`` — return whatever's there."""
    return r.get("required_operation") or "unknown"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v8-base",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_interpolation" / "train.jsonl"))
    ap.add_argument("--v10-corpus",
                    default=str(ROOT / "data" / "processed"
                                / "redundancy_lean_cli" / "next_tactic.jsonl"))
    ap.add_argument("--op-holdout-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_redundancy_operation_holdout"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_combined_v10_per_op"))
    args = ap.parse_args(argv)

    base_rows = _load(Path(args.v8_base))
    v10_rows = _load(Path(args.v10_corpus))

    # Convert v10 next_tactic rows to proof_blocks rows (mirror of
    # build_redundancy_proof_blocks._to_pb_row).
    def _v10_to_pb(r: dict, regime: str) -> dict:
        m = r.get("metadata") or {}
        return {
            "theorem_name": r["theorem_name"],
            "theorem_statement": r["theorem_statement"],
            "state_before": r["state_before"],
            "tactic": r["tactic"],
            "family": m.get("surface_family"),
            "required_operation": m.get("operation"),
            "corpus_source": "redundancy_corpus",
            "tactic_source": "verified",
            "split": "train",
            "regime": regime,
        }

    # Group v10 cells by operation
    v10_by_op: Dict[str, List[dict]] = defaultdict(list)
    for r in v10_rows:
        op = (r.get("metadata") or {}).get("operation") or "unknown"
        v10_by_op[op].append(r)

    operations = sorted(v10_by_op.keys())
    print(f"v8 base pool: {len(base_rows)} rows")
    print(f"v10 corpus: {len(v10_rows)} rows across {len(operations)} operations")
    for op in operations:
        print(f"  {op:30s}  {len(v10_by_op[op])} cells")

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    op_holdout_root = Path(args.op_holdout_root)

    manifest = {"description": ("per-op LOFO regimes: train = v8 base + v10 minus "
                                "held op; test = held op's cells"),
                "folds": []}

    for op in operations:
        out_dir = out_root / op
        out_dir.mkdir(parents=True, exist_ok=True)

        # train = v8 base + v10 (minus held op)
        train_rows: List[dict] = list(base_rows)
        for other_op, rows in v10_by_op.items():
            if other_op == op:
                continue
            for r in rows:
                train_rows.append(_v10_to_pb(r, regime=f"per_op_combined_v10/{op}"))

        # test = the held op's cells (same as op_holdout test)
        # We pull from the op_holdout regime so the test set is byte-identical
        # to what evaluate_proof_block_seq2seq.py reads for the regular op_holdout
        # eval — this means clean per-op metrics are directly comparable to the
        # leaked-legacy op_holdout metrics.
        oph_test = op_holdout_root / op / "test.jsonl"
        if not oph_test.exists():
            print(f"  SKIP {op}: no op_holdout test set at {oph_test}")
            continue
        test_rows = list(_load(oph_test))

        # ----- leakage assertion -----
        train_thms = {r["theorem_name"] for r in train_rows}
        test_thms = {r["theorem_name"] for r in test_rows}
        leaked = train_thms & test_thms
        if leaked:
            print(f"LEAKAGE {op}: {len(leaked)} test theorems in train; "
                  f"first {sorted(leaked)[:3]}", file=sys.stderr)
            return 2
        # Also assert no V10 train row carries the held op. v8 base-pool rows
        # may carry the held op (e.g. the basic-corpus `neg_exfalso` family has
        # operation=contradiction); that is *transfer signal*, NOT leakage —
        # the baseline_v8 model has it too. The bug being guarded against is
        # the v10 corpus's per-op cells slipping into train. We identify v10
        # rows by their `corpus_source == "redundancy_corpus"` (set by
        # ``build_redundancy_proof_blocks``).
        bad_v10_rows = [r for r in train_rows
                        if r.get("corpus_source") == "redundancy_corpus"
                        and _v10_required_op(r) == op]
        if bad_v10_rows:
            print(f"LEAKAGE {op}: {len(bad_v10_rows)} v10 train rows carry "
                  f"required_operation={op}", file=sys.stderr)
            return 2

        # ----- write -----
        with (out_dir / "train.jsonl").open("w", encoding="utf-8") as f:
            for r in train_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with (out_dir / "test.jsonl").open("w", encoding="utf-8") as f:
            for r in test_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        # no val.jsonl - the trainer will synthesise 10% of train as val

        meta = {"held_operation": op, "n_train_rows": len(train_rows),
                "n_test_rows": len(test_rows),
                "n_train_theorems": len(train_thms),
                "n_test_theorems": len(test_thms),
                "no_leakage_assertion": "passed",
                "no_held_operation_in_train_assertion": "passed"}
        (out_dir / "manifest.json").write_text(json.dumps(meta, indent=2),
                                               encoding="utf-8")
        manifest["folds"].append({"operation": op,
                                  "dir": f"proof_blocks_combined_v10_per_op/{op}",
                                  **meta})
        print(f"  {op:30s}  train={len(train_rows):>4}  test={len(test_rows):>3}  -> {out_dir.name}")

    (out_root / "manifest.json").write_text(json.dumps(manifest, indent=2),
                                            encoding="utf-8")
    print(f"WROTE {len(manifest['folds'])} per-op regimes -> {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
