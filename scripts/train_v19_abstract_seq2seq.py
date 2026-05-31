"""Mini-ELF v19 — Part 4: train abstract token seq2seq.

Trains a single token-level seq2seq on the v19 abstract synthetic
train set (1111 leakage-guarded rows after dedup). The architecture
is unchanged from v14/v16/v17/v18 (bi-GRU encoder + GRU+attention
decoder, embed 96, hidden 128, beam 10, deterministic seed) — only
the input/target text differs (placeholders instead of names).

This is the **honest experimental control**: same architecture,
same training data shape, just with identifier names replaced by
their placeholders.
"""

from __future__ import annotations

import argparse
import json
import logging
import random as _r
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
from mini_elf_lean.token_seq2seq_dataset import (  # noqa: E402
    TokenVocab, build_input_text,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_v19_abstract_seq2seq")


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--abstract-root",
                    default=str(ROOT / "data" / "processed"
                                / "v19_abstract_synthetic_train"))
    ap.add_argument("--out-dir",
                    default=str(ROOT / "data" / "models"
                                / "token_seq2seq_v19_abstract"))
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--embedding-dim", type=int, default=96)
    ap.add_argument("--hidden-dim", type=int, default=128)
    ap.add_argument("--beam-width", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    train_rows = _read_jsonl(Path(args.abstract_root) / "train.jsonl")
    val_rows = _read_jsonl(Path(args.abstract_root) / "val.jsonl")
    if not train_rows:
        logger.error("no abstract train rows at %s", args.abstract_root)
        return 1
    logger.info("loaded %d abstract train + %d val rows",
                len(train_rows), len(val_rows))

    def _to_example(r: Dict[str, Any], split: str) -> Example:
        return Example(
            theorem_name=r.get("theorem_name", ""),
            theorem_statement="",  # abstract state already carries shape
            state_before=r["state_before_abstract"],
            tactic=r["tactic_abstract"],
            split=split,
        )
    train_examples = [_to_example(r, "train") for r in train_rows]
    val_examples = [_to_example(r, "val") for r in val_rows]

    src_texts = [build_input_text(e.theorem_statement, e.state_before)
                 for e in train_examples + val_examples]
    tactics = [e.tactic for e in train_examples + val_examples]
    vocab = TokenVocab.build(src_texts, tactics)
    logger.info("vocab size: %d (includes placeholder tokens)",
                len(vocab))

    cfg = TokenTrainConfig(
        epochs=args.epochs, batch_size=args.batch_size, lr=args.lr,
        embedding_dim=args.embedding_dim, hidden_dim=args.hidden_dim,
        beam_width=args.beam_width, seed=args.seed,
    )
    art = train_token(
        train_examples, val_examples, vocab, cfg,
        log_fn=lambda r: logger.info(
            "  epoch=%d train_loss=%.4f val_loss=%.4f val_exact=%.4f",
            r["epoch"], r["train_loss"], r["val_loss"],
            r["val_greedy_exact_top1"],
        ) if (r["epoch"] % 2 == 0 or r["epoch"] == cfg.epochs - 1) else None,
    )
    out_dir = Path(args.out_dir)
    save_token_artifacts(out_dir, art, cfg,
                         extra={"corpus": "v19_abstract_synthetic"})
    logger.info("V19 ABSTRACT MODEL DONE; saved to %s", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
