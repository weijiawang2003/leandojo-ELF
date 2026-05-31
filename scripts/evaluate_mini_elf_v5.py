"""Evaluate Mini-ELF v5 candidate-proposer configurations with real lean-cli pass@k.

v5 keeps the v3 system unchanged and adds data-driven proposers (retrieval / LLM
/ learned). This evaluator builds one of several **clearly-labelled** configs and
runs it through the shared harness, so numbers are directly comparable to v1–v4.

Configs (``--config``):

  * ``v3``                  — v3 unchanged (planner ⊕ witness ⊕ flow). Baseline.
  * ``v4_templates``        — v3 + the explicitly-labelled v4 negation/∃-elim
                              templates (the v4 ablation, re-run on this split).
  * ``retrieval``           — retrieval proposer alone (+ light adaptation).
  * ``retrieval_verbatim``  — retrieval alone, adaptation OFF (ablation).
  * ``v3_retrieval``        — v3 ⊕ retrieval (the v5 fusion).
  * ``v3_retrieval_v4templates`` — v3 + v4 templates ⊕ retrieval (labelled).
  * ``llm``                 — LLM proposer alone (skips cleanly if no API key).
  * ``v3_retrieval_llm``    — v3 ⊕ retrieval ⊕ LLM.
  * ``learned`` / ``v3_retrieval_learned`` — uses the trained proof-block model
                              if present (skips with a note otherwise).

Manual-oracle candidates are **never** wired into any config — they are
audit-only. Theorem-level verification only (``state_after_is_real=false``); no
``state_after`` is read; not full ELF.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

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
)
from mini_elf_lean.baselines import load_dataset, load_dataset_split  # noqa: E402
from mini_elf_lean.elf_v3_sample import MiniElfV3Baseline  # noqa: E402
from mini_elf_lean.elf_v5_sample import MiniElfV5Baseline  # noqa: E402
from mini_elf_lean.proposer import RetrievalProofBlockProposer, LLMProposer  # noqa: E402

from evaluate_mini_elf_v1 import (  # noqa: E402
    _family_focus,
    _load_difficulty_map,
    _per_difficulty_pass_at_k,
    _write_outputs,
)

# Sources that are *new in v5* (a proposer produced them), vs the existing
# symbolic/flow sources from v3. Used for the "verified, not from planner/
# witness-copy/flow" attribution the brief asks for.
PROPOSER_SOURCES = {"retrieval", "retrieval_adapted", "llm_proposer", "learned_proposer"}
SYMBOLIC_PREFIXES = ("planner_", "witness_copy")
FLOW_SOURCE = "flow_decoder"

CONFIGS = (
    "v3", "v4_templates", "retrieval", "retrieval_verbatim",
    "v3_retrieval", "v3_retrieval_v4templates", "llm", "v3_retrieval_llm",
    "learned", "v3_retrieval_learned",
)


def _load_v3(args, *, templates: bool) -> MiniElfV3Baseline:
    return MiniElfV3Baseline.load(
        args.model_dir, n_samples=args.n_samples, steps=args.flow_steps, seed=args.seed,
        use_witness=True, use_reranker=True, use_planner=True, planner_max=args.planner_max,
        enable_negation_templates=templates, enable_exists_elim_templates=templates,
    )


def _make_learned(args):
    """Construct the learned proof-block proposer if its module + model exist;
    otherwise return None and let the caller note the skip (never crash)."""
    try:
        from mini_elf_lean.proof_block_model import LearnedProofBlockProposer
    except Exception:  # noqa: BLE001 - module optional
        return None
    model_dir = args.learned_model_dir
    if model_dir is None or not Path(model_dir).exists():
        return None
    try:
        return LearnedProofBlockProposer.load(Path(model_dir), beam=args.learned_beam)
    except Exception as exc:  # noqa: BLE001
        print(f"warning: could not load learned proposer from {model_dir}: {exc}", file=sys.stderr)
        return None


def build_baseline(args) -> MiniElfV5Baseline:
    cfg = args.config
    retrieval = RetrievalProofBlockProposer(neighbors=args.retrieval_neighbors)
    retrieval_verbatim = RetrievalProofBlockProposer(
        neighbors=args.retrieval_neighbors, enable_numeric_adapt=False, enable_hyp_remap=False)
    llm = LLMProposer(backend=args.llm_backend, model=args.llm_model)

    if cfg == "v3":
        return MiniElfV5Baseline(v3=_load_v3(args, templates=False), proposers=[])
    if cfg == "v4_templates":
        return MiniElfV5Baseline(v3=_load_v3(args, templates=True), proposers=[])
    if cfg == "retrieval":
        return MiniElfV5Baseline(v3=None, proposers=[retrieval])
    if cfg == "retrieval_verbatim":
        return MiniElfV5Baseline(v3=None, proposers=[retrieval_verbatim])
    if cfg == "v3_retrieval":
        return MiniElfV5Baseline(v3=_load_v3(args, templates=False), proposers=[retrieval])
    if cfg == "v3_retrieval_v4templates":
        return MiniElfV5Baseline(v3=_load_v3(args, templates=True), proposers=[retrieval])
    if cfg == "llm":
        return MiniElfV5Baseline(v3=None, proposers=[llm])
    if cfg == "v3_retrieval_llm":
        return MiniElfV5Baseline(v3=_load_v3(args, templates=False), proposers=[retrieval, llm])
    if cfg == "learned":
        learned = _make_learned(args)
        if learned is None:
            print("note: learned proof-block proposer unavailable (see docs/V5_LEARNED_PROPOSER.md); "
                  "config 'learned' produces no candidates.", file=sys.stderr)
        return MiniElfV5Baseline(v3=None, proposers=[learned] if learned else [])
    if cfg == "v3_retrieval_learned":
        learned = _make_learned(args)
        if learned is None:
            print("note: learned proposer unavailable; falling back to v3 ⊕ retrieval.", file=sys.stderr)
        props = [retrieval] + ([learned] if learned else [])
        return MiniElfV5Baseline(v3=_load_v3(args, templates=False), proposers=props)
    raise ValueError(f"unknown config {cfg!r}")


def _source_class(source: Optional[str]) -> str:
    if source in PROPOSER_SOURCES:
        return "proposer"
    if source == FLOW_SOURCE:
        return "flow"
    if source and source.startswith(SYMBOLIC_PREFIXES):
        return "symbolic"
    return "other"


def _v5_stats(predictions: Sequence[Dict[str, Any]], baseline: MiniElfV5Baseline,
              eval_examples, train_tactics: set, verifier_used: bool) -> Dict[str, Any]:
    by_source: Dict[str, Dict[str, int]] = defaultdict(lambda: {"attempted": 0, "verified": 0})
    adapt_verified: Dict[str, int] = defaultdict(int)
    total = verified = novel = novel_verified = 0
    proposer_verified = 0
    rows_via_proposer = rows_only_proposer = 0
    top1_invalid = top1_total = 0
    distinct_per_row: List[int] = []
    distinct_sources_per_row: List[int] = []
    top1_len: List[int] = []
    cand_len: List[int] = []
    multiline = 0

    for row in predictions:
        preds = row.get("predictions") or []
        prov = row.get("prediction_provenance") or [{} for _ in preds]
        lean = row.get("lean_results") or {}
        distinct_per_row.append(len(set(preds)))
        distinct_sources_per_row.append(len({(prov[i].get("source") if i < len(prov) else None) for i in range(len(preds))}))
        if preds:
            top1_len.append(len(preds[0]))
        any_sym = any_flow = any_prop = False
        for i, tac in enumerate(preds):
            source = prov[i].get("source") if i < len(prov) else None
            meta = prov[i].get("metadata") if i < len(prov) else {}
            cls = _source_class(source)
            total += 1
            cand_len.append(len(tac))
            if "\n" in tac:
                multiline += 1
            is_novel = tac not in train_tactics
            if is_novel:
                novel += 1
            if source:
                by_source[source]["attempted"] += 1
            ok = bool(lean.get(tac, {}).get("success")) if verifier_used else False
            if verifier_used and i == 0:
                top1_total += 1
                if not ok:
                    top1_invalid += 1
            if ok:
                verified += 1
                if source:
                    by_source[source]["verified"] += 1
                if is_novel:
                    novel_verified += 1
                if cls == "symbolic":
                    any_sym = True
                elif cls == "flow":
                    any_flow = True
                elif cls == "proposer":
                    any_prop = True
                    proposer_verified += 1
                    if source == "retrieval_adapted" and isinstance(meta, dict):
                        adapt_verified[meta.get("adaptation", "?")] += 1
        if verifier_used:
            if any_prop:
                rows_via_proposer += 1
            if any_prop and not (any_sym or any_flow):
                rows_only_proposer += 1

    n = len(eval_examples)
    stats: Dict[str, Any] = {
        "mode": baseline.mode,
        "candidate_source_breakdown": {s: dict(v) for s, v in sorted(by_source.items())},
        "total_candidates_in_topk": total,
        "avg_distinct_candidates_per_row": (sum(distinct_per_row) / n) if n else 0.0,
        "avg_distinct_sources_per_row": (sum(distinct_sources_per_row) / n) if n else 0.0,
        "avg_proposer_candidates_per_row": (
            sum(baseline.proposer_candidate_count(e) for e in eval_examples) / n) if n else 0.0,
        "novel_candidate_rate": (novel / total) if total else 0.0,
        "proof_block_length": {
            "avg_top1": (sum(top1_len) / len(top1_len)) if top1_len else 0.0,
            "avg_candidate": (sum(cand_len) / len(cand_len)) if cand_len else 0.0,
            "multiline_rate": (multiline / total) if total else 0.0,
        },
    }
    if verifier_used:
        stats.update({
            "candidate_invalid_rate": (1.0 - verified / total) if total else 0.0,
            "invalid_rate_top1": (top1_invalid / top1_total) if top1_total else 0.0,
            "verified_candidates": verified,
            "novel_verified": novel_verified,
            "proposer_verified_candidates": proposer_verified,
            "rows_solved_via_proposer": rows_via_proposer,
            "rows_solved_only_by_proposer": rows_only_proposer,
            "rows_solved_only_by_proposer_rate": (rows_only_proposer / n) if n else 0.0,
            "verified_by_adaptation": dict(adapt_verified),
        })
    return stats


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--config", required=True, choices=CONFIGS)
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--model-dir", type=Path, default=None,
                   help="v2 model dir (required for any config that includes v3).")
    p.add_argument("--split", default="test", choices=("train", "val", "test"))
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--n-samples", type=int, default=64)
    p.add_argument("--flow-steps", type=int, default=10)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--planner-max", type=int, default=24)
    p.add_argument("--retrieval-neighbors", type=int, default=24)
    p.add_argument("--llm-backend", default="auto")
    p.add_argument("--llm-model", default=None)
    p.add_argument("--learned-model-dir", type=Path, default=None)
    p.add_argument("--learned-beam", type=int, default=8)
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

    needs_v3 = args.config in ("v3", "v4_templates", "v3_retrieval",
                               "v3_retrieval_v4templates", "v3_retrieval_llm", "v3_retrieval_learned")
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
    # Surface LLM skip clearly.
    for p in baseline.proposers:
        if isinstance(p, LLMProposer):
            print(f"  LLMProposer status: {p.status()}")

    cache = VerificationCache.load(
        args.output_dir / "verification_cache.json" if args.cache else None, enabled=args.cache,
    )
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
    result.metrics["mini_elf_v5"] = _v5_stats(
        result.predictions, baseline, eval_examples, train_tactics, verifier_used=verifier is not None
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

    _write_outputs(args.output_dir, result, cache, args.cache,
                   result.metrics["mini_elf_v5"]["candidate_source_breakdown"])
    print(json.dumps(result.metrics, indent=2, sort_keys=True))
    n = result.metrics["n_examples"]
    if 0 < n <= SMALL_SAMPLE_THRESHOLD:
        print(f"\nNOTE: only {n} eval example(s) — diagnostic, not statistically meaningful.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
