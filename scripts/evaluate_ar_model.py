"""Evaluate a trained AR seq2seq tactic model with real lean-cli ``pass@k``.

Reuses the same evaluation harness as the other baselines
(:func:`mini_elf_lean.baseline_eval.evaluate`) by wrapping the trained model in
:class:`~mini_elf_lean.ar_decode.ARGenerativeBaseline`, so the AR numbers are
directly comparable to majority / retrieval / log-linear. Adds AR-specific
generation metrics on top: average generated length, empty-generation rate,
candidate-invalid rate, and **open-vocabulary** stats (how often a *novel*
tactic — one never seen as a training label — is generated and verified).

This is theorem-level verification (``state_after_is_real=false``); we never use
``state_after`` as a target.

Example:

    MINI_ELF_LEAN_COMMAND=$HOME/.elan/toolchains/.../bin/lean \\
    python scripts/evaluate_ar_model.py \\
        --model-dir data/models/basic_lean_cli_ar \\
        --dataset data/processed/basic_lean_cli/next_tactic.jsonl \\
        --output-dir data/baselines/basic_lean_cli_ar_val \\
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

from mini_elf_lean.ar_decode import ARGenerativeBaseline  # noqa: E402
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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--model-dir", required=True, type=Path,
                   help="Directory written by scripts/train_ar_model.py.")
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--split", default="val", choices=("train", "val", "test"))
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--beam-width", type=int, default=5)
    p.add_argument("--length-penalty", type=float, default=0.7)
    p.add_argument("--verify-with-lean-cli", dest="verify", action="store_true")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--cache", dest="cache", action="store_true")
    g.add_argument("--no-cache", dest="cache", action="store_false")
    p.set_defaults(cache=True)
    p.add_argument("--lean-timeout", type=float, default=30.0)
    p.add_argument("--seeds", type=Path, default=None,
                   help="Seeds JSONL with metadata.pattern_family; enables per-family "
                        "pass@k and the sibling-family confusion table.")
    p.add_argument("-v", "--verbose", action="count", default=0)
    return p


def _ar_generation_stats(
    predictions: Sequence[Dict[str, Any]],
    train_tactics: set,
    verifier_used: bool,
) -> Dict[str, Any]:
    """AR-specific metrics computed from the per-row predictions.

    ``train_tactics`` is the set of tactic strings that appear as a label in the
    train split — a generated candidate not in this set is "novel" (the
    open-vocabulary question). When a verifier ran, we also count novel
    candidates that lean-cli accepted, and rows whose pass came *via* a novel
    tactic.
    """
    n = len(predictions)
    top1_lengths: List[int] = []
    empty_top1 = 0
    total_candidates = 0
    novel_candidates = 0
    novel_verified = 0
    rows_passed_via_novel = 0
    verified_candidates = 0

    for row in predictions:
        preds = row.get("predictions") or []
        top1 = preds[0] if preds else ""
        top1_lengths.append(len(top1))
        if not top1.strip():
            empty_top1 += 1
        lean_results = row.get("lean_results") or {}
        row_passed_novel = False
        for tac in preds:
            total_candidates += 1
            is_novel = tac not in train_tactics
            if is_novel:
                novel_candidates += 1
            res = lean_results.get(tac)
            if res and res.get("success"):
                verified_candidates += 1
                if is_novel:
                    novel_verified += 1
                    row_passed_novel = True
        if row_passed_novel:
            rows_passed_via_novel += 1

    stats: Dict[str, Any] = {
        "avg_generated_length_top1": (sum(top1_lengths) / n) if n else 0.0,
        "empty_generation_rate": (empty_top1 / n) if n else 0.0,
        "total_candidates": total_candidates,
        "novel_candidate_rate": (novel_candidates / total_candidates) if total_candidates else 0.0,
        "novel_candidates": novel_candidates,
    }
    if verifier_used:
        stats["candidate_invalid_rate"] = (
            1.0 - verified_candidates / total_candidates if total_candidates else 0.0
        )
        stats["verified_candidates"] = verified_candidates
        stats["novel_candidates_verified"] = novel_verified
        stats["rows_passed_via_novel_tactic"] = rows_passed_via_novel
        stats["rows_passed_via_novel_tactic_rate"] = (rows_passed_via_novel / n) if n else 0.0
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
        print(f"error: dataset is empty: {args.dataset}", file=sys.stderr)
        return 2
    train, eval_examples = load_dataset_split(args.dataset, args.split)
    train_tactics = {e.tactic for e in train}
    print(f"loaded {len(full)} examples; train={len(train)} eval[{args.split}]={len(eval_examples)}")

    baseline = ARGenerativeBaseline.load(
        args.model_dir, beam_width=args.beam_width, length_penalty=args.length_penalty,
    )
    print(f"loaded AR model from {args.model_dir}  ({baseline.mode})")

    cache = VerificationCache.load(
        args.output_dir / "verification_cache.json" if args.cache else None, enabled=args.cache,
    )
    verifier = make_lean_cli_verifier(timeout=args.lean_timeout) if args.verify else None

    if not eval_examples:
        from mini_elf_lean.baseline_eval import EvaluationResult
        from mini_elf_lean.baselines import split_summary

        result = EvaluationResult(
            metrics={
                "baseline": baseline.name, "n_examples": 0, "n_theorems": 0,
                "note": f"eval split {args.split!r} is empty",
                "split_diagnostics": split_summary(train, eval_examples),
            },
            predictions=[], failures=[],
        )
        _write_outputs(args.output_dir, result, cache, args.cache)
        print(json.dumps(result.metrics, indent=2, sort_keys=True))
        return 0

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
            print(f"  evaluating {i}/{n}", end="\r", flush=True) if args.verbose else None
        ),
    )
    if args.verbose:
        print()

    result.metrics["ar_generation"] = _ar_generation_stats(
        result.predictions, train_tactics, verifier_used=verifier is not None
    )

    if args.seeds and result.predictions:
        thm2fam, tac2fams = load_family_maps(args.seeds)
        if args.verify:
            result.metrics["per_family_pass_at_k"] = per_family_pass_at_k(
                result.predictions, thm2fam, DEFAULT_KS
            )
        result.metrics["sibling_confusion"] = sibling_confusion(
            result.predictions, thm2fam, tac2fams
        )

    _write_outputs(args.output_dir, result, cache, args.cache)
    print(json.dumps(result.metrics, indent=2, sort_keys=True))
    n = result.metrics["n_examples"]
    if 0 < n <= SMALL_SAMPLE_THRESHOLD:
        print(f"\nNOTE: only {n} eval example(s) — diagnostic, not statistically meaningful.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
