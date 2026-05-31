"""Mini-ELF v11 — per-family LOFO regimes for the v8/v9 negative-control test.

v10 isolated a specific question and could not answer it cleanly: do the v8
matrix's two persistently-zero family_holdout cells (``forall_inst`` and
``rewrite_succ``) become non-zero when v10 redundancy cells are folded into
the *same* family-LOFO training pool the v8 matrix used?

The v10 follow-up (per-operation LOFO) couldn't answer this because it held
out a whole *operation* at once, removing the v10 redundancy cells too. v11
holds out only the planner-blind *family* and keeps the v10 redundancy cells
of the same operation in train — exactly the situation v10's hypothesis is
about.

Per target family ``<fam>``::

    train = v8 *family-LOFO* train pool
            (data/processed/proof_blocks_family_holdout/<fam>/train.jsonl)
          + v10 redundancy rows of any operation EXCEPT those that duplicate
            a held-test theorem_name or duplicate an exact
            (state_before, tactic) row already in test

    test  = the v8 family_holdout/<fam>/test.jsonl rows verbatim
            (so v11 metrics are *directly comparable* to the v8 matrix)

Crucially the v8 family-LOFO train ALREADY removes every row whose
``family == <fam>`` (including such rows in the v8 base pool — the v8
interpolation train.jsonl contains 7 ``forall_inst`` rows and 16
``rewrite_succ`` rows, which would silently leak if we re-built the base
ourselves). Layering v10 on top of that pool keeps the v8/v11 numbers
apples-to-apples and prevents accidental re-introduction of held-family
rows.

Inline leakage assertions:
  1. no test theorem_name in train
  2. no exact (state_before, tactic) row in train
  3. no row with family==<fam> in train (the held-family planner_blind
     condition that v8's `proof_block_seq2seq_family_holdout_<fam>` enforced)
  4. report whether the same operation, and the same tactic *skeleton*,
     appear in train (descriptive, NOT a leakage condition — the v10
     hypothesis is "same shape via siblings", which requires precisely
     these conditions to hold).

Targets (the brief's primary two + three v8 wins for comparison)::

  forall_inst, rewrite_succ,
  neg_exfalso, exists_reconstruct, neg_imp_exfalso

Output: ``data/processed/proof_blocks_v11_family_lofo/<fam>/{train,test}.jsonl``
plus a manifest with the leakage report. Deterministic; torch-free; no Lean.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.io_utils import read_jsonl  # noqa: E402


DEFAULT_TARGETS = (
    "forall_inst",
    "rewrite_succ",
    "neg_exfalso",
    "exists_reconstruct",
    "neg_imp_exfalso",
)

# Map family-LOFO target -> v10 redundancy *operation* that supplies siblings.
# This is descriptive only; v10 cells of these operations are eligible to land
# in train (subject to the no-(state, tactic)-duplicate guard).
FAM_TO_V10_OP = {
    "forall_inst":        "instantiate_forall",
    "rewrite_succ":       "rewrite_eq",
    "neg_exfalso":        "contradiction",
    "exists_reconstruct": "exists_elim",
    "neg_imp_exfalso":    "contradiction",
}


def _load(p: Path) -> List[dict]:
    if not p.exists():
        return []
    return list(read_jsonl(p))


def _v10_to_pb(r: dict, *, regime: str) -> dict:
    """Convert a v10 next_tactic row to a proof_blocks training row."""
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


_NUM_RE = re.compile(r"(?<![\w.])\d+(?!\w)")


def _tactic_skeleton(t: str) -> str:
    return _NUM_RE.sub("<num>", t)


def build_fam_regime(
    *,
    fam: str,
    v8_lofo_train: List[dict],
    pb_test: List[dict],
    v10_rows: List[dict],
    out_dir: Path,
) -> Dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build the test forbidden set: theorem_names and (state_before, tactic) pairs.
    test_thms: Set[str] = {r["theorem_name"] for r in pb_test}
    test_pairs: Set[Tuple[str, str]] = {
        (r["state_before"], r["tactic"]) for r in pb_test
    }
    test_skeletons: Set[str] = {_tactic_skeleton(r["tactic"]) for r in pb_test}

    # v10 rows: candidate to add, but only if they don't duplicate a test
    # (theorem_name, state_before, tactic) row.
    v10_train_candidate: List[dict] = []
    v10_dropped_by_pair: List[dict] = []
    v10_dropped_by_name: List[dict] = []
    for r in v10_rows:
        pb = _v10_to_pb(r, regime=f"v11_family_lofo/{fam}")
        if pb["theorem_name"] in test_thms:
            v10_dropped_by_name.append(pb)
            continue
        if (pb["state_before"], pb["tactic"]) in test_pairs:
            v10_dropped_by_pair.append(pb)
            continue
        v10_train_candidate.append(pb)

    # Compose final train pool: v8 family-LOFO train (already excludes held
    # family) + v10 redundancy cells that survive the leakage guard.
    train = list(v8_lofo_train) + v10_train_candidate

    # ----- leakage assertions -----
    train_thms = {r["theorem_name"] for r in train}
    leaked_thms = train_thms & test_thms
    assert not leaked_thms, (
        f"v11/{fam} theorem-name leakage: {sorted(leaked_thms)[:5]}"
    )
    train_pairs = {(r["state_before"], r["tactic"]) for r in train}
    leaked_pairs = train_pairs & test_pairs
    assert not leaked_pairs, (
        f"v11/{fam} (state_before, tactic) leakage: {len(leaked_pairs)} pairs"
    )
    # No held-family planner_blind row in train
    bad_pb_in_train = [r for r in train
                       if r.get("corpus_source") == "planner_blind"
                       and r.get("family") == fam]
    assert not bad_pb_in_train, (
        f"v11/{fam} planner_blind rows with family={fam} leaked into train: "
        f"{len(bad_pb_in_train)}"
    )

    # ----- descriptive (not leakage) -----
    held_op = pb_test[0].get("required_operation") if pb_test else "unknown"
    same_op_in_train = sum(1 for r in train
                           if r.get("required_operation") == held_op)
    same_skeleton_in_train = sum(1 for r in train
                                  if _tactic_skeleton(r["tactic"]) in test_skeletons)
    v10_same_op_kept = sum(1 for r in v10_train_candidate
                           if r.get("required_operation") == held_op)

    # ----- write -----
    with (out_dir / "train.jsonl").open("w", encoding="utf-8") as f:
        for r in train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (out_dir / "test.jsonl").open("w", encoding="utf-8") as f:
        for r in pb_test:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    manifest = {
        "regime": f"v11_family_lofo/{fam}",
        "held_family": fam,
        "held_operation": held_op,
        "n_train_rows": len(train),
        "n_test_rows": len(pb_test),
        "n_train_theorems": len(train_thms),
        "n_test_theorems": len(test_thms),
        "v8_lofo_train_rows": len(v8_lofo_train),
        "v10_rows_kept_in_train": len(v10_train_candidate),
        "v10_rows_kept_same_operation_as_held": v10_same_op_kept,
        "v10_rows_dropped_by_theorem_name": len(v10_dropped_by_name),
        "v10_rows_dropped_by_state_tactic_pair": len(v10_dropped_by_pair),
        "descriptive_same_operation_rows_in_train": same_op_in_train,
        "descriptive_same_tactic_skeleton_rows_in_train": same_skeleton_in_train,
        "test_tactic_skeletons": sorted(test_skeletons),
        "leakage_assertions": "passed",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2),
                                           encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--pb-fam-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_family_holdout"))
    ap.add_argument("--v10-corpus",
                    default=str(ROOT / "data" / "processed"
                                / "redundancy_lean_cli" / "next_tactic.jsonl"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v11_family_lofo"))
    ap.add_argument("--targets", nargs="*", default=list(DEFAULT_TARGETS),
                    help="held family names")
    args = ap.parse_args(argv)

    v10_rows = _load(Path(args.v10_corpus))
    pb_fam_root = Path(args.pb_fam_root)
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    print(f"v10 redundancy corpus: {len(v10_rows)} cells")
    print()

    manifests: List[Dict] = []
    for fam in args.targets:
        fold_dir = pb_fam_root / fam
        if not fold_dir.exists():
            print(f"SKIP {fam}: no v8 family_holdout fold at {fold_dir}")
            continue
        v8_lofo_train = _load(fold_dir / "train.jsonl")
        pb_test = _load(fold_dir / "test.jsonl")
        out_dir = out_root / fam
        try:
            m = build_fam_regime(
                fam=fam, v8_lofo_train=v8_lofo_train, pb_test=pb_test,
                v10_rows=v10_rows, out_dir=out_dir,
            )
        except AssertionError as exc:
            print(f"FAIL {fam}: {exc}", file=sys.stderr)
            return 2
        manifests.append(m)
        print(f"  {fam:24s}  v8_lofo_base={len(v8_lofo_train):>4} "
              f"+v10={m['v10_rows_kept_in_train']:>2} "
              f"(same-op={m['v10_rows_kept_same_operation_as_held']:>2}) "
              f"= train {m['n_train_rows']:>4}, test {m['n_test_rows']:>2}")

    (out_root / "manifest.json").write_text(
        json.dumps({"folds": manifests, "n_folds": len(manifests)},
                   indent=2), encoding="utf-8")
    print(f"WROTE {len(manifests)} per-family LOFO regimes -> {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
