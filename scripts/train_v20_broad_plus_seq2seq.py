"""Mini-ELF v20 — Part 5: train a raw-name token seq2seq on the
v20 broad-synthetic-plus pool (v18 broad base + v20 implication +
v20 bool).

**Raw names** — NOT generation-time placeholders. v19 confirmed the
placeholder generation path collapses on transfer. v20 returns to
the v18 raw-name regime and tests whether the added shape corpora
move implication and bool off 0.000.

Same architecture as v14/v17/v18: bi-GRU + additive attention,
token-level tokeniser, 96 embed / 128 hidden, beam 10, deterministic
seed 0.

Honesty:
  * v18 leakage guards already baked into the build_v20_broad_training
    step.
  * No state_after consumed during training (the tokeniser only sees
    theorem_statement + state_before).
  * No manual oracle.
"""

from __future__ import annotations

import argparse
import json
import logging
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
logger = logging.getLogger("train_v20_broad_plus_seq2seq")


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
    ap.add_argument("--train-rows",
                    default=str(ROOT / "data" / "processed"
                                / "v20_broad_synthetic_plus"
                                / "train_rows.jsonl"))
    ap.add_argument("--out-dir",
                    default=str(ROOT / "data" / "models"
                                / "token_seq2seq_v20_broad_plus"))
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--embedding-dim", type=int, default=96)
    ap.add_argument("--hidden-dim", type=int, default=128)
    ap.add_argument("--beam-width", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--val-fraction", type=float, default=0.08)
    args = ap.parse_args(argv)

    rows = _read_jsonl(Path(args.train_rows))
    if not rows:
        logger.error("no training rows at %s", args.train_rows)
        return 1
    logger.info("training rows: %d", len(rows))

    src_texts = [build_input_text(r.get("theorem_statement", ""),
                                  r.get("state_before", "")) for r in rows]
    tactics = [r.get("tactic", "") for r in rows]
    vocab = TokenVocab.build(src_texts, tactics)
    logger.info("vocab size: %d", len(vocab))

    examples = [Example(
        theorem_name=r.get("theorem_name", ""),
        theorem_statement=r.get("theorem_statement", ""),
        state_before=r.get("state_before", ""),
        tactic=r.get("tactic", ""),
        split="train",
    ) for r in rows]

    import random as _r
    rng = _r.Random(args.seed)
    indices = list(range(len(examples)))
    rng.shuffle(indices)
    n_val = max(20, int(len(examples) * args.val_fraction))
    val_idx = set(indices[:n_val])
    train_examples = [e for i, e in enumerate(examples) if i not in val_idx]
    val_examples = [e for i, e in enumerate(examples) if i in val_idx]
    logger.info("train=%d val=%d", len(train_examples), len(val_examples))

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
    save_token_artifacts(out_dir, art, cfg, extra={"corpus": "v20_broad_plus"})
    logger.info("V20 BROAD-PLUS MODEL TRAINING DONE; saved to %s", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
