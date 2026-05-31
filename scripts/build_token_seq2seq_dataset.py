"""Mini-ELF v14 — build token-level proof-block datasets.

Reads the same v11 family-LOFO folds the char-level seq2seq trains on
(``data/processed/proof_blocks_v11_family_lofo/<fam>/{train,test}.jsonl``)
and writes a parallel token-level tree at
``data/processed/proof_blocks_v14_token/<fam>/`` containing:

  * ``train.jsonl``  — one TokenizedRow per train row
  * ``test.jsonl``   — one TokenizedRow per test row
  * ``vocab.json``   — TokenVocab built from train rows only
  * ``stats.json``   — FoldStats for the trainer / report

Per the v14 honesty contract, **no v11 file is overwritten**, no v10
metrics are touched, and there is no ``state_after`` anywhere in the
pipeline.
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

from mini_elf_lean.token_seq2seq_dataset import (  # noqa: E402
    build_fold, read_jsonl, write_jsonl,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_token_seq2seq_dataset")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--src-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v11_family_lofo"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v14_token"))
    ap.add_argument("--families", nargs="*",
                    default=["forall_inst", "rewrite_succ", "neg_exfalso",
                             "exists_reconstruct", "neg_imp_exfalso"])
    args = ap.parse_args(argv)

    src_root = Path(args.src_root)
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    all_stats = []
    for fam in args.families:
        fold_dir = src_root / fam
        train_p = fold_dir / "train.jsonl"
        test_p = fold_dir / "test.jsonl"
        if not (train_p.exists() and test_p.exists()):
            logger.warning("SKIP %s (missing %s or %s)", fam, train_p, test_p)
            continue
        train_rows = read_jsonl(train_p)
        test_rows = read_jsonl(test_p)
        logger.info("FAM %s n_train=%d n_test=%d",
                    fam, len(train_rows), len(test_rows))

        vocab, tr, te, stats = build_fold(
            family=fam, train_rows=train_rows, test_rows=test_rows,
        )
        out_fam = out_root / fam
        out_fam.mkdir(parents=True, exist_ok=True)
        write_jsonl(tr, out_fam / "train.jsonl")
        write_jsonl(te, out_fam / "test.jsonl")
        vocab.save(out_fam / "vocab.json")
        (out_fam / "stats.json").write_text(
            json.dumps(stats.to_jsonable(), indent=2), encoding="utf-8")
        all_stats.append(stats.to_jsonable())
        logger.info("  vocab=%d train_lossless=%d/%d test_lossless=%d/%d "
                    "train_tac_unique=%d test_tac_unique=%d",
                    stats.vocab_size,
                    stats.n_train_lossless, stats.n_train,
                    stats.n_test_lossless, stats.n_test,
                    stats.train_tactic_unique, stats.test_tactic_unique)

    (out_root / "summary.json").write_text(
        json.dumps({"folds": all_stats}, indent=2), encoding="utf-8")
    logger.info("V14 TOKEN DATASET BUILD DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
