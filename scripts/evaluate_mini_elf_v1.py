"""Evaluate Mini-ELF v1 with real lean-cli ``pass@k``.

Wraps the trained v1 generator (+ reranker + witness augmentation) in
:class:`~mini_elf_lean.elf_v1_sample.MiniElfV1Baseline` and reuses the shared
evaluation harness, so numbers are directly comparable to AR / Mini-ELF v0.

Modes (``--mode``):

  * ``decoder_no_rerank``     — flow decode, ranked by sample frequency (v0-style).
  * ``decoder_rerank``        — flow decode, ranked by the learned reranker.
  * ``decoder_rerank_witness``— flow decode + witness-copy candidates, reranked.
  * ``nn_ablation``           — nearest-neighbour latent decode (retrieval ablation).

Adds v1 metrics on top of the harness: invalid-rate@1/@5, candidate diversity,
novel-verified count, **candidate-source breakdown** (flow_decoder / witness_copy
/ nn_decode, attempted vs verified), reranker-score split for verified vs failed
candidates, per-family pass@k, sibling confusion, and a focused
exists/and_elim/or_intro summary. Theorem-level (``state_after_is_real=false``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
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
from mini_elf_lean.elf_v1_sample import MiniElfV1Baseline  # noqa: E402

MODES = {
    "decoder_no_rerank": dict(decode="decoder", use_reranker=False, use_witness=False),
    "decoder_rerank": dict(decode="decoder", use_reranker=True, use_witness=False),
    "decoder_rerank_witness": dict(decode="decoder", use_reranker=True, use_witness=True),
    "nn_ablation": dict(decode="nn", use_reranker=False, use_witness=False),
}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--model-dir", required=True, type=Path)
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--split", default="val", choices=("train", "val", "test"))
    p.add_argument("--mode", default="decoder_rerank_witness", choices=tuple(MODES))
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--n-samples", type=int, default=64)
    p.add_argument("--flow-steps", type=int, default=10)
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


def _v1_generation_stats(
    predictions: Sequence[Dict[str, Any]], baseline: MiniElfV1Baseline,
    eval_examples, train_tactics: set, verifier_used: bool, k_focus: int = 5,
) -> Dict[str, Any]:
    n = len(predictions)
    top1_lengths: List[int] = []
    empty_top1 = 0
    total_candidates = novel_candidates = verified_candidates = novel_verified = 0
    rows_passed_via_novel = 0
    top1_invalid = top1_total = topk_invalid = topk_total = 0
    by_source = defaultdict(lambda: {"attempted": 0, "verified": 0})
    rerank_scores = {"verified": [], "failed": []}

    for row in predictions:
        preds = row.get("predictions") or []
        prov = row.get("prediction_provenance") or [{} for _ in preds]
        lean_results = row.get("lean_results") or {}
        top1 = preds[0] if preds else ""
        top1_lengths.append(len(top1))
        if not top1.strip():
            empty_top1 += 1

        passed_novel = False
        for i, tac in enumerate(preds):
            source = prov[i].get("source") if i < len(prov) else None
            score = prov[i].get("reranker_score") if i < len(prov) else None
            total_candidates += 1
            novel = tac not in train_tactics
            if novel:
                novel_candidates += 1
            if source:
                by_source[source]["attempted"] += 1
            ok = bool(lean_results.get(tac, {}).get("success"))
            if verifier_used:
                if i == 0:
                    top1_total += 1
                    if not ok:
                        top1_invalid += 1
                if i < k_focus:
                    topk_total += 1
                    if not ok:
                        topk_invalid += 1
                if ok:
                    verified_candidates += 1
                    if source:
                        by_source[source]["verified"] += 1
                    if novel:
                        novel_verified += 1
                        passed_novel = True
                if score is not None:
                    rerank_scores["verified" if ok else "failed"].append(score)
        if passed_novel:
            rows_passed_via_novel += 1

    uniq_per_row = [baseline.distinct_flow_candidates(e) for e in eval_examples]

    stats: Dict[str, Any] = {
        "mode": baseline.mode,
        "n_samples_per_row": baseline.n_samples,
        "avg_generated_length_top1": (sum(top1_lengths) / n) if n else 0.0,
        "empty_generation_rate": (empty_top1 / n) if n else 0.0,
        "avg_distinct_flow_candidates_per_row": (sum(uniq_per_row) / len(uniq_per_row)) if uniq_per_row else 0.0,
        "total_candidates_in_topk": total_candidates,
        "novel_candidate_rate": (novel_candidates / total_candidates) if total_candidates else 0.0,
        "novel_candidates": novel_candidates,
        "candidate_source_breakdown": {s: dict(v) for s, v in sorted(by_source.items())},
    }
    if verifier_used:
        stats["invalid_rate_top1"] = (top1_invalid / top1_total) if top1_total else 0.0
        stats["invalid_rate_top5"] = (topk_invalid / topk_total) if topk_total else 0.0
        stats["candidate_invalid_rate"] = (
            1.0 - verified_candidates / total_candidates if total_candidates else 0.0
        )
        stats["novel_candidates_verified"] = novel_verified
        stats["rows_passed_via_novel_tactic"] = rows_passed_via_novel
        for label in ("verified", "failed"):
            vals = rerank_scores[label]
            stats[f"avg_reranker_score_{label}_candidates"] = (sum(vals) / len(vals)) if vals else None
    return stats


def _family_focus(per_family: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the families v1 specifically targets for an at-a-glance summary."""
    focus = {}
    for fam in ("exists_witness", "and_elim_left", "and_elim_right",
                "or_intro_left", "or_intro_right"):
        e = per_family.get(fam)
        if e:
            focus[fam] = {
                "n_rows": e["n_rows"],
                "pass_at_1": e["pass_at_k"]["1"]["rate"],
                "pass_at_5": e["pass_at_k"]["5"]["rate"],
            }
    return focus


