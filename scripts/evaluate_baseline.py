"""Evaluate a tactic-prediction baseline over a processed next_tactic dataset.

This is **theorem-level** verification: lean-cli typechecks the *whole template*
substituted with the predicted tactic. We never use ``state_after`` as a
target — for this corpus it is the lean-cli placeholder (``state_after_is_real
=false``).

Example:

    python scripts/evaluate_baseline.py \\
        --dataset data/processed/basic_lean_cli/next_tactic.jsonl \\
        --output-dir data/baselines/basic_lean_cli_retrieval_val \\
        --baseline retrieval --split val --top-k 5 \\
        --verify-with-lean-cli --cache

Outputs (always written, even on empty splits):

    <output-dir>/predictions.jsonl
    <output-dir>/metrics.json
    <output-dir>/verification_cache.json     (when --cache, even if empty)
    <output-dir>/failures.jsonl              (Lean errors for failed tactics)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_elf_lean.baseline_eval import (  # noqa: E402
    DEFAULT_KS,
    SMALL_SAMPLE_THRESHOLD,
    VerificationCache,
    evaluate,
    make_lean_cli_verifier,
)
from mini_elf_lean.baseline_eval import (  # noqa: E402
    load_family_maps,
    per_family_pass_at_k,
    sibling_confusion,
)
from mini_elf_lean.baselines import (  # noqa: E402
    MajorityBaseline,
    RetrievalBaseline,
    load_dataset,
    load_dataset_split,
)
from mini_elf_lean.neural_baseline import NeuralTacticBaseline  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--dataset", required=True, type=Path,
                   help="Processed next_tactic.jsonl produced by scripts/build_dataset.py.")
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--baseline", required=True, choices=("majority", "retrieval", "neural"))
    p.add_argument("--split", default="val", choices=("train", "val", "test"),
                   help="Which split to evaluate. 'train' is for debugging only.")
    p.add_argument("--top-k", type=int, default=5,
                   help="Number of ranked candidate tactics per example.")
    p.add_argument("--verify-with-lean-cli", dest="verify", action="store_true",
                   help="Run real lean-cli verification on each top-k candidate.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--cache", dest="cache", action="store_true",
                   help="Read/write a JSON verification cache in --output-dir (default).")
    g.add_argument("--no-cache", dest="cache", action="store_false")
    p.set_defaults(cache=True)
    p.add_argument("--lean-timeout", type=float, default=30.0)
    p.add_argument("--retrieval-neighbors", type=int, default=16,
                   help="How many train rows to score before dedup-by-tactic.")
    p.add_argument("--seeds", type=Path, default=None,
                   help="Seeds JSONL with metadata.pattern_family; enables per-family pass@k "
                        "and the sibling-family confusion table in metrics.json.")
    # neural-baseline hyperparameters (ignored by majority/retrieval)
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--dim", type=int, default=8192)
    p.add_argument("--lr", type=float, default=0.5)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("-v", "--verbose", action="count", default=0)
    return p


def _write_outputs(args, result, cache: VerificationCache) -> None:
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    pred_path = out / "predictions.jsonl"
    with pred_path.open("w", encoding="utf-8") as fh:
        for row in result.predictions:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            fh.write("\n")

    metrics_path = out / "metrics.json"
    metrics_path.write_text(
        json.dumps(result.metrics, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )

    failures_path = out / "failures.jsonl"
    with failures_path.open("w", encoding="utf-8") as fh:
        for row in result.failures:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            fh.write("\n")

    if args.cache:
        cache.path = out / "verification_cache.json"
        cache.dirty = True  # force write so the cache file always exists
        cache.save()


def _write_training_files(out: Path, baseline) -> None:
    """Persist neural training artifacts (no-op for non-neural baselines)."""
    cfg = getattr(baseline, "training_config", None)
    log = getattr(baseline, "training_log", None)
    if cfg is not None:
        (out / "training_config.json").write_text(
            json.dumps(cfg, indent=2, sort_keys=True), encoding="utf-8"
        )
    if log is not None:
        with (out / "training_log.jsonl").open("w", encoding="utf-8") as fh:
            for row in log:
                fh.write(json.dumps(row, sort_keys=True) + "\n")


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING - 10 * min(args.verbose, 2),
        format="%(message)s",
    )

    full = load_dataset(args.dataset)
    if not full:
        print(f"error: dataset is empty: {args.dataset}", file=sys.stderr)
        return 2

    train, eval_examples = load_dataset_split(args.dataset, args.split)
    print(f"loaded {len(full)} examples; train={len(train)} eval[{args.split}]={len(eval_examples)}")

    if args.baseline == "majority":
        baseline = MajorityBaseline().fit(train)
    elif args.baseline == "retrieval":
        baseline = RetrievalBaseline(neighbors=args.retrieval_neighbors).fit(train)
        print(f"retrieval mode: {baseline.mode}")
    else:
        import time as _t
        t0 = _t.perf_counter()
        baseline = NeuralTacticBaseline(
            dim=args.dim, epochs=args.epochs, lr=args.lr, seed=args.seed,
        ).fit(train)
        train_s = _t.perf_counter() - t0
        baseline.training_config["train_seconds"] = round(train_s, 2)
        print(f"neural trained in {train_s:.1f}s: {baseline.training_config['n_classes']} classes, "
              f"train_top1_acc={baseline.training_config['train_top1_accuracy']:.3f}")

    cache = VerificationCache.load(
        args.output_dir / "verification_cache.json" if args.cache else None,
        enabled=args.cache,
    )

    verifier = make_lean_cli_verifier(timeout=args.lean_timeout) if args.verify else None

    if eval_examples:
        result = evaluate(
            baseline,
            train=train,
            eval_examples=eval_examples,
            full_dataset=full,
            k_values=DEFAULT_KS,
            top_k=args.top_k,
            verifier=verifier,
            cache=cache,
            progress=lambda i, n: (
                print(f"  evaluating {i}/{n}", end="\r", flush=True)
                if args.verbose else None
            ),
        )
        if args.verbose:
            print()  # newline after progress
    else:
        # Empty eval split: still produce the canonical outputs.
        from mini_elf_lean.baseline_eval import EvaluationResult
        from mini_elf_lean.baselines import split_summary

        result = EvaluationResult(
            metrics={
                "baseline": baseline.name,
                "n_examples": 0, "n_theorems": 0,
                "small_sample_warning": True,
                "split_diagnostics": split_summary(train, eval_examples),
                "exact_match": {"top1_exact": 0.0, "topk_any_verified": {}},
                "oracle": {"rows_with_verified_in_corpus": 0,
                           "rows_with_verified_in_corpus_rate": 0.0},
                "note": f"eval split {args.split!r} is empty for this dataset",
            },
            predictions=[], failures=[],
        )

    # Optional pattern-family analysis (per-family pass@k + sibling confusion).
    if args.seeds and result.predictions:
        thm2fam, tac2fams = load_family_maps(args.seeds)
        if args.verify:
            result.metrics["per_family_pass_at_k"] = per_family_pass_at_k(
                result.predictions, thm2fam, DEFAULT_KS
            )
        result.metrics["sibling_confusion"] = sibling_confusion(
            result.predictions, thm2fam, tac2fams
        )

    _write_outputs(args, result, cache)
    _write_training_files(args.output_dir, baseline)
    print(json.dumps(result.metrics, indent=2, sort_keys=True))
    n = result.metrics["n_examples"]
    if 0 < n <= SMALL_SAMPLE_THRESHOLD:
        print(
            f"\nNOTE: only {n} eval example(s) — metrics are diagnostic, not "
            "statistically meaningful. Grow the corpus before drawing conclusions."
        )
    if n == 0:
        print(f"\nNOTE: split {args.split!r} contains 0 rows for this dataset.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
