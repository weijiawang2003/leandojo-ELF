"""Mini-ELF v8 Part 2 — materialise proof-block train/test regimes on disk.

Wraps :mod:`mini_elf_lean.proof_block_dataset` and writes:

  data/processed/proof_blocks_interpolation/{train,val,test}.jsonl
  data/processed/proof_blocks_family_holdout/<family>/{train,test}.jsonl
  data/processed/proof_blocks_operation_holdout/<op>/{train,test}.jsonl
  data/processed/proof_blocks_donorless_eval/{train,test}.jsonl

Plus a top-level ``data/processed/proof_blocks_manifest.json`` summarising row
counts and the families/operations chosen.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.proof_block_dataset import (  # noqa: E402
    PB_FAMILIES,
    assert_family_holdout, assert_no_state_after, assert_no_theorem_leakage,
    assert_nonempty_tactics, assert_operation_holdout,
    build_donorless_eval, build_family_holdout, build_interpolation,
    build_operation_holdout, load_pool, write_regime,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out-root", default=str(ROOT / "data" / "processed"))
    args = ap.parse_args()

    repo = Path(args.root)
    out_root = Path(args.out_root)

    pool = load_pool(repo)
    if not pool:
        print("ERROR: pool empty — check data/processed", file=sys.stderr)
        return 1
    print(f"pool: {len(pool)} verified rows, "
          f"{len({r.theorem_name for r in pool})} unique theorems, "
          f"{len({r.family for r in pool if r.family})} families, "
          f"{len({r.required_operation for r in pool})} operations")

    top: Dict[str, object] = {"pool": {
        "n_rows": len(pool),
        "n_theorems": len({r.theorem_name for r in pool}),
        "n_families": len({r.family for r in pool if r.family}),
        "n_operations": len({r.required_operation for r in pool}),
    }, "regimes": {}}

    # ---- interpolation ----
    interp = build_interpolation(pool)
    assert_no_theorem_leakage(interp)
    assert_no_state_after(interp)
    assert_nonempty_tactics(interp)
    d_interp = out_root / "proof_blocks_interpolation"
    counts = write_regime(interp, d_interp)
    top["regimes"]["interpolation"] = {"dir": str(d_interp.relative_to(repo)),
                                       "counts": counts}
    print(f"  interpolation     -> {counts}")

    # ---- family_holdout (one fold per planner-blind family) ----
    fh_root = out_root / "proof_blocks_family_holdout"
    fh_summary = {}
    for fam in PB_FAMILIES:
        rows = build_family_holdout(pool, fam)
        assert_family_holdout(rows, fam)
        assert_no_theorem_leakage(rows)
        assert_no_state_after(rows)
        assert_nonempty_tactics(rows)
        d = fh_root / fam
        counts = write_regime(rows, d)
        fh_summary[fam] = counts
        print(f"  family_holdout/{fam:<20} -> {counts}")
    top["regimes"]["family_holdout"] = {"dir": str(fh_root.relative_to(repo)),
                                        "folds": fh_summary}

    # ---- operation_holdout (one fold per observed required_operation) ----
    operations = sorted({r.required_operation for r in pool})
    oh_root = out_root / "proof_blocks_operation_holdout"
    oh_summary = {}
    for op in operations:
        rows = build_operation_holdout(pool, op)
        assert_operation_holdout(rows, op)
        assert_no_theorem_leakage(rows)
        assert_no_state_after(rows)
        assert_nonempty_tactics(rows)
        d = oh_root / op
        counts = write_regime(rows, d)
        oh_summary[op] = counts
        print(f"  operation_holdout/{op:<18} -> {counts}")
    top["regimes"]["operation_holdout"] = {"dir": str(oh_root.relative_to(repo)),
                                            "folds": oh_summary}

    # ---- donorless_eval ----
    dl = build_donorless_eval(pool)
    assert_no_theorem_leakage(dl)
    assert_no_state_after(dl)
    assert_nonempty_tactics(dl)
    d_dl = out_root / "proof_blocks_donorless_eval"
    counts = write_regime(dl, d_dl)
    top["regimes"]["donorless_eval"] = {"dir": str(d_dl.relative_to(repo)),
                                         "counts": counts}
    print(f"  donorless_eval    -> {counts}")

    # ---- top-level manifest ----
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "proof_blocks_manifest.json").write_text(
        json.dumps(top, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_root / 'proof_blocks_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
