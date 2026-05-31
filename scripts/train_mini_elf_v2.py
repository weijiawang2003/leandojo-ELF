"""Train Mini-ELF v2 — same architecture as v1, trained on the **combined**
(basic + hard) corpus to test whether adding harder, less-templated data improves
generalization.

v2 reuses the v1 modules wholesale (`elf_v1_train.train_v1` for the denoising AE +
structured-flow generator; `elf_rerank.Reranker` for the verifier-aware reranker).
The only differences are data-side:

  * trains on a combined processed dataset (whose ``split`` field encodes the
    chosen v2 split strategy — hash / difficulty_holdout / adversarial_sibling /
    family_holdout — so evaluation on that split's test set is leakage-free);
  * the reranker sees **both** corpora's verified/failed traces (more, harder
    negatives) plus self-training hard negatives from v2's own flow candidates on
    the combined train theorems, Lean-labelled.

Theorem-level only (``state_after_is_real=false``); no full ELF over proof states.
CPU-only, deterministic given ``--seed``.
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
    p.add_argument("--dataset", required=True, type=Path,
                   help="combined next_tactic.jsonl (split field encodes the v2 strategy)")
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--verified-traces", type=Path, nargs="+", default=None)
    p.add_argument("--failed-traces", type=Path, nargs="+", default=None)
    p.add_argument("--splits", type=Path, default=None,
                   help="theorem_splits.json (combined) for reranker no-leakage filtering")
    p.add_argument("--seeds", type=Path, nargs="+", default=None,
                   help="one or more seeds JSONL for the pattern_family map")
    p.add_argument("--ae-epochs", type=int, default=100)
    p.add_argument("--flow-epochs", type=int, default=500)
    p.add_argument("--rerank-epochs", type=int, default=100)
    p.add_argument("--ae-denoise-prob", type=float, default=0.1)
    p.add_argument("--ae-latent-noise-std", type=float, default=0.1)
    p.add_argument("--latent-dim", type=int, default=64)
    p.add_argument("--cond-dim", type=int, default=128)
    p.add_argument("--n-samples", type=int, default=64)
    p.add_argument("--flow-steps", type=int, default=10)
    p.add_argument("--val-every", type=int, default=30)
    p.add_argument("--self-train-rerank", action="store_true")
    p.add_argument("--self-train-max", type=int, default=10)
    p.add_argument("--lean-timeout", type=float, default=30.0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _merged_family_map(seed_paths) -> dict:
    from mini_elf_lean.baseline_eval import load_family_maps
    fam: dict = {}
    for sp in seed_paths or []:
        thm2fam, _ = load_family_maps(sp)
        fam.update(thm2fam)
    return fam


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
        latent_dim=args.latent_dim, cond_dim=args.cond_dim,
        n_samples=args.n_samples, flow_steps=args.flow_steps, val_every=args.val_every, seed=args.seed,
    )

    def _log(rec):
        if args.verbose and rec.get("stage") == "flow" and "val_any_verified_top5" in rec:
            print(f"  [flow] epoch {rec['epoch']:3d}  loss={rec['flow_loss']:.4f}  "
                  f"val_any@5={rec['val_any_verified_top5']:.3f}")

    t0 = time.perf_counter()
    art = train_v1(train_examples, val_examples, full, cfg, device="cpu", log_fn=_log)
    gen_secs = time.perf_counter() - t0
    save_artifacts_v1(args.output_dir, art, cfg, extra={
        "model": "mini_elf_v2", "corpus": "combined", "train_seconds_generator": round(gen_secs, 2),
    })
    s = art.summary
    print(f"\n[generator] {gen_secs:.1f}s  params={s['n_parameters_total']:,}  vocab={s['vocab_size']}  "
          f"AE recon={s['ae_val_recon_exact']:.3f}  flow best epoch={s['flow_best_epoch']}")
    vm = art.val_metrics
    print(f"[generator] val top1_exact={vm['top1_exact']:.3f}  val top5_any={vm['top5_any_verified']:.3f}")

    # ---- reranker (both corpora's traces + self-training) ----
    if args.verified_traces and args.failed_traces:
        train_names = load_split_names(args.splits, "train") if args.splits else None
        family_map = _merged_family_map(args.seeds)
        # Read every verified file (label 1) and every failed file (label 0).
        rex = []
        for vpath in args.verified_traces:
            rex += rerank_examples_from_traces(vpath, Path("/dev/null"),
                                               train_names=train_names, family_map=family_map)
        for fpath in args.failed_traces:
            rex += rerank_examples_from_traces(Path("/dev/null"), fpath,
                                               train_names=train_names, family_map=family_map)
        n_trace = len(rex)

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
            print(f"[reranker] self-training on {len(train_examples)} combined train theorems...")
            t_st = time.perf_counter()
            flow_ex = flow_rerank_examples(flow_baseline, train_examples, verify_fn,
                                           max_per_row=args.self_train_max, family_map=family_map)
            cache.dirty = True
            cache.save()
            n_fpos = sum(1 for e in flow_ex if e.label == 1)
            print(f"[reranker] self-train: {len(flow_ex)} flow examples "
                  f"({n_fpos} pos / {len(flow_ex) - n_fpos} neg) in {time.perf_counter() - t_st:.1f}s")
            rex += flow_ex

        n_pos = sum(1 for e in rex if e.label == 1)
        print(f"[reranker] {len(rex)} examples ({n_pos} pos / {len(rex) - n_pos} neg) "
              f"[{n_trace} trace + {len(rex) - n_trace} flow]")
        t1 = time.perf_counter()
        rr = Reranker.fit(rex, RerankConfig(epochs=args.rerank_epochs, seed=args.seed))
        rr.save(args.output_dir)
        print(f"[reranker] trained in {time.perf_counter() - t1:.1f}s")
    else:
        print("[reranker] skipped (no traces given)")

    print(f"\nartifacts -> {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
