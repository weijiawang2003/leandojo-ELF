"""Train Mini-ELF v0: a tactic-autoencoder latent space + a conditional
rectified-flow tactic generator.

Stage 1 trains a char-level tactic autoencoder (the continuous latent space);
stage 2 freezes it and trains a small flow-matching MLP to transport Gaussian
noise → tactic latent, conditioned on ``theorem_statement + "\\n" + state_before``.
Input never includes ``state_after``. CPU-only, deterministic given ``--seed``.

This is the first Mini-ELF prototype — deliberately small and **not** a claim of
real next-state modeling (verification is still theorem-level,
``state_after_is_real=false``).

Example:

    python scripts/train_mini_elf.py \\
        --dataset data/processed/basic_lean_cli/next_tactic.jsonl \\
        --output-dir data/models/basic_lean_cli_mini_elf \\
        --ae-epochs 60 --flow-epochs 300 --latent-dim 48 --cond-dim 128 --seed 0
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_elf_lean.baselines import load_dataset, load_dataset_split  # noqa: E402
from mini_elf_lean.elf_train import ElfTrainConfig, save_artifacts, train  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--ae-epochs", type=int, default=60)
    p.add_argument("--flow-epochs", type=int, default=300)
    p.add_argument("--ae-lr", type=float, default=3e-3)
    p.add_argument("--flow-lr", type=float, default=2e-3)
    p.add_argument("--latent-dim", type=int, default=48)
    p.add_argument("--cond-dim", type=int, default=128)
    p.add_argument("--flow-hidden", type=int, default=128)
    p.add_argument("--flow-layers", type=int, default=3)
    p.add_argument("--n-samples", type=int, default=32)
    p.add_argument("--flow-steps", type=int, default=10)
    p.add_argument("--val-every", type=int, default=30)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    full = load_dataset(args.dataset)
    if not full:
        print(f"error: dataset empty: {args.dataset}", file=sys.stderr)
        return 2
    train_examples, val_examples = load_dataset_split(args.dataset, "val")
    print(f"loaded train={len(train_examples)} val={len(val_examples)} "
          f"({len({e.theorem_name for e in train_examples})} train theorems)")

    cfg = ElfTrainConfig(
        ae_epochs=args.ae_epochs, flow_epochs=args.flow_epochs, ae_lr=args.ae_lr, flow_lr=args.flow_lr,
        latent_dim=args.latent_dim, cond_dim=args.cond_dim, flow_hidden=args.flow_hidden,
        flow_layers=args.flow_layers, n_samples=args.n_samples, flow_steps=args.flow_steps,
        val_every=args.val_every, seed=args.seed,
    )

    def _log(rec):
        if args.verbose and rec.get("stage") == "flow" and "val_any_verified_top5" in rec:
            print(f"  [flow] epoch {rec['epoch']:3d}  loss={rec['flow_loss']:.4f}  "
                  f"val_any@5={rec['val_any_verified_top5']:.3f}")

    t0 = time.perf_counter()
    art = train(train_examples, val_examples, full, cfg, device="cpu", log_fn=_log)
    secs = time.perf_counter() - t0

    save_artifacts(args.output_dir, art, cfg, extra={"train_seconds": round(secs, 2)})

    s = art.summary
    print(f"\ntrained in {secs:.1f}s  |  params={s['n_parameters_total']:,} "
          f"(ae={s['ae_params']:,} cond={s['cond_params']:,} flow={s['flow_params']:,})  "
          f"vocab={s['vocab_size']}  latent={s['latent_dim']}")
    print(f"AE val reconstruction exact = {s['ae_val_recon_exact']:.3f}  |  "
          f"flow best epoch = {s['flow_best_epoch']}")
    vm = art.val_metrics
    print(f"val top1_exact = {vm['top1_exact']:.3f}  |  val top5 any-verified = "
          f"{vm['top5_any_verified']:.3f}  |  avg unique candidates = "
          f"{vm['avg_unique_candidates']:.1f}  |  empty = {vm['empty_generation_rate']:.3f}")
    print(f"artifacts -> {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
