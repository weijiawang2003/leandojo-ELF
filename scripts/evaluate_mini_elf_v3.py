"""Evaluate Mini-ELF v3 (structured planner ⊕ v2 model) with real lean-cli pass@k.

v3 reuses a trained ``combined_lean_cli_mini_elf_v2*`` model (flow generator +
verifier-aware reranker + witness-copy) and adds the symbolic proof-block
planner (:mod:`mini_elf_lean.proof_planner`) as a new candidate source. This
evaluator wraps :class:`~mini_elf_lean.elf_v3_sample.MiniElfV3Baseline` in the
shared harness, so numbers are directly comparable to v1-transfer and v2.

On top of the v1/v2 generation stats it reports **planner-specific** metrics:
candidates generated per theorem, per-strategy attempted/verified, rows whose
top-1 verified came from the planner, and rows the planner solves that the flow
generator does not (the compositional-generalization contribution).

Use ``--no-planner`` to reproduce the pure-v2 numbers through the same harness
(ablation). Theorem-level only (``state_after_is_real=false``); the planner is
symbolic/heuristic, not neural generation; not full ELF.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

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
from mini_elf_lean.elf_v3_sample import MiniElfV3Baseline  # noqa: E402
from mini_elf_lean.elf_v1_sample import FLOW_SOURCE  # noqa: E402
from mini_elf_lean.proof_planner import PLANNER_SOURCES  # noqa: E402

from evaluate_mini_elf_v1 import (  # noqa: E402
    _family_focus,
    _load_difficulty_map,
    _per_difficulty_pass_at_k,
    _v1_generation_stats,
    _write_outputs,
)


def _planner_stats(predictions, baseline, eval_examples, verifier_used: bool) -> Dict[str, Any]:
    """Planner-attributable metrics: generation volume, per-strategy verified
    counts, and the compositional contribution (rows the planner solves)."""
    planner_sources = set(PLANNER_SOURCES)
    per_row = [baseline.planner_candidate_count(e) for e in eval_examples]
    by_strategy: Dict[str, Dict[str, int]] = defaultdict(lambda: {"attempted": 0, "verified": 0})
    by_source: Dict[str, Dict[str, int]] = defaultdict(lambda: {"attempted": 0, "verified": 0})
    rows_planner_top1_verified = 0
    rows_passed_via_planner = 0
    rows_solved_only_by_planner = 0

    for row in predictions:
        preds = row.get("predictions") or []
        prov = row.get("prediction_provenance") or []
        lean = row.get("lean_results") or {}
        planner_ok = flow_ok = False
        for i, tac in enumerate(preds):
            p = prov[i] if i < len(prov) else {}
            source = p.get("source")
            strat = p.get("strategy") or "?"
            ok = bool(lean.get(tac, {}).get("success"))
            if source in planner_sources:
                by_strategy[strat]["attempted"] += 1
                by_source[source]["attempted"] += 1
                if verifier_used and ok:
                    by_strategy[strat]["verified"] += 1
                    by_source[source]["verified"] += 1
                    planner_ok = True
                    if i == 0:
                        rows_planner_top1_verified += 1
            elif source == FLOW_SOURCE and verifier_used and ok:
                flow_ok = True
        if verifier_used:
            if planner_ok:
                rows_passed_via_planner += 1
            if planner_ok and not flow_ok:
                rows_solved_only_by_planner += 1

    n = len(eval_examples)
    out: Dict[str, Any] = {
        "use_planner": baseline.use_planner,
        "avg_planner_candidates_per_row": (sum(per_row) / len(per_row)) if per_row else 0.0,
        "max_planner_candidates_per_row": max(per_row) if per_row else 0,
        "rows_with_any_planner_candidate": sum(1 for c in per_row if c > 0),
        "planner_by_strategy": {k: dict(v) for k, v in sorted(by_strategy.items())},
        "planner_by_source": {k: dict(v) for k, v in sorted(by_source.items())},
    }
    if verifier_used:
        out["rows_planner_top1_verified"] = rows_planner_top1_verified
        out["rows_passed_via_planner"] = rows_passed_via_planner
        out["rows_solved_only_by_planner"] = rows_solved_only_by_planner
        out["rows_passed_via_planner_rate"] = (rows_passed_via_planner / n) if n else 0.0
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--model-dir", required=True, type=Path)
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--split", default="test", choices=("train", "val", "test"))
    p.add_argument("--no-planner", dest="use_planner", action="store_false",
                   help="ablation: disable the planner (reproduce pure-v2 numbers)")
    p.add_argument("--no-witness", dest="use_witness", action="store_false")
    p.add_argument("--no-reranker", dest="use_reranker", action="store_false")
    p.set_defaults(use_planner=True, use_witness=True, use_reranker=True)
    p.add_argument("--enable-negation-templates", action="store_true",
                   help="V4 ablation: add the optional planner_negation templates.")
    p.add_argument("--enable-exists-elim-templates", action="store_true",
                   help="V4 ablation: add the optional planner_exists_elim templates.")
    p.add_argument("--planner-max", type=int, default=24)
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


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    full = load_dataset(args.dataset)
    if not full:
        print(f"error: dataset empty: {args.dataset}", file=sys.stderr)
        return 2
    train, eval_examples = load_dataset_split(args.dataset, args.split)
    train_tactics = {e.tactic for e in train}
    print(f"loaded {len(full)} examples; train={len(train)} eval[{args.split}]={len(eval_examples)}")

    baseline = MiniElfV3Baseline.load(
        args.model_dir, n_samples=args.n_samples, steps=args.flow_steps, seed=args.seed,
        use_witness=args.use_witness, use_reranker=args.use_reranker,
        use_planner=args.use_planner, planner_max=args.planner_max,
        enable_negation_templates=args.enable_negation_templates,
        enable_exists_elim_templates=args.enable_exists_elim_templates,
    )
    print(f"loaded Mini-ELF v3 from {args.model_dir}  ({baseline.mode})")

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

    result.metrics["mode"] = baseline.mode
    result.metrics["elf_v1_generation"] = _v1_generation_stats(
        result.predictions, baseline, eval_examples, train_tactics, verifier_used=verifier is not None
    )
    result.metrics["mini_elf_v3_planner"] = _planner_stats(
        result.predictions, baseline, eval_examples, verifier_used=verifier is not None
    )

    if args.seeds and result.predictions:
        thm2fam, tac2fams = load_family_maps(args.seeds)
        if args.verify:
            pf = per_family_pass_at_k(result.predictions, thm2fam, DEFAULT_KS)
            result.metrics["per_family_pass_at_k"] = pf
            result.metrics["family_focus"] = _family_focus(pf)
            thm2diff = _load_difficulty_map(args.seeds)
            if thm2diff:
                result.metrics["per_difficulty_pass_at_k"] = _per_difficulty_pass_at_k(
                    result.predictions, thm2diff, DEFAULT_KS
                )
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