def _write_outputs(out: Path, result, cache: VerificationCache, write_cache: bool,
                   source_summary: Dict[str, Any]) -> None:
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
    (out / "candidate_sources_summary.json").write_text(
        json.dumps(source_summary, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    if write_cache:
        cache.path = out / "verification_cache.json"
        cache.dirty = True
        cache.save()


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    mode_kwargs = MODES[args.mode]

    full = load_dataset(args.dataset)
    if not full:
        print(f"error: dataset empty: {args.dataset}", file=sys.stderr)
        return 2
    train, eval_examples = load_dataset_split(args.dataset, args.split)
    train_tactics = {e.tactic for e in train}
    print(f"loaded {len(full)} examples; train={len(train)} eval[{args.split}]={len(eval_examples)}")

    baseline = MiniElfV1Baseline.load(
        args.model_dir, n_samples=args.n_samples, steps=args.flow_steps,
        seed=args.seed, **mode_kwargs,
    )
    print(f"loaded Mini-ELF v1 ({args.mode}) from {args.model_dir}  ({baseline.mode})")

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
        _write_outputs(args.output_dir, result, cache, args.cache, {})
        print(json.dumps(result.metrics, indent=2, sort_keys=True))
        return 0

    result = evaluate(
        baseline, train=train, eval_examples=eval_examples, full_dataset=full,
        k_values=DEFAULT_KS, top_k=args.top_k, verifier=verifier, cache=cache,
        progress=lambda i, n: (print(f"  evaluating {i}/{n}", end="\r", flush=True) if args.verbose else None),
    )
    if args.verbose:
        print()

    result.metrics["mode"] = args.mode
    result.metrics["elf_v1_generation"] = _v1_generation_stats(
        result.predictions, baseline, eval_examples, train_tactics, verifier_used=verifier is not None
    )

    if args.seeds and result.predictions:
        thm2fam, tac2fams = load_family_maps(args.seeds)
        if args.verify:
            pf = per_family_pass_at_k(result.predictions, thm2fam, DEFAULT_KS)
            result.metrics["per_family_pass_at_k"] = pf
            result.metrics["family_focus"] = _family_focus(pf)
        result.metrics["sibling_confusion"] = sibling_confusion(result.predictions, thm2fam, tac2fams)

    _write_outputs(args.output_dir, result, cache, args.cache,
                   result.metrics["elf_v1_generation"].get("candidate_source_breakdown", {}))
    print(json.dumps(result.metrics, indent=2, sort_keys=True))
    n = result.metrics["n_examples"]
    if 0 < n <= SMALL_SAMPLE_THRESHOLD:
        print(f"\nNOTE: only {n} eval example(s) — diagnostic, not statistically meaningful.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
