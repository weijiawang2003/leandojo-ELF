"""Mini-ELF v16 — Part 3: build v16 family-LOFO folds.

For each of the 5 v11 LOFO families we produce a fresh
``data/processed/proof_blocks_v16_token/<fam>/{train,test}.jsonl``:

  * **train** = (v11 LOFO train.jsonl for this fam) + (v16
    contrapositive corpus train rows). The v11 train was already
    family-LOFO-clean. The v16 corpus uses disjoint variable names
    and a separate ``surface_family`` so it is structurally distinct
    from the v11 LOFO test theorems.

  * **test** = unchanged v11 LOFO test.jsonl for this fam — so
    pass@k metrics are directly comparable to v14/v15.

Leakage guards (enforced at build time and unit-tested):

  1. No row in v16 train shares a ``theorem_name`` with any v11 LOFO
     test row across any family.
  2. No row in v16 train shares an *exact* ``(theorem_statement,
     state_before, tactic)`` triple with the held family's test set.
  3. The v16 corpus rows are clearly tagged
     (``corpus_source == "v16_contrapositive_corpus"``).

Outputs also include a ``manifest.json`` per fold documenting the
counts + a top-level ``v16_lofo_summary.json``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_v16_family_lofo")


V11_FAMILIES = ("forall_inst", "rewrite_succ", "neg_exfalso",
                "exists_reconstruct", "neg_imp_exfalso")


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def _write_jsonl(rows: Sequence[Dict[str, Any]], p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _collect_v11_test_theorem_names(v11_root: Path,
                                    families: Sequence[str]) -> Set[str]:
    names: Set[str] = set()
    for fam in families:
        for r in _read_jsonl(v11_root / fam / "test.jsonl"):
            nm = r.get("theorem_name")
            if nm:
                names.add(nm)
    return names


def _collect_v11_test_triples(v11_root: Path, fam: str
                              ) -> Set[Tuple[str, str, str]]:
    triples: Set[Tuple[str, str, str]] = set()
    for r in _read_jsonl(v11_root / fam / "test.jsonl"):
        triples.add((
            r.get("theorem_statement", ""),
            r.get("state_before", ""),
            r.get("tactic", ""),
        ))
    return triples


def build_fold(*, fam: str, v11_root: Path, v16_corpus: Path,
               all_v11_test_names: Set[str], out_root: Path,
               ) -> Dict[str, Any]:
    v11_train = _read_jsonl(v11_root / fam / "train.jsonl")
    v11_test = _read_jsonl(v11_root / fam / "test.jsonl")
    v16_rows = _read_jsonl(v16_corpus)

    # Leakage guard 1: drop any v16 row whose theorem_name matches a
    # v11 test theorem name (across any family). v16 corpus uses
    # disjoint names by construction, but we enforce.
    v16_clean: List[Dict[str, Any]] = []
    v16_dropped_by_name = 0
    for r in v16_rows:
        if r.get("theorem_name") in all_v11_test_names:
            v16_dropped_by_name += 1
            continue
        v16_clean.append(r)

    # Leakage guard 2: drop any v16 row whose (statement, state, tactic)
    # exactly matches the held family's test set.
    test_triples = _collect_v11_test_triples(v11_root, fam)
    v16_no_triple_leak: List[Dict[str, Any]] = []
    v16_dropped_by_triple = 0
    for r in v16_clean:
        key = (r.get("theorem_statement", ""),
               r.get("state_before", ""),
               r.get("tactic", ""))
        if key in test_triples:
            v16_dropped_by_triple += 1
            continue
        v16_no_triple_leak.append(r)

    # Tag every v16 row with the held family for downstream audit.
    for r in v16_no_triple_leak:
        r.setdefault("v16_held_family", fam)
        r.setdefault("split", "train")

    # Compose train.
    combined_train = list(v11_train) + v16_no_triple_leak

    # Sanity: combined_train must not contain any test theorem name.
    n_train_with_test_name = sum(
        1 for r in combined_train
        if r.get("theorem_name") in all_v11_test_names
        and r.get("corpus_source") == "v16_contrapositive_corpus"
    )
    assert n_train_with_test_name == 0, (
        f"v16 train leakage: {n_train_with_test_name} v16 rows carry "
        f"a v11 LOFO test theorem name"
    )

    out_fam = out_root / fam
    out_fam.mkdir(parents=True, exist_ok=True)
    _write_jsonl(combined_train, out_fam / "train.jsonl")
    _write_jsonl(v11_test, out_fam / "test.jsonl")

    manifest = {
        "family": fam,
        "n_train_total": len(combined_train),
        "n_train_v11": len(v11_train),
        "n_train_v16_contrapositive": len(v16_no_triple_leak),
        "n_test": len(v11_test),
        "v16_dropped_by_name_leakage_guard": v16_dropped_by_name,
        "v16_dropped_by_triple_leakage_guard": v16_dropped_by_triple,
        "uses_state_after": False,
    }
    (out_fam / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v11-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v11_family_lofo"))
    ap.add_argument("--v16-corpus",
                    default=str(ROOT / "data" / "processed"
                                / "v16_contrapositive_corpus"
                                / "train_rows.jsonl"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v16_token"))
    ap.add_argument("--families", nargs="*", default=list(V11_FAMILIES))
    args = ap.parse_args(argv)

    all_test_names = _collect_v11_test_theorem_names(
        Path(args.v11_root), args.families)
    logger.info("v11 test theorem names across all families: %d",
                len(all_test_names))

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    summary: List[Dict[str, Any]] = []
    for fam in args.families:
        m = build_fold(
            fam=fam,
            v11_root=Path(args.v11_root),
            v16_corpus=Path(args.v16_corpus),
            all_v11_test_names=all_test_names,
            out_root=out_root,
        )
        logger.info(
            "FAM %-22s train=%d (v11=%d + v16=%d) test=%d  "
            "leakage_guard dropped_by_name=%d dropped_by_triple=%d",
            fam, m["n_train_total"], m["n_train_v11"],
            m["n_train_v16_contrapositive"], m["n_test"],
            m["v16_dropped_by_name_leakage_guard"],
            m["v16_dropped_by_triple_leakage_guard"],
        )
        summary.append(m)
    (out_root / "v16_lofo_summary.json").write_text(
        json.dumps({"folds": summary,
                    "uses_state_after": False}, indent=2),
        encoding="utf-8",
    )
    logger.info("V16 FAMILY-LOFO BUILD DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
