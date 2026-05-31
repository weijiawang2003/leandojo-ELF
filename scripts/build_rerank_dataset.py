"""Mini-ELF v15 — build the candidate-outcome dataset for the learned reranker.

Walks v12 / v14 predictions + v13 / v14 timeout reruns and writes
``data/processed/v15_rerank_dataset/all_candidates.jsonl`` plus a
``stats.json`` summary.

Honest scope: every candidate has a Lean-verified label (cached or
re-run); no synthetic positives, no manual oracle, no state_after.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.rerank_dataset import (  # noqa: E402
    build_candidate_outcome_dataset, compute_stats, write_rows,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_rerank_dataset")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--fold-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v11_family_lofo"))
    ap.add_argument("--v12-root",
                    default=str(ROOT / "data" / "baselines" / "v12_eval"))
    ap.add_argument("--v14-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v14_token_seq2seq"))
    ap.add_argument("--v13-rerun-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v13_timeout_rerun"))
    ap.add_argument("--v14-rerun-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v14_timeout_rerun"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "processed"
                                / "v15_rerank_dataset"))
    ap.add_argument("--families", nargs="*",
                    default=["forall_inst", "rewrite_succ", "neg_exfalso",
                             "exists_reconstruct", "neg_imp_exfalso"])
    args = ap.parse_args(argv)

    rows = build_candidate_outcome_dataset(
        fold_root=Path(args.fold_root),
        v12_root=Path(args.v12_root),
        v14_root=Path(args.v14_root),
        v13_rerun_root=Path(args.v13_rerun_root),
        v14_rerun_root=Path(args.v14_rerun_root),
        families=args.families,
    )
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    write_rows(rows, out_root / "all_candidates.jsonl")

    stats = compute_stats(rows)
    (out_root / "stats.json").write_text(
        json.dumps(stats.to_jsonable(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("wrote %d candidate rows; verified=%d (%.1f%%) failed=%d",
                stats.n_total, stats.n_verified,
                100.0 * stats.positive_fraction, stats.n_failed)
    for fam, d in sorted(stats.by_family.items()):
        logger.info("  fam=%-22s n=%4d verified=%3d", fam, d["n"], d["verified"])
    for src, d in sorted(stats.by_source_run.items()):
        logger.info("  run=%-30s n=%4d verified=%3d", src, d["n"], d["verified"])
    logger.info("error classes: %s", stats.by_error_class)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
