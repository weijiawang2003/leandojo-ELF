"""Mini-ELF v20 — Part 4: build the v20 broad-synthetic-plus
training set.

Union sources (mirrors the v18 broad gather + the two new v20
corpora):
  * v11 LOFO per-family train rows (one canonical copy)
  * v16 contrapositive corpus
  * v17 arrow_false_elim corpus
  * **v20 implication corpus** (new)
  * **v20 bool corpus** (new)

Leakage guards:
  * No v18 broad-core ``theorem_name`` in train.
  * No (theorem_statement, state_before, tactic) triple overlap with
    v18 broad-core eval rows.
  * v20 corpus rows tagged ``corpus_source`` so audit can split.

Output:
  ``data/processed/v20_broad_synthetic_plus/train_rows.jsonl``
  ``data/processed/v20_broad_synthetic_plus/summary.json``
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_v20_broad_training")


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


def _v18_leakage_sets(v18_root: Path
                      ) -> Tuple[Set[str], Set[Tuple[str, str, str]]]:
    names: Set[str] = set()
    triples: Set[Tuple[str, str, str]] = set()
    for fname in ("train.jsonl", "val.jsonl", "test.jsonl"):
        for r in _read_jsonl(v18_root / fname):
            if r.get("theorem_name"):
                names.add(r["theorem_name"])
            triples.add((r.get("theorem_statement", ""),
                         r.get("state_before", ""),
                         r.get("tactic", "")))
    return names, triples


def _ingest(rows: List[Dict[str, Any]], stats: Dict[str, int],
            v18_names: Set[str],
            v18_triples: Set[Tuple[str, str, str]],
            *, source_label: str,
            seen: Set[Tuple[str, str]]) -> List[Dict[str, Any]]:
    """Walk a list of candidate rows, drop those that leak into v18 or
    that duplicate a (theorem_name, tactic) pair already in ``seen``.
    Tags each kept row with ``corpus_source = source_label`` if not
    already set."""
    kept: List[Dict[str, Any]] = []
    for r in rows:
        stats[f"n_{source_label}"] += 1
        nm = r.get("theorem_name", "")
        triple = (r.get("theorem_statement", ""),
                  r.get("state_before", ""),
                  r.get("tactic", ""))
        if nm in v18_names:
            stats["dropped_by_v18_name_guard"] += 1
            continue
        if triple in v18_triples:
            stats["dropped_by_v18_triple_guard"] += 1
            continue
        k = (nm, r.get("tactic", ""))
        if k in seen:
            stats["dropped_by_dedup"] += 1
            continue
        seen.add(k)
        out = dict(r)
        if "corpus_source" not in out:
            out["corpus_source"] = source_label
        kept.append(out)
    return kept


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v18-root",
                    default=str(ROOT / "data" / "processed"
                                / "v18_broad_core"))
    ap.add_argument("--v11-lofo-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v11_family_lofo"))
    ap.add_argument("--v16-corpus",
                    default=str(ROOT / "data" / "processed"
                                / "v16_contrapositive_corpus"
                                / "train_rows.jsonl"))
    ap.add_argument("--v17-corpus",
                    default=str(ROOT / "data" / "processed"
                                / "v17_arrow_false_elim_corpus"
                                / "train_rows.jsonl"))
    ap.add_argument("--v20-implication-corpus",
                    default=str(ROOT / "data" / "processed"
                                / "v20_implication_corpus"
                                / "train_rows.jsonl"))
    ap.add_argument("--v20-bool-corpus",
                    default=str(ROOT / "data" / "processed"
                                / "v20_bool_corpus"
                                / "train_rows.jsonl"))
    ap.add_argument("--out-dir",
                    default=str(ROOT / "data" / "processed"
                                / "v20_broad_synthetic_plus"))
    args = ap.parse_args(argv)

    v18_root = Path(args.v18_root)
    v18_names, v18_triples = _v18_leakage_sets(v18_root)
    logger.info("v18 leakage sets: %d names, %d triples",
                len(v18_names), len(v18_triples))

    stats: Dict[str, int] = {
        "n_v11_lofo": 0, "n_v16_corpus": 0, "n_v17_corpus": 0,
        "n_v20_implication": 0, "n_v20_bool": 0,
        "dropped_by_v18_name_guard": 0,
        "dropped_by_v18_triple_guard": 0,
        "dropped_by_dedup": 0,
    }
    seen: Set[Tuple[str, str]] = set()
    rows: List[Dict[str, Any]] = []

    v11_root = Path(args.v11_lofo_root)
    if v11_root.exists():
        for fam_dir in v11_root.iterdir():
            if fam_dir.is_dir():
                rows.extend(_ingest(_read_jsonl(fam_dir / "train.jsonl"),
                                    stats, v18_names, v18_triples,
                                    source_label="v11_lofo",
                                    seen=seen))
    rows.extend(_ingest(_read_jsonl(Path(args.v16_corpus)),
                        stats, v18_names, v18_triples,
                        source_label="v16_corpus", seen=seen))
    rows.extend(_ingest(_read_jsonl(Path(args.v17_corpus)),
                        stats, v18_names, v18_triples,
                        source_label="v17_corpus", seen=seen))
    rows.extend(_ingest(_read_jsonl(Path(args.v20_implication_corpus)),
                        stats, v18_names, v18_triples,
                        source_label="v20_implication", seen=seen))
    rows.extend(_ingest(_read_jsonl(Path(args.v20_bool_corpus)),
                        stats, v18_names, v18_triples,
                        source_label="v20_bool", seen=seen))

    # Per-corpus tally on kept rows
    by_source = {}
    for r in rows:
        by_source[r["corpus_source"]] = by_source.get(r["corpus_source"], 0) + 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "train_rows.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {
        "n_total_kept": len(rows),
        "ingest_stats": stats,
        "rows_by_corpus_source": by_source,
        "v18_leakage_universe": {
            "n_v18_names": len(v18_names),
            "n_v18_triples": len(v18_triples),
        },
        "uses_state_after": False,
        "uses_manual_oracle": False,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8")
    logger.info("v20 broad-plus train set: %d rows", len(rows))
    for k, v in stats.items():
        logger.info("  %s = %d", k, v)
    logger.info("by corpus source: %s", by_source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
