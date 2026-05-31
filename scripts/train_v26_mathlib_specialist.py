"""Mini-ELF v26 — Part 5: train a Mathlib specialist token seq2seq.

Same architecture as v14/v18/v20/v24 (bi-GRU + additive attention, token-level
tokeniser, deterministic seed 0). The specialist trains **only on Mathlib-tier
rows** (config A) or Mathlib-tier rows + a small curated v18 core subset
(config B) — never the full v24 broad-core corpus. The v24 broad-core model is
left untouched; v26 delivers Mathlib via this specialist + a router.

Configs:
  A  base        --train-rows theorem_holdout/train_rows.jsonl
  B  plus_core   --train-rows theorem_holdout/train_rows_plus_core.jsonl
  C  large       (A or B rows) with --embedding-dim 128 --hidden-dim 192

Vocabulary is built from the **train rows only**; val rows are used purely for
checkpoint selection (val-OOV → <unk>). No state_after; no manual oracle.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baselines import Example  # noqa: E402
from mini_elf_lean.token_seq2seq import (  # noqa: E402
    TokenTrainConfig, save_token_artifacts, train_token,
)
from mini_elf_lean.token_seq2seq_dataset import TokenVocab, build_input_text  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_v26_mathlib_specialist")


def _read(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def _examples(rows: List[Dict[str, Any]]) -> List[Example]:
    return [Example(theorem_name=r.get("theorem_name", ""),
                    theorem_statement=r.get("theorem_statement", ""),
                    state_before=r.get("state_before", ""),
                    tactic=r.get("tactic", ""), split="train") for r in rows]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--train-rows", required=True)
    ap.add_argument("--val-rows", default=None, help="explicit val rows; else slice from train")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--label", default="v26_mathlib_specialist")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--embedding-dim", type=int, default=96)
    ap.add_argument("--hidden-dim", type=int, default=128)
    ap.add_argument("--beam-width", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--val-fraction", type=float, default=0.12)
    args = ap.parse_args(argv)

    rows = _read(Path(args.train_rows))
    if not rows:
        logger.error("no training rows at %s", args.train_rows)
        return 1

    src_texts = [build_input_text(r.get("theorem_statement", ""), r.get("state_before", "")) for r in rows]
    tactics = [r.get("tactic", "") for r in rows]
    vocab = TokenVocab.build(src_texts, tactics)
    train_examples = _examples(rows)

    if args.val_rows:
        val_examples = _examples(_read(Path(args.val_rows)))
        logger.info("using explicit val rows: %d", len(val_examples))
    else:
        rng = random.Random(args.seed)
        idx = list(range(len(train_examples)))
        rng.shuffle(idx)
        n_val = max(8, int(len(train_examples) * args.val_fraction))
        val_set = set(idx[:n_val])
        val_examples = [e for i, e in enumerate(train_examples) if i in val_set]
        train_examples = [e for i, e in enumerate(train_examples) if i not in val_set]

    logger.info("label=%s vocab=%d train=%d val=%d epochs=%d embed=%d hidden=%d",
                args.label, len(vocab), len(train_examples), len(val_examples),
                args.epochs, args.embedding_dim, args.hidden_dim)

    cfg = TokenTrainConfig(epochs=args.epochs, batch_size=args.batch_size, lr=args.lr,
                           embedding_dim=args.embedding_dim, hidden_dim=args.hidden_dim,
                           beam_width=args.beam_width, seed=args.seed)
    art = train_token(
        train_examples, val_examples, vocab, cfg,
        log_fn=lambda r: logger.info("  epoch=%d train_loss=%.4f val_loss=%.4f val_exact=%.4f",
                                     r["epoch"], r["train_loss"], r["val_loss"],
                                     r["val_greedy_exact_top1"])
        if (r["epoch"] % 5 == 0 or r["epoch"] == cfg.epochs - 1) else None,
    )
    out_dir = Path(args.out_dir)
    save_token_artifacts(out_dir, art, cfg, extra={"corpus": args.label,
                                                   "train_rows": args.train_rows,
                                                   "val_rows": args.val_rows})
    logger.info("V26 SPECIALIST '%s' DONE: params=%d best_epoch=%d val_exact=%.4f -> %s",
                args.label, art.summary["n_parameters"], art.summary["best_epoch"],
                art.val_metrics.get("val_greedy_exact_top1", -1), out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
