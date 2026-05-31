"""Mini-ELF v17 — Part 4: build v17 family-LOFO folds.

Composes per-family train sets as:
  v17 train = v16 train (already includes v11 + v16 contrapositive
                          corpus) + v17 arrow_false_elim corpus.

Test rows are unchanged (still v11 family-LOFO test rows).

Leakage guards (enforced + unit-tested):
  * No v17 corpus row's theorem_name matches a v11 LOFO test name.
  * No exact (statement, state, tactic) triple in train matches the
    held family's test set.
  * v17 corpus rows are tagged ``corpus_source =
    v17_arrow_false_elim_corpus`` and ``regime =
    v17_arrow_false_elim_redundancy``.
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
logger = logging.getLogger("build_v17_family_lofo")


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


def _collect_test_triples(v16_root: Path, fam: str
                          ) -> Set[Tuple[str, str, str]]:
    triples: Set[Tuple[str, str, str]] = set()
    for r in _read_jsonl(v16_root / fam / "test.jsonl"):
        triples.add((
            r.get("theorem_statement", ""),
            r.get("state_before", ""),
            r.get("tactic", ""),
        ))
    return triples


def build_fold(*, fam: str, v16_root: Path, v17_corpus: Path,
               all_v11_test_names: Set[str], out_root: Path,
               ) -> Dict[str, Any]:
    v16_train = _read_jsonl(v16_root / fam / "train.jsonl")
    v16_test = _read_jsonl(v16_root / fam / "test.jsonl")
    v17_rows = _read_jsonl(v17_corpus)

    # Guard 1: drop v17 rows whose theorem_name hits a v11 test name.
    v17_clean = [r for r in v17_rows
                 if r.get("theorem_name") not in all_v11_test_names]
    dropped_by_name = len(v17_rows) - len(v17_clean)

    # Guard 2: drop v17 rows whose triple matches the held family's
    # test set.
    test_triples = _collect_test_triples(v16_root, fam)
    v17_no_triple = []
    dropped_by_triple = 0
    for r in v17_clean:
        key = (r.get("theorem_statement", ""),
               r.get("state_before", ""),
               r.get("tactic", ""))
        if key in test_triples:
            dropped_by_triple += 1
            continue
        v17_no_triple.append(r)

    for r in v17_no_triple:
        r.setdefault("v17_held_family", fam)
        r.setdefault("split", "train")

    combined_train = list(v16_train) + v17_no_triple

    out_fam = out_root / fam
    out_fam.mkdir(parents=True, exist_ok=True)
    _write_jsonl(combined_train, out_fam / "train.jsonl")
    _write_jsonl(v16_test, out_fam / "test.jsonl")

    manifest = {
        "family": fam,
        "n_train_total": len(combined_train),
        "n_train_v16_carry": len(v16_train),
        "n_train_v17_added": len(v17_no_triple),
        "n_test": len(v16_test),
        "v17_dropped_by_name_leakage_guard": dropped_by_name,
        "v17_dropped_by_triple_leakage_guard": dropped_by_triple,
        "uses_state_after": False,
    }
    (out_fam / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v16-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v16_token"))
    ap.add_argument("--v11-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v11_family_lofo"))
    ap.add_argument("--v17-corpus",
                    default=str(ROOT / "data" / "processed"
                                / "v17_arrow_false_elim_corpus"
                                / "train_rows.jsonl"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v17_token"))
    ap.add_argument("--families", nargs="*", default=list(V11_FAMILIES))
    args = ap.parse_args(argv)

    all_test_names = _collect_v11_test_theorem_names(
        Path(args.v11_root), args.families)
    logger.info("v11 test theorem names: %d", len(all_test_names))

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    summary: List[Dict[str, Any]] = []
    for fam in args.families:
        m = build_fold(
            fam=fam, v16_root=Path(args.v16_root),
            v17_corpus=Path(args.v17_corpus),
            all_v11_test_names=all_test_names, out_root=out_root,
        )
        logger.info(
            "FAM %-22s train=%d (v16=%d + v17=%d) test=%d  "
            "guard_drops name=%d triple=%d",
            fam, m["n_train_total"], m["n_train_v16_carry"],
            m["n_train_v17_added"], m["n_test"],
            m["v17_dropped_by_name_leakage_guard"],
            m["v17_dropped_by_triple_leakage_guard"],
        )
        summary.append(m)
    (out_root / "v17_lofo_summary.json").write_text(
        json.dumps({"folds": summary, "uses_state_after": False}, indent=2),
        encoding="utf-8")
    logger.info("V17 FAMILY-LOFO BUILD DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
