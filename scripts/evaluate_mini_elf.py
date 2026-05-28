"""Evaluate Mini-ELF v0 with real lean-cli ``pass@k``.

Wraps the trained model in :class:`~mini_elf_lean.elf_sample.MiniElfBaseline` and
reuses the shared evaluation harness, so the numbers are directly comparable to
majority / retrieval / log-linear / AR. Adds Mini-ELF generation metrics:
average generated length, empty + candidate-invalid rates, novel-candidate rate,
and **candidate diversity** (avg distinct candidates per row across the noise
samples). Theorem-level verification (``state_after_is_real=false``).

``--decode decoder`` (default) is the generative path (AE decoder on the flow
latent); ``--decode nn`` snaps each latent to the nearest train tactic (an
ablation — not open-vocabulary).

Example:

    MINI_ELF_LEAN_COMMAND=$HOME/.elan/toolchains/.../bin/lean \\
    python scripts/evaluate_mini_elf.py \\
        --model-dir data/models/basic_lean_cli_mini_elf \\
        --dataset data/processed/basic_lean_cli/next_tactic.jsonl \\
        --output-dir data/baselines/basic_lean_cli_mini_elf_val \\
        --split val --top-k 5 --verify-with-lean-cli --cache \\
        --seeds data/seeds/basic_lean_seeds.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_elf_lean.baseline_eval import (  # noqa: E402
    DEFAULT_KS,
    SMALL_SAMPLE_THRESHOLD,
    VerificationCache,
    evaluate,
    load_family_maps,
    make_lean_cli_verifier,
    per_family_pass_at_k,
    sibling_confusion,
)
from mini_elf_lean.baselines import load_dataset, load_dataset_split  # noqa: E402
from mini_elf_lean.elf_sample import MiniElfBaseline  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--model-dir", required=True, type=Path)
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--split", default="val", choices=("train", "val", "test"))
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--n-samples", type=int, default=32)
    p.add_argument("--flow-steps", type=int, default=10)
    p.add_argument("--decode", default="decoder", choices=("decoder", "nn"))
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--verify-with-lean-cli", dest="verify", action="store_true")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--cache", dest="cache", action="store_true")
    g.add_argument("--no-cache", dest="cache", action="store_false")
    p.set_defaults(cache=True)
    p.add_argument("--lean-timeout", type=float, default=30.0)
    p.add_argument("--seeds", type=Path, default=None)
    p.add_argument("-v", "--verbose", action="count", default=0)
    return p


def _generation_stats(
    predictions: Sequence[Dict[str, Any]], baseline: MiniElfBaseline,
    eval_examples, train_tactics: set, verifier_used: bool,
) -> Dict[str, Any]:
    n = len(predictions)
    top1_lengths: List[int] = []
    empty_top1 = 0
    total_candidates = novel_candidates = verified_candidates = novel_verified = 0
    rows_passed_via_novel = 0
    for row in predictions:
        preds = row.get("predictions") or []
        top1 = preds[0] if preds else ""
        top1_lengths.append(len(top1))
        if not top1.strip():
            empty_top1 += 1
        lean_results = row.get("lean_results") or {}
        passed_novel = False
        for tac in preds:
            total_candidates += 1
            novel = tac not in train_tactics
            if novel:
                novel_candidates += 1
            if lean_results.get(tac, {}).get("success"):
                verified_candidates += 1
                if novel:
                    novel_verified += 1
                    passed_novel = True
        if passed_novel:
            rows_passed_via_novel += 1

    # Candidate diversity: distinct strings across all noise samples per row.
    uniq_per_row = []
    for e in eval_examples:
        ranked = baseline.predict_with_counts(e)
        uniq_per_row.append(len(ranked))

    stats: Dict[str, Any] = {
        "decode_mode": baseline.decode,
        "n_samples_per_row": baseline.n_samples,
        "avg_generated_length_top1": (sum(top1_lengths) / n) if n else 0.0,
        "empty_generation_rate": (empty_top1 / n) if n else 0.0,
        "avg_distinct_candidates_per_row": (sum(uniq_per_row) / len(uniq_per_row)) if uniq_per_row else 0.0,
        "total_candidates": total_candidates,
        "novel_candidate_rate": (novel_candidates / total_candidates) if total_candidates else 0.0,
        "novel_candidates": novel_candidates,
    }
    if verifier_used:
        stats["candidate_invalid_rate"] = (
            1.0 - verified_candidates / total_candidates if total_candidates else 0.0
        )
        stats["novel_candidates_verified"] = novel_verified
        stats["rows_passed_via_novel_tactic"] = rows_passed_via_novel
    return stats


def _write_outputs(out: Path, result, cache: VerificationCache, write_cache: bool) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "predictions.jsonl").open("w", encoding="utf-8") as fh:
        for row in result.predictions:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    (out / "metrics.json").write_text(
        json.dumps(result.metrics, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    with (out / "failures.jsonl").open("w", encoding="utf-8") as fh:
        for row in result.failures:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    if write_cache:
        cache.path = out / "verification_cache.json"
        cache.dirty = True
        cache.save()


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    full = load_dataset(args.dataset)
    if not full:
        print(f"error: dataset empty: {args.dataset}", file=sys.stderr)
        return 2
    train, eval_examples = load_dataset_split(args.dataset, args.split)
    train_tactics = {e.tactic for e in train}
    print(f"loaded {len(full)} examples; train={len(train)} eval[{args.split}]={len(eval_examples)}")

    baseline = MiniElfBaseline.load(
        args.model_dir, n_samples=args.n_samples, steps=args.flow_steps,
        seed=args.seed, decode=args.decode,
    )
    print(f"loaded Mini-ELF from {args.model_dir}  ({baseline.mode})")

    cache = VerificationCache.load(
        args.output_dir / "verification_cache.json" if args.cache else None, enabled=args.cache,
    )
    verifier = make_lean_cli_verifier(timeout=args.lean_timeout) if args.verify else None

    if not eval_examples:
        from mini_elf_lean.baseline_eval import EvaluationResult
        result = EvaluationResult(
            metrics={"baseline": baseline.name, "n_examples": 0,
                     "note": f"split {args.split!r} empty"},
            predictions=[], failures=[],
        )
        _write_outputs(args.output_dir, result, cache, args.cache)
        print(json.dumps(result.metrics, indent=2, sort_keys=True))
        return 0

    result = evaluate(
        baseline, train=train, eval_examples=eval_examples, full_dataset=full,
        k_values=DEFAULT_KS, top_k=args.top_k, verifier=verifier, cache=cache,
        progress=lambda i, n: (print(f"  evaluating {i}/{n}", end="\r", flush=True) if args.verbose else None),
    )
    if args.verbose:
        print()

    result.metrics["elf_generation"] = _generation_stats(
        result.predictions, baseline, eval_examples, train_tactics, verifier_used=verifier is not None
    )

    if args.seeds and result.predictions:
        thm2fam, tac2fams = load_family_maps(args.seeds)
        if args.verify:
            result.metrics["per_family_pass_at_k"] = per_family_pass_at_k(result.predictions, thm2fam, DEFAULT_KS)
        result.metrics["sibling_confusion"] = sibling_confusion(result.predictions, thm2fam, tac2fams)

    _write_outputs(args.output_dir, result, cache, args.cache)
    print(json.dumps(result.metrics, indent=2, sort_keys=True))
    n = result.metrics["n_examples"]
    if 0 < n <= SMALL_SAMPLE_THRESHOLD:
        print(f"\nNOTE: only {n} eval example(s) — diagnostic, not statistically meaningful.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
