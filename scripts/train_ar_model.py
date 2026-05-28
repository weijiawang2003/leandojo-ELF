"""Train the character-level AR seq2seq tactic model on a processed dataset.

This trains the project's first **true generative** tactic model — it decodes a
tactic character by character, so it can emit strings never seen as a training
label. Input is ``theorem_statement + "\\n" + state_before`` only; ``state_after``
is never read (the dataset loader doesn't even expose it). CPU-only, deterministic
given ``--seed``.

Example:

    python scripts/train_ar_model.py \\
        --dataset data/processed/basic_lean_cli/next_tactic.jsonl \\
        --output-dir data/models/basic_lean_cli_ar \\
        --epochs 60 --batch-size 32 --lr 0.003 \\
        --embedding-dim 64 --hidden-dim 128 --seed 0

Outputs (in --output-dir):

    config.json  vocab.json  model.pt  train_log.jsonl
    val_predictions.jsonl  val_metrics.json
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_elf_lean.ar_train import (  # noqa: E402
    TrainConfig,
    save_artifacts,
    train,
)
from mini_elf_lean.baselines import load_dataset_split  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--dataset", required=True, type=Path,
                   help="Processed next_tactic.jsonl from scripts/build_dataset.py.")
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=3e-3)
    p.add_argument("--embedding-dim", type=int, default=64)
    p.add_argument("--hidden-dim", type=int, default=128)
    p.add_argument("--num-layers", type=int, default=1)
    p.add_argument("--dropout", type=float, default=0.1)
    p.add_argument("--max-input-len", type=int, default=160)
    p.add_argument("--max-output-len", type=int, default=80)
    p.add_argument("--beam-width", type=int, default=5)
    p.add_argument("--length-penalty", type=float, default=0.7)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Print per-epoch train/val loss.")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    # split="val" -> (all train rows, val rows). Leakage is re-checked inside.
    train_examples, val_examples = load_dataset_split(args.dataset, "val")
    if not train_examples:
        print(f"error: no train rows in {args.dataset}", file=sys.stderr)
        return 2
    print(f"loaded train={len(train_examples)} val={len(val_examples)} "
          f"({len({e.theorem_name for e in train_examples})} train theorems)")

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

    def _log(rec):
        if args.verbose:
            print(f"  epoch {rec['epoch']:3d}  train_loss={rec['train_loss']:.4f}  "
                  f"tok_acc={rec['train_token_acc']:.3f}  val_loss={rec['val_loss']:.4f}  "
                  f"val_exact={rec['val_greedy_exact_top1']:.3f}")

    t0 = time.perf_counter()
    art = train(train_examples, val_examples, cfg, device="cpu", log_fn=_log)
    train_seconds = time.perf_counter() - t0

    save_artifacts(
        args.output_dir, art, cfg,
        extra_config={"train_seconds": round(train_seconds, 2)},
    )

    print(f"\ntrained in {train_seconds:.1f}s  |  params={art.summary['n_parameters']:,}  "
          f"vocab={art.summary['vocab_size']}  best_epoch={art.summary['best_epoch']}")
    print(f"val greedy exact@1 = {art.val_metrics['greedy_exact_top1']:.3f}  |  "
          f"val beam@{cfg.beam_width} contains-gold = "
          f"{art.val_metrics[f'beam_top{cfg.beam_width}_contains_gold']:.3f}  |  "
          f"avg gen len = {art.val_metrics['avg_generated_length']:.1f}  |  "
          f"empty = {art.val_metrics['empty_generation_rate']:.3f}")
    if art.summary["truncation"]["source_truncated"] or art.summary["truncation"]["target_truncated"]:
        print(f"NOTE truncation: {art.summary['truncation']}")
    print(f"artifacts -> {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
