"""Evaluate Mini-ELF v6 (structure-aware retrieval) with real lean-cli pass@k.

v6 keeps everything from v5 and swaps the char-similarity retrieval ranking for a
**structure-aware** scorer (`StructureAwareRetrievalProposer`) plus an
adapted-candidate preference. It re-ranks the *same* candidate set; it does not
add proof templates. Configs (`--config`):

  * ``v5_retrieval``        — v5 char-similarity retrieval alone (baseline).
  * ``v6_retrieval``        — v6 structure-aware retrieval alone.
  * ``v5_fusion``           — v3 ⊕ v5 retrieval.
  * ``v6_fusion``           — v3 ⊕ v6 retrieval.
  * ``v6_no_structure``     — v3 ⊕ v6 retrieval, structural terms OFF (ablation).
  * ``v6_no_adapt_pref``    — v3 ⊕ v6 retrieval, adapted-preference OFF (ablation).

Same `family_interpolation` split as v5 for comparability. Theorem-level lean-cli
verification only (`state_after_is_real=false`); no `state_after`; manual-oracle
candidates never wired in.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mini_elf_lean.baseline_eval import (  # noqa: E402
    DEFAULT_KS, SMALL_SAMPLE_THRESHOLD, VerificationCache, evaluate,
    load_family_maps, make_lean_cli_verifier, per_family_pass_at_k,
)
from mini_elf_lean.baselines import load_dataset, load_dataset_split  # noqa: E402
from mini_elf_lean.elf_v5_sample import MiniElfV5Baseline  # noqa: E402
from mini_elf_lean.retrieval_proposer import (  # noqa: E402
    RetrievalProofBlockProposer, StructureAwareRetrievalProposer, load_v6_weights,
)

from evaluate_mini_elf_v1 import (  # noqa: E402
    _family_focus, _load_difficulty_map, _per_difficulty_pass_at_k, _write_outputs,
)
from evaluate_mini_elf_v5 import _v5_stats, _load_v3  # noqa: E402

CONFIGS = ("v5_retrieval", "v6_retrieval", "v5_fusion", "v6_fusion",
           "v6_no_structure", "v6_no_adapt_pref")


def build_baseline(args) -> MiniElfV5Baseline:
    cfg = args.config
    weights = load_v6_weights(args.weights)
    v5_ret = RetrievalProofBlockProposer(neighbors=args.retrieval_neighbors)
    if cfg == "v5_retrieval":
        return MiniElfV5Baseline(v3=None, proposers=[v5_ret])
    if cfg == "v6_retrieval":
        return MiniElfV5Baseline(v3=None, proposers=[StructureAwareRetrievalProposer(weights=weights)])
    if cfg == "v5_fusion":
        return MiniElfV5Baseline(v3=_load_v3(args, templates=False), proposers=[v5_ret])
    if cfg == "v6_fusion":
        return MiniElfV5Baseline(v3=_load_v3(args, templates=False),
                                 proposers=[StructureAwareRetrievalProposer(weights=weights)])
    if cfg == "v6_no_structure":
        return MiniElfV5Baseline(v3=_load_v3(args, templates=False),
                                 proposers=[StructureAwareRetrievalProposer(weights=weights, enable_structural=False)])
    if cfg == "v6_no_adapt_pref":
        return MiniElfV5Baseline(v3=_load_v3(args, templates=False),
                                 proposers=[StructureAwareRetrievalProposer(weights=weights, enable_adapt_preference=False)])
    raise ValueError(f"unknown config {cfg!r}")


def _v6_extra_stats(predictions: Sequence[Dict[str, Any]], verifier_used: bool) -> Dict[str, Any]:
    """Adapted-candidate ranking metrics on top of `_v5_stats` (the F1 fix)."""
    adapted_verified = adapted_top1 = adapted_top1_verified = rows = 0
    for row in predictions:
        rows += 1
        preds = row.get("predictions") or []
        prov = row.get("prediction_provenance") or [{} for _ in preds]
        lean = row.get("lean_results") or {}
        for i, tac in enumerate(preds):
            meta = (prov[i].get("metadata") if i < len(prov) else {}) or {}
            is_adapted = bool(meta.get("adapted")) or (prov[i].get("source") == "retrieval_adapted")
            ok = bool(lean.get(tac, {}).get("success")) if verifier_used else False
            if is_adapted and ok:
                adapted_verified += 1
            if i == 0 and is_adapted:
                adapted_top1 += 1
                if ok:
                    adapted_top1_verified += 1
    return {
        "adapted_candidate_verified": adapted_verified,
        "adapted_candidate_top1": adapted_top1,
        "adapted_candidate_top1_verified": adapted_top1_verified,
        "adapted_candidate_top1_rate": (adapted_top1 / rows) if rows else 0.0,
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--config", required=True, choices=CONFIGS)
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--model-dir", type=Path, default=None)
    p.add_argument("--weights", type=Path, default=ROOT / "data" / "configs" / "v6_retrieval.json")
    p.add_argument("--split", default="test", choices=("train", "val", "test"))
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--n-samples", type=int, default=64)
    p.add_argument("--flow-steps", type=int, default=10)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--planner-max", type=int, default=24)
    p.add_argument("--retrieval-neighbors", type=int, default=24)
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
    needs_v3 = args.config in ("v5_fusion", "v6_fusion", "v6_no_structure", "v6_no_adapt_pref")
    if needs_v3 and args.model_dir is None:
        print(f"error: config {args.config!r} needs --model-dir (a v2 model)", file=sys.stderr)
        return 2

    full = load_dataset(args.dataset)
    if not full:
        print(f"error: dataset empty: {args.dataset}", file=sys.stderr)
        return 2
    train, eval_examples = load_dataset_split(args.dataset, args.split)
    train_tactics = {e.tactic for e in train}
    print(f"loaded {len(full)} examples; train={len(train)} eval[{args.split}]={len(eval_examples)}")

    baseline = build_baseline(args).fit(train)
    print(f"config={args.config}  ({baseline.mode})")

    cache = VerificationCache.load(
        args.output_dir / "verification_cache.json" if args.cache else None, enabled=args.cache)
    verifier = make_lean_cli_verifier(timeout=args.lean_timeout) if args.verify else None

    result = evaluate(
        baseline, train=train, eval_examples=eval_examples, full_dataset=full,
        k_values=DEFAULT_KS, top_k=args.top_k, verifier=verifier, cache=cache,
        progress=lambda i, n: (print(f"  evaluating {i}/{n}", end="\r", flush=True) if args.verbose else None),
    )
    if args.verbose:
        print()

    result.metrics["mode"] = baseline.mode
    result.metrics["config"] = args.config
    stats = _v5_stats(result.predictions, baseline, eval_examples, train_tactics, verifier_used=verifier is not None)
    stats.update(_v6_extra_stats(result.predictions, verifier_used=verifier is not None))
    result.metrics["mini_elf_v6"] = stats

    if args.seeds and result.predictions and args.verify:
        thm2fam, _ = load_family_maps(args.seeds)
        pf = per_family_pass_at_k(result.predictions, thm2fam, DEFAULT_KS)
        result.metrics["per_family_pass_at_k"] = pf
        result.metrics["family_focus"] = _family_focus(pf)
        thm2diff = _load_difficulty_map(args.seeds)
        if thm2diff:
            result.metrics["per_difficulty_pass_at_k"] = _per_difficulty_pass_at_k(result.predictions, thm2diff, DEFAULT_KS)

    _write_outputs(args.output_dir, result, cache, args.cache, stats["candidate_source_breakdown"])
    print(json.dumps(result.metrics, indent=2, sort_keys=True))
    n = result.metrics["n_examples"]
    if 0 < n <= SMALL_SAMPLE_THRESHOLD:
        print(f"\nNOTE: only {n} eval example(s) — diagnostic, not statistically meaningful.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
