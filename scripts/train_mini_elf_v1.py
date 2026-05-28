"""Train Mini-ELF v1: a denoising tactic-AE + structured-conditioned
rectified-flow generator, *plus* a verifier-aware reranker.

Stage 1 trains a denoising char-level tactic autoencoder (input corruption +
latent noise). Stage 2 freezes it and trains a flow-matching MLP conditioned on
the v1 structured prompt encoder (raw bi-GRU + goal bi-GRU + goal-shape embed +
numeric features). Stage 3 trains the reranker on previously-collected Lean
traces (verified = positive, failed = negative; train-split theorems only). All
artifacts land in one model dir. Input never includes ``state_after``. CPU-only,
deterministic given ``--seed``.

Example:

    python scripts/train_mini_elf_v1.py \\
        --dataset data/processed/basic_lean_cli/next_tactic.jsonl \\
        --output-dir data/models/basic_lean_cli_mini_elf_v1 \\
        --verified-traces data/traces/basic_lean_cli_verified.jsonl \\
        --failed-traces data/traces/basic_lean_cli_failed.jsonl \\
        --splits data/processed/basic_lean_cli/theorem_splits.json \\
        --seeds data/seeds/basic_lean_seeds.jsonl \\
        --ae-epochs 80 --flow-epochs 400 --rerank-epochs 80 --latent-dim 64 --seed 0
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_elf_lean.baselines import load_dataset, load_dataset_split  # noqa: E402
from mini_elf_lean.elf_rerank import (  # noqa: E402
    RerankConfig,
    Reranker,
    load_split_names,
    rerank_examples_from_traces,
)
from mini_elf_lean.elf_v1_train import ElfV1TrainConfig, save_artifacts_v1, train_v1  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--verified-traces", type=Path, default=None)
    p.add_argument("--failed-traces", type=Path, default=None)
    p.add_argument("--splits", type=Path, default=None, help="theorem_splits.json for reranker no-leakage")
    p.add_argument("--seeds", type=Path, default=None, help="seeds JSONL for pattern_family map")
    p.add_argument("--ae-epochs", type=int, default=80)
    p.add_argument("--flow-epochs", type=int, default=400)
    p.add_argument("--rerank-epochs", type=int, default=80)
    p.add_argument("--self-train-rerank", action="store_true",
                   help="generate flow candidates on train theorems, Lean-label them, "
                        "and add as hard reranker examples (needs lean-cli)")
    p.add_argument("--self-train-max", type=int, default=12,
                   help="max distinct flow candidates per train theorem to Lean-label")
    p.add_argument("--lean-timeout", type=float, default=30.0)
    p.add_argument("--ae-denoise-prob", type=float, default=0.1)
    p.add_argument("--ae-latent-noise-std", type=float, default=0.1)
    p.add_argument("--scheduled-sampling", action="store_true")
    p.add_argument("--ae-teacher-forcing-ratio", type=float, default=1.0)
    p.add_argument("--latent-dim", type=int, default=64)
    p.add_argument("--cond-dim", type=int, default=128)
    p.add_argument("--flow-hidden", type=int, default=128)
    p.add_argument("--flow-layers", type=int, default=3)
    p.add_argument("--n-samples", type=int, default=64)
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

    cfg = ElfV1TrainConfig(
        ae_epochs=args.ae_epochs, flow_epochs=args.flow_epochs,
        ae_denoise_prob=args.ae_denoise_prob, ae_latent_noise_std=args.ae_latent_noise_std,
        scheduled_sampling=args.scheduled_sampling,
        ae_teacher_forcing_ratio=args.ae_teacher_forcing_ratio,
        latent_dim=args.latent_dim, cond_dim=args.cond_dim, flow_hidden=args.flow_hidden,
        flow_layers=args.flow_layers, n_samples=args.n_samples, flow_steps=args.flow_steps,
        val_every=args.val_every, seed=args.seed,
    )

    def _log(rec):
        if args.verbose and rec.get("stage") == "flow" and "val_any_verified_top5" in rec:
            print(f"  [flow] epoch {rec['epoch']:3d}  loss={rec['flow_loss']:.4f}  "
                  f"val_any@5={rec['val_any_verified_top5']:.3f}")
        elif args.verbose and rec.get("stage") == "ae" and rec["epoch"] % 20 == 0:
            print(f"  [ae]   epoch {rec['epoch']:3d}  loss={rec['ae_loss']:.4f}  "
                  f"recon={rec['val_recon_exact']:.3f}")

    t0 = time.perf_counter()
    art = train_v1(train_examples, val_examples, full, cfg, device="cpu", log_fn=_log)
    gen_secs = time.perf_counter() - t0
    save_artifacts_v1(args.output_dir, art, cfg, extra={"train_seconds_generator": round(gen_secs, 2)})

    s = art.summary
    print(f"\n[generator] trained in {gen_secs:.1f}s  |  params={s['n_parameters_total']:,} "
          f"(ae={s['ae_params']:,} cond={s['cond_params']:,} flow={s['flow_params']:,})  "
          f"vocab={s['vocab_size']}  latent={s['latent_dim']}")
    print(f"[generator] AE val recon = {s['ae_val_recon_exact']:.3f}  flow best epoch = {s['flow_best_epoch']}  "
          f"denoise={s['ae_denoise_prob']} latent_noise={s['ae_latent_noise_std']}")
    vm = art.val_metrics
    print(f"[generator] val top1_exact={vm['top1_exact']:.3f}  val top5_any={vm['top5_any_verified']:.3f}  "
          f"avg_unique={vm['avg_unique_candidates']:.1f}")

    # ---- stage 3: reranker ----
    if args.verified_traces and args.failed_traces:
        train_names = load_split_names(args.splits, "train") if args.splits else None
        family_map = {}
        if args.seeds:
            from mini_elf_lean.baseline_eval import load_family_maps
            family_map, _ = load_family_maps(args.seeds)
        rex = rerank_examples_from_traces(
            args.verified_traces, args.failed_traces,
            train_names=train_names, family_map=family_map,
        )
        n_trace = len(rex)

        # Hard examples: flow candidates on train theorems, labelled by Lean.
        if args.self_train_rerank:
            from mini_elf_lean.baseline_eval import VerificationCache, make_lean_cli_verifier
            from mini_elf_lean.elf_v1_sample import MiniElfV1Baseline
            from mini_elf_lean.elf_v1_train import flow_rerank_examples

            cache = VerificationCache.load(args.output_dir / "selftrain_cache.json")
            raw_verify = make_lean_cli_verifier(timeout=args.lean_timeout)

            def verify_fn(name, stmt, tactic):
                hit = cache.get(name, tactic)
                if hit is not None:
                    return bool(hit.get("success"))
                res = raw_verify(name, stmt, tactic)
                cache.put(name, tactic, res)
                return bool(res.get("success"))

            flow_baseline = MiniElfV1Baseline.load(
                args.output_dir, n_samples=args.n_samples, steps=args.flow_steps,
                seed=args.seed, decode="decoder",
            )
            print(f"[reranker] self-training: Lean-labelling flow candidates on "
                  f"{len(train_examples)} train theorems (cached)...")
            t_st = time.perf_counter()
            flow_ex = flow_rerank_examples(
                flow_baseline, train_examples, verify_fn,
                max_per_row=args.self_train_max, family_map=family_map,
            )
            cache.dirty = True
            cache.save()
            n_fpos = sum(1 for e in flow_ex if e.label == 1)
            print(f"[reranker] self-train: {len(flow_ex)} flow examples "
                  f"({n_fpos} pos / {len(flow_ex) - n_fpos} neg) in {time.perf_counter() - t_st:.1f}s")
            rex = rex + flow_ex

        n_pos = sum(1 for e in rex if e.label == 1)
        print(f"[reranker] {len(rex)} train examples ({n_pos} pos / {len(rex) - n_pos} neg)"
              f"  [{n_trace} trace + {len(rex) - n_trace} flow]"
              f"{' [train-split only]' if train_names else ''}")
        t1 = time.perf_counter()
        rr = Reranker.fit(rex, RerankConfig(epochs=args.rerank_epochs, seed=args.seed))
        rr.save(args.output_dir)
        print(f"[reranker] trained in {time.perf_counter() - t1:.1f}s  -> {args.output_dir}")
    else:
        print("\n[reranker] skipped (no --verified-traces/--failed-traces)")

    print(f"\nartifacts -> {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
