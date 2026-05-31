"""Mini-ELF v19 — Part 3: build the abstracted training dataset.

For each clean synthetic verified train row we:
  1. Parse the ``state_before`` into a local context.
  2. Build a placeholder map (per-category counters).
  3. Replace local identifier names in both the ``state_before``
     and the gold ``tactic`` with placeholders.
  4. Round-trip sanity check: concretising the abstract tactic back
     against the *original* state must yield the original tactic.
     Drop rows that don't (rare; arises if a placeholder collides
     with a Lean keyword).
  5. Persist the (original, abstract) pair + the map.

The brief calls for two regimes:
  * **zero-shot synthetic abstract train** → v18 test (default).
  * **v18 train/test abstract split** (optional in-domain) —
    written here too so a future v19 fine-tune has clean inputs.

Outputs:
  ``data/processed/v19_abstract_synthetic_train/``
    train.jsonl  — abstracted (state, tactic) pairs from
                   v11+v16+v17 (deduplicated, v18 leakage-guarded).
    val.jsonl    — 8 % slice for trainer checkpoint selection.
    summary.json — counts + drop reasons.
  ``data/processed/v19_abstract_v18_split/``
    train.jsonl / val.jsonl / test.jsonl — same as
    ``data/processed/v18_broad_core/{train,val,test}.jsonl`` but
    abstracted. Carries the placeholder map per-row so the eval
    pipeline can reverse it.

Honesty contract:
  * No ``state_after`` anywhere.
  * No manual oracle: abstract tactics are derived purely from
    ``state_before`` + the original verified tactic.
  * Leakage guard: every row whose ``theorem_name`` or
    ``(statement, state, tactic)`` triple appears in the v18 corpus
    is dropped from the *synthetic* train set (and reported).
  * Reconstruct sanity: abstract → concretise round-trip checked
    per row; mismatches dropped + logged.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.identifier_abstraction import (  # noqa: E402
    abstract_state, concretise_or_fail,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_v19_abstract_dataset")


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


def _collect_v18_names_and_triples(
    v18_root: Path,
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


def _abstract_row(row: Dict[str, Any]
                  ) -> Tuple[Dict[str, Any], str]:
    """Returns (abstracted_row, drop_reason). drop_reason is ``ok``
    on success or a short class label on failure."""
    state = row.get("state_before", "")
    tactic = row.get("tactic", "")
    if not state or not tactic:
        return {}, "empty_state_or_tactic"
    try:
        abs_state, abs_tactic, am = abstract_state(state, tactic)
    except Exception as exc:  # noqa: BLE001
        return {}, f"abstract_exception:{exc}"
    # Round-trip sanity: abstract → concretise (against original
    # state) must reproduce the original tactic.
    reconstructed, reason = concretise_or_fail(abs_tactic, state)
    if reason not in ("ok", "no_placeholders"):
        return {}, f"reconstruct_failed:{reason}"
    # 'no_placeholders' means the tactic didn't reference any
    # local identifier — that's fine; carry the row anyway.
    if reason == "ok" and reconstructed != tactic:
        return {}, "reconstruct_mismatch"
    return {
        "theorem_name": row.get("theorem_name", ""),
        "theorem_statement_original": row.get("theorem_statement", ""),
        "state_before_original": state,
        "tactic_original": tactic,
        "state_before_abstract": abs_state,
        "tactic_abstract": abs_tactic,
        "placeholder_map_original_to_abstract": dict(am.name_to_ph),
        "placeholder_map_abstract_to_original": dict(am.ph_to_name),
        "family": row.get("family"),
        "required_operation": row.get("required_operation"),
        "category": row.get("category"),
        "split": row.get("split", "train"),
        "corpus_source": row.get("corpus_source"),
        "regime": row.get("regime"),
    }, "ok"


def _write_jsonl(rows: Sequence[Dict[str, Any]], p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def build_synthetic(
    *, v11_root: Path, v16_corpus: Path, v17_corpus: Path,
    v18_root: Path, out_root: Path, seed: int = 0,
    val_fraction: float = 0.08,
) -> Dict[str, Any]:
    """Walk v11/v16/v17 verified rows, abstract each, drop leakage."""
    names_v18, triples_v18 = _collect_v18_names_and_triples(v18_root)

    rows_raw: List[Dict[str, Any]] = []
    sources_seen: Dict[str, int] = {}
    # v11 LOFO trains across 5 families — same canonical sources
    for fam_dir in (v11_root).iterdir():
        if not fam_dir.is_dir():
            continue
        for r in _read_jsonl(fam_dir / "train.jsonl"):
            r.setdefault("corpus_source", "v11_lofo")
            rows_raw.append(r)
            sources_seen["v11_lofo"] = sources_seen.get("v11_lofo", 0) + 1
    # v16 / v17 corpus rows are stored as a flat list each
    for r in _read_jsonl(v16_corpus):
        r.setdefault("corpus_source", "v16_contrapositive_corpus")
        rows_raw.append(r)
        sources_seen["v16"] = sources_seen.get("v16", 0) + 1
    for r in _read_jsonl(v17_corpus):
        r.setdefault("corpus_source", "v17_arrow_false_elim_corpus")
        rows_raw.append(r)
        sources_seen["v17"] = sources_seen.get("v17", 0) + 1

    stats = {
        "n_raw_total": len(rows_raw),
        "n_dropped_v18_name_leakage": 0,
        "n_dropped_v18_triple_leakage": 0,
        "n_dropped_dedup": 0,
        "n_dropped_abstract_or_reconstruct": 0,
        "drop_reasons": {},
        "sources_seen_raw": sources_seen,
    }
    rows_clean: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str, str]] = set()
    for r in rows_raw:
        nm = r.get("theorem_name", "")
        triple = (r.get("theorem_statement", ""),
                  r.get("state_before", ""), r.get("tactic", ""))
        if nm in names_v18:
            stats["n_dropped_v18_name_leakage"] += 1
            continue
        if triple in triples_v18:
            stats["n_dropped_v18_triple_leakage"] += 1
            continue
        if triple in seen:
            stats["n_dropped_dedup"] += 1
            continue
        seen.add(triple)
        absr, reason = _abstract_row(r)
        if reason != "ok":
            stats["n_dropped_abstract_or_reconstruct"] += 1
            stats["drop_reasons"][reason] = (
                stats["drop_reasons"].get(reason, 0) + 1)
            continue
        rows_clean.append(absr)

    rng = random.Random(seed)
    indices = list(range(len(rows_clean)))
    rng.shuffle(indices)
    n_val = max(20, int(len(rows_clean) * val_fraction))
    val_idx = set(indices[:n_val])
    train_rows = [rows_clean[i] for i in range(len(rows_clean))
                  if i not in val_idx]
    val_rows = [rows_clean[i] for i in range(len(rows_clean))
                if i in val_idx]

    out_dir = out_root
    _write_jsonl(train_rows, out_dir / "train.jsonl")
    _write_jsonl(val_rows, out_dir / "val.jsonl")
    stats["n_train_rows"] = len(train_rows)
    stats["n_val_rows"] = len(val_rows)
    stats["n_clean_total"] = len(rows_clean)
    stats["uses_state_after"] = False
    (out_dir / "summary.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    return stats


def build_v18_split(
    *, v18_root: Path, out_root: Path,
) -> Dict[str, Any]:
    """Abstract the existing v18 train/val/test verified rows."""
    counts: Dict[str, int] = {}
    drops: Dict[str, int] = {}
    for split in ("train", "val", "test"):
        rows_raw = _read_jsonl(v18_root / f"{split}.jsonl")
        rows_clean: List[Dict[str, Any]] = []
        for r in rows_raw:
            absr, reason = _abstract_row(r)
            if reason != "ok":
                drops[reason] = drops.get(reason, 0) + 1
                continue
            rows_clean.append(absr)
        _write_jsonl(rows_clean, out_root / f"{split}.jsonl")
        counts[split] = len(rows_clean)
    summary = {"counts": counts, "drops": drops,
               "uses_state_after": False}
    (out_root / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    return summary


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
    ap.add_argument("--v17-corpus",
                    default=str(ROOT / "data" / "processed"
                                / "v17_arrow_false_elim_corpus"
                                / "train_rows.jsonl"))
    ap.add_argument("--v18-root",
                    default=str(ROOT / "data" / "processed"
                                / "v18_broad_core"))
    ap.add_argument("--out-synthetic",
                    default=str(ROOT / "data" / "processed"
                                / "v19_abstract_synthetic_train"))
    ap.add_argument("--out-v18-split",
                    default=str(ROOT / "data" / "processed"
                                / "v19_abstract_v18_split"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--val-fraction", type=float, default=0.08)
    args = ap.parse_args(argv)

    syn_stats = build_synthetic(
        v11_root=Path(args.v11_root),
        v16_corpus=Path(args.v16_corpus),
        v17_corpus=Path(args.v17_corpus),
        v18_root=Path(args.v18_root),
        out_root=Path(args.out_synthetic),
        seed=args.seed, val_fraction=args.val_fraction,
    )
    logger.info("synthetic: raw=%d clean=%d train=%d val=%d "
                "dropped(leak/dedup/abstract)=%d/%d/%d",
                syn_stats["n_raw_total"], syn_stats["n_clean_total"],
                syn_stats["n_train_rows"], syn_stats["n_val_rows"],
                syn_stats["n_dropped_v18_name_leakage"]
                + syn_stats["n_dropped_v18_triple_leakage"],
                syn_stats["n_dropped_dedup"],
                syn_stats["n_dropped_abstract_or_reconstruct"])
    if syn_stats["drop_reasons"]:
        logger.info("synthetic drop reasons: %s",
                    syn_stats["drop_reasons"])

    v18_stats = build_v18_split(
        v18_root=Path(args.v18_root),
        out_root=Path(args.out_v18_split),
    )
    logger.info("v18 abstract split: %s drops=%s",
                v18_stats["counts"], v18_stats["drops"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
