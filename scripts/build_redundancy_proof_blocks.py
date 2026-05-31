"""Mini-ELF v10 — materialise proof_blocks-shape regimes from the redundancy
splits (and optionally combined with the v8 base proof-block pool).

The seq2seq trainer ``scripts/train_proof_block_seq2seq.py`` expects
``regime_dir/{train,val,test}.jsonl`` in proof_blocks row format (one row per
(theorem, tactic) with ``family``, ``required_operation``, ``corpus_source``,
``tactic_source``, ``split``, ``regime`` fields). The v10 split builder writes
``next_tactic.jsonl`` files (one row per cell with a ``split`` field). This
script bridges the two:

  redundancy_only   — convert one redundancy split-dir to a single proof_blocks
                      regime dir.
  combined_v10      — concatenate the redundancy train rows with the base v8
                      proof_blocks_interpolation/train.jsonl pool and emit one
                      combined regime dir. (The base train pool is reused
                      verbatim; redundancy rows are appended.)

Both forms emit ``train.jsonl``, ``test.jsonl``, and a ``manifest.json`` with
the split sizes. There is no synthetic val here — the trainer falls back to
a 10 %-of-train pseudo-val when ``val.jsonl`` is missing, which is the same
behaviour every v8 holdout fold used.

Deterministic; torch-free; no Lean."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.io_utils import read_jsonl  # noqa: E402


def _to_pb_row(r: dict, *, regime: str) -> dict:
    """Convert a v10 next_tactic.jsonl row to a proof_blocks training row.
    Adds ``family``/``required_operation``/``corpus_source``/``tactic_source``/
    ``split``/``regime`` so downstream loaders see the same schema as v8."""
    m = r.get("metadata") or {}
    return {
        "theorem_name": r["theorem_name"],
        "theorem_statement": r["theorem_statement"],
        "state_before": r["state_before"],
        "tactic": r["tactic"],
        "family": m.get("surface_family") or m.get("pattern_family"),
        "required_operation": m.get("operation") or m.get("required_operation"),
        "corpus_source": m.get("corpus_source") or "redundancy_corpus",
        "tactic_source": "verified",
        "split": r.get("split", "train"),
        "regime": regime,
    }


def _read_pb_train(p: Path) -> List[dict]:
    if not p.exists():
        return []
    return list(read_jsonl(p))


def _write_pb(rows: List[dict], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def _convert_one(src_jsonl: Path, *, regime_name: str,
                 out_dir: Path,
                 base_pool: Optional[List[dict]] = None) -> Dict[str, int]:
    """Convert a single redundancy split's next_tactic.jsonl into a proof_blocks
    regime dir. If ``base_pool`` is non-empty, those rows are prepended to the
    train set (unchanged) — used for the combined-v10 variant."""
    rows_in = list(read_jsonl(src_jsonl))
    pb_rows = [_to_pb_row(r, regime=regime_name) for r in rows_in]

    train = [r for r in pb_rows if r["split"] == "train"]
    test = [r for r in pb_rows if r["split"] == "test"]
    # interpolation split sometimes has val; pass through if so
    val = [r for r in pb_rows if r["split"] == "val"]

    if base_pool is not None:
        # Prepend the base v8 pool (already proof_blocks-shape, ``split=train``).
        train = list(base_pool) + train

    out_dir.mkdir(parents=True, exist_ok=True)
    n_tr = _write_pb(train, out_dir / "train.jsonl")
    n_te = _write_pb(test, out_dir / "test.jsonl")
    n_va = _write_pb(val, out_dir / "val.jsonl") if val else 0
    manifest = {
        "regime": regime_name,
        "source_next_tactic": str(src_jsonl),
        "with_base_pool": base_pool is not None,
        "n_train_rows": n_tr,
        "n_test_rows": n_te,
        "n_val_rows": n_va,
        "n_train_theorems": len({r["theorem_name"] for r in train}),
        "n_test_theorems": len({r["theorem_name"] for r in test}),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2),
                                           encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--src", type=Path,
                    default=ROOT / "data" / "processed",
                    help="root dir containing the redundancy_* split dirs")
    ap.add_argument("--out-root", type=Path,
                    default=ROOT / "data" / "processed",
                    help="root dir to write the proof_blocks_redundancy_* dirs")
    ap.add_argument("--base-train", type=Path,
                    default=ROOT / "data" / "processed"
                    / "proof_blocks_interpolation" / "train.jsonl",
                    help="base v8 proof_blocks_interpolation train.jsonl; used"
                         " for combined_v10 variants")
    ap.add_argument("--regimes", nargs="*",
                    default=["redundancy_interpolation",
                             "redundancy_family_holdout",
                             "redundancy_operation_holdout",
                             "redundancy_cell_holdout",
                             "redundancy_low_shot"])
    ap.add_argument("--also-combined", action="store_true",
                    help="emit combined_v10 variants alongside redundancy-only")
    args = ap.parse_args(argv)

    base_pool = _read_pb_train(args.base_train) if args.also_combined else []
    print(f"base pool: {len(base_pool)} rows from {args.base_train}")

    summary: List[Dict[str, object]] = []
    for regime in args.regimes:
        src_root = args.src / regime
        if not src_root.exists():
            print(f"SKIP {regime} (no source dir at {src_root})")
            continue
        next_tactic = src_root / "next_tactic.jsonl"
        if next_tactic.exists():
            # single-split regime
            out_dir = args.out_root / f"proof_blocks_{regime}"
            m = _convert_one(next_tactic, regime_name=regime, out_dir=out_dir)
            print(f"{regime}: train={m['n_train_rows']} test={m['n_test_rows']} -> {out_dir.name}")
            summary.append({"variant": "redundancy_only", **m})
            if args.also_combined:
                cout = args.out_root / f"proof_blocks_combined_v10_{regime}"
                m2 = _convert_one(next_tactic, regime_name=f"combined_{regime}",
                                  out_dir=cout, base_pool=base_pool)
                print(f"  + combined_v10/{regime}: train={m2['n_train_rows']} test={m2['n_test_rows']} -> {cout.name}")
                summary.append({"variant": "combined_v10", **m2})
        else:
            # LOFO root with sub-folds
            for fold in sorted(src_root.iterdir()):
                if not fold.is_dir():
                    continue
                fold_jsonl = fold / "next_tactic.jsonl"
                if not fold_jsonl.exists():
                    continue
                fold_name = f"{regime}/{fold.name}"
                out_dir = args.out_root / f"proof_blocks_{regime}" / fold.name
                m = _convert_one(fold_jsonl, regime_name=fold_name, out_dir=out_dir)
                print(f"{fold_name}: train={m['n_train_rows']} test={m['n_test_rows']} -> {out_dir.name}")
                summary.append({"variant": "redundancy_only", **m})
                if args.also_combined:
                    cout = (args.out_root / f"proof_blocks_combined_v10_{regime}"
                            / fold.name)
                    m2 = _convert_one(fold_jsonl,
                                      regime_name=f"combined_{fold_name}",
                                      out_dir=cout, base_pool=base_pool)
                    print(f"  + combined_v10/{fold_name}: train={m2['n_train_rows']} test={m2['n_test_rows']}")
                    summary.append({"variant": "combined_v10", **m2})

    (args.out_root / "proof_blocks_v10_manifest.json").write_text(
        json.dumps({"folds": summary, "n_folds": len(summary)}, indent=2),
        encoding="utf-8",
    )
    print(f"WROTE {len(summary)} proof_blocks dirs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
