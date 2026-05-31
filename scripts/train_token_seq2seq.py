"""Mini-ELF v14 — train a token-level seq2seq per family-LOFO fold.

Reads the token-tokenised folds at
``data/processed/proof_blocks_v14_token/<fam>/`` (built by
``scripts/build_token_seq2seq_dataset.py``) and writes one trained
model per family at
``data/models/token_seq2seq_v14/<fam>/{model.pt, vocab.json,
config.json, summary.json, train_log.jsonl}``.

The train/val split is taken from the proof_blocks train.jsonl rows
themselves (rows where ``split == 'val'``); per-family-LOFO folds
typically have no separate val rows, so by default the script slices
the last 10% of train as val for checkpoint selection. Use
``--no-val-slice`` to disable that and select by last-epoch instead.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baselines import Example  # noqa: E402
from mini_elf_lean.token_seq2seq import (  # noqa: E402
    TokenTrainConfig, save_token_artifacts, train_token,
)
from mini_elf_lean.token_seq2seq_dataset import TokenVocab, read_jsonl  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_token_seq2seq")


def rows_to_examples(rows: Sequence[dict]) -> List[Example]:
    out: List[Example] = []
    for r in rows:
        out.append(Example(
            theorem_name=r.get("theorem_name", ""),
            theorem_statement=r.get("theorem_statement", ""),
            state_before=r.get("state_before", ""),
            tactic=r.get("original_tactic") or r.get("tactic", ""),
            split=r.get("split", "train"),
        ))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--token-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v14_token"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "models" / "token_seq2seq_v14"))
    ap.add_argument("--families", nargs="*",
                    default=["forall_inst", "rewrite_succ"],
                    help="Which folds to train (default: forall_inst + "
                         "rewrite_succ — the headline-relevant ones).")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--embedding-dim", type=int, default=96)
    ap.add_argument("--hidden-dim", type=int, default=128)
    ap.add_argument("--beam-width", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--val-fraction", type=float, default=0.10,
                    help="Fraction of train rows to hold out as val for "
                         "checkpoint selection (default 0.10).")
    ap.add_argument("--no-val-slice", dest="val_slice", action="store_false")
    ap.set_defaults(val_slice=True)
    args = ap.parse_args(argv)

    token_root = Path(args.token_root)
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    for fam in args.families:
        fam_dir = token_root / fam
        if not (fam_dir / "train.jsonl").exists():
            logger.warning("SKIP %s (no train.jsonl)", fam)
            continue
        train_rows = read_jsonl(fam_dir / "train.jsonl")
        vocab = TokenVocab.load(fam_dir / "vocab.json")

        all_examples = rows_to_examples(train_rows)
        if args.val_slice and len(all_examples) >= 10:
            import random as _r
            rng = _r.Random(args.seed)
            shuffled = list(range(len(all_examples)))
            rng.shuffle(shuffled)
            n_val = max(1, int(len(all_examples) * args.val_fraction))
            val_idx = set(shuffled[:n_val])
            train_examples = [e for i, e in enumerate(all_examples)
                              if i not in val_idx]
            val_examples = [e for i, e in enumerate(all_examples)
                            if i in val_idx]
        else:
            train_examples = all_examples
            val_examples = []
        logger.info("FAM %s  vocab=%d  train=%d  val=%d  epochs=%d",
                    fam, len(vocab), len(train_examples),
                    len(val_examples), args.epochs)

        cfg = TokenTrainConfig(
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            embedding_dim=args.embedding_dim,
            hidden_dim=args.hidden_dim,
            beam_width=args.beam_width,
            seed=args.seed,
        )
        art = train_token(
            train_examples, val_examples, vocab, cfg,
            log_fn=lambda r: logger.info(
                "  epoch=%d train_loss=%.4f val_loss=%.4f val_exact=%.4f",
                r["epoch"], r["train_loss"], r["val_loss"],
                r["val_greedy_exact_top1"],
            ) if (r["epoch"] % 5 == 0 or r["epoch"] == cfg.epochs - 1) else None,
        )
        out_fam = out_root / fam
        save_token_artifacts(out_fam, art, cfg, extra={"family": fam})
        logger.info("  %s saved: params=%d best_epoch=%d val_exact=%.4f",
                    fam, art.summary["n_parameters"], art.summary["best_epoch"],
                    art.val_metrics.get("val_greedy_exact_top1",
                                        art.val_metrics.get("n_examples", -1)))

    logger.info("V14 TOKEN TRAIN DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
