"""Mini-ELF v8 Part 3 — train the proof-block seq2seq under a chosen regime.

Reuses :mod:`mini_elf_lean.ar_train.train` (the same training loop as the v0
AR baseline) but reads from the v8 proof-blocks dataset directories. Saves the
artifact set in the standard layout (``config.json``, ``vocab.json``,
``model.pt``, ``train_log.jsonl``, ``val_predictions.jsonl``,
``val_metrics.json``) so :class:`ProofBlockSeq2SeqProposer` can pick it up
directly.

Usage::

    ./.venv/bin/python scripts/train_proof_block_seq2seq.py \
        --regime-dir data/processed/proof_blocks_interpolation \
        --out-dir   data/models/proof_block_seq2seq_interpolation \
        --epochs 30 --seed 0

For ``family_holdout/<fam>`` (no val split), the script falls back to taking
10 % of train (theorem-stratified) as a synthetic val so model selection still
has signal — that synthetic val is recorded in the config under
``training.val_source: "synthetic"``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.ar_train import TrainConfig, save_artifacts, train  # noqa: E402
from mini_elf_lean.baselines import Example  # noqa: E402
from mini_elf_lean.proof_block_seq2seq import load_proof_block_regime  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_proof_block_seq2seq")


def _stable_bucket(thm: str, salt: str) -> float:
    h = hashlib.sha256(f"{salt}::{thm}".encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") / float(1 << 64)


def _synthetic_val_split(train: List[Example], *, frac: float = 0.1,
                         seed: str = "v8-synthval") -> tuple[List[Example], List[Example]]:
    """Theorem-stratified pseudo-val from the train split (used when the
    regime has no val of its own)."""
    if not train:
        return [], []
    thms = {e.theorem_name for e in train}
    buckets = {t: _stable_bucket(t, seed) for t in thms}
    val_thms = {t for t, b in buckets.items() if b < frac}
    if not val_thms:
        # ensure at least one theorem in val
        val_thms = {sorted(thms, key=lambda t: buckets[t])[0]}
    new_train = [e for e in train if e.theorem_name not in val_thms]
    new_val = [e for e in train if e.theorem_name in val_thms]
    return new_train, new_val


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--regime-dir", required=True,
                    help="proof_blocks_* directory containing train.jsonl etc.")
    ap.add_argument("--out-dir", required=True,
                    help="where to write model.pt / vocab.json / config.json")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--embedding-dim", type=int, default=64)
    ap.add_argument("--hidden-dim", type=int, default=128)
    ap.add_argument("--num-layers", type=int, default=1)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--max-input-len", type=int, default=160)
    ap.add_argument("--max-output-len", type=int, default=80)
    ap.add_argument("--beam-width", type=int, default=10)
    ap.add_argument("--length-penalty", type=float, default=0.7)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    regime_dir = Path(args.regime_dir)
    out_dir = Path(args.out_dir)

    train_ex, val_ex, _test_ex = load_proof_block_regime(regime_dir)
    if not train_ex:
        logger.error("no training examples in %s", regime_dir)
        return 1
    val_source = "val.jsonl"
    if not val_ex:
        train_ex, val_ex = _synthetic_val_split(train_ex)
        val_source = "synthetic_from_train"
        logger.warning("no val.jsonl found; synthesising val (%d theorems)",
                       len({e.theorem_name for e in val_ex}))
    logger.info("regime=%s train=%d val=%d (val_source=%s)",
                regime_dir.name, len(train_ex), len(val_ex), val_source)

    cfg = TrainConfig(
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        embedding_dim=args.embedding_dim,
        hidden_dim=args.hidden_dim,
        num_layers=args.num_layers,
        dropout=args.dropout,
        max_input_len=args.max_input_len,
        max_output_len=args.max_output_len,
        beam_width=args.beam_width,
        length_penalty=args.length_penalty,
        seed=args.seed,
    )

    artifacts = train(train_ex, val_ex, cfg, log_fn=lambda r: logger.info("epoch %s", r))
    extra = {
        "regime_dir": str(regime_dir),
        "regime_name": regime_dir.name,
        "val_source": val_source,
    }
    save_artifacts(out_dir, artifacts, cfg, extra_config=extra)
    logger.info("wrote %s  (val_metrics=%s)", out_dir, artifacts.val_metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
