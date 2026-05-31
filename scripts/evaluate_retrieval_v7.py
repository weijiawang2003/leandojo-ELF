"""V7 Part 3 — evaluate retrieval under donor scarcity (real lean-cli pass@k).

Runs a small matrix of retrieval configs across the v7 donor-scarcity splits and
reports the *gradient* of pass@k as same-family / same-operation donors are
removed. Leave-one-out splits (family/operation holdout) are evaluated per fold
and **pooled** (each held-out theorem scored once in its unseen condition).

Configs (retrieval-only; v3 off so this isolates the proposer):
  * ``v5_retrieval``         — v5 char-similarity retrieval (baseline).
  * ``v6_retrieval``         — v6 structure-aware retrieval.
  * ``v6_no_same_family``    — v6, same-family donors forbidden at retrieval time.
  * ``v6_no_same_operation`` — v6, same-operation donors forbidden at retrieval time.
  * ``v7_abstract``          — v6 + operation-abstraction cross-family re-ranker (Part 4).

Per run metrics: pass@1/3/5, per-family / per-operation pass@5, same-family donor
rate, cross-family / cross-operation / adapted verified counts, donorless pass@5,
invalid@1, and a donor-condition failure taxonomy. Verification is cache-backed
and keyed by `(theorem_name, tactic)`, shared across runs. No `state_after`; no
new templates; example reuse + ranking, not reasoning.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_elf_lean.baseline_eval import (  # noqa: E402
    DEFAULT_KS, VerificationCache, evaluate, make_lean_cli_verifier,
)
from mini_elf_lean.baselines import load_dataset, load_dataset_split  # noqa: E402
from mini_elf_lean.elf_v5_sample import MiniElfV5Baseline  # noqa: E402
from mini_elf_lean.io_utils import read_jsonl  # noqa: E402
from mini_elf_lean.retrieval_features import OP_UNKNOWN, extract_features  # noqa: E402
from mini_elf_lean.retrieval_proposer import (  # noqa: E402
    RetrievalProofBlockProposer, StructureAwareRetrievalProposer, load_v6_weights,
)

CONFIGS = ("v5_retrieval", "v6_retrieval", "v6_no_same_family", "v6_no_same_operation", "v7_abstract")


def family_map_from_seeds(seeds: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in read_jsonl(seeds):
        m = row.get("metadata") or {}
        if row.get("theorem_name") and m.get("pattern_family"):
            out[row["theorem_name"]] = m["pattern_family"]
    return out


def operation_map(rows) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for r in rows:
        out.setdefault(r.theorem_name, extract_features(r.theorem_statement, r.state_before).required_operation)
    return out


def make_proposer(config: str, weights: Dict[str, float], family_map: Dict[str, str]):
    if config == "v5_retrieval":
        return RetrievalProofBlockProposer(neighbors=24)
    if config == "v6_retrieval":
        return StructureAwareRetrievalProposer(weights=weights, family_map=family_map)
    if config == "v6_no_same_family":
        return StructureAwareRetrievalProposer(weights=weights, family_map=family_map, forbid_same_family=True)
    if config == "v6_no_same_operation":
        return StructureAwareRetrievalProposer(weights=weights, family_map=family_map, forbid_same_operation=True)
    if config == "v7_abstract":
        from mini_elf_lean.retrieval_abstraction_proposer import AbstractionAwareRetrievalProposer
        return AbstractionAwareRetrievalProposer(weights=weights, family_map=family_map)
    raise ValueError(f"unknown config {config!r}")


# ---------------- per-row annotation + metrics ----------------


def _neighbor(prov: Dict[str, Any]) -> Optional[str]:
    return (prov.get("metadata") or {}).get("neighbor_theorem")


def _first_verified_index(row: Dict[str, Any]) -> int:
    lean = row.get("lean_results") or {}
    for i, tac in enumerate(row.get("predictions") or []):
        if lean.get(tac, {}).get("success"):
            return i
    return -1


def annotate_rows(rows: List[Dict[str, Any]], thm2fam, thm2op,
                  train_families: set, train_ops: set, held_label: str) -> None:
    """Add v7 donor-condition fields to each prediction row in place."""
    for row in rows:
        name = row["theorem_name"]
        fam = thm2fam.get(name)
        op = thm2op.get(name, OP_UNKNOWN)
        prov = row.get("prediction_provenance") or []
        row["_family"] = fam
        row["_operation"] = op
        row["_held"] = held_label
        row["_same_family_in_train"] = fam in train_families if fam else False
        row["_same_operation_in_train"] = (op in train_ops) if op != OP_UNKNOWN else False
        # rank-0 donor family
        rank0_donor = _neighbor(prov[0]) if prov else None
        row["_rank0_donor_family"] = thm2fam.get(rank0_donor) if rank0_donor else None
        row["_rank0_same_family"] = (row["_rank0_donor_family"] == fam) if fam else False
        # first verified candidate's donor + adaptation
        fv = _first_verified_index(row)
        row["_verified5"] = fv >= 0
        row["_verified1"] = fv == 0
        if fv >= 0:
            fprov = prov[fv] if fv < len(prov) else {}
            donor = _neighbor(fprov)
            row["_verified_donor_family"] = thm2fam.get(donor) if donor else None
            row["_verified_donor_operation"] = (fprov.get("metadata") or {}).get("donor_operation")
            row["_verified_cross_family"] = (row["_verified_donor_family"] != fam) if fam else False
            row["_verified_cross_operation"] = (
                row["_verified_donor_operation"] not in (None, op))
            row["_verified_adapted"] = bool((fprov.get("metadata") or {}).get("adapted")) \
                or (fprov.get("source") == "retrieval_adapted")
        else:
            row["_verified_donor_family"] = None
            row["_verified_cross_family"] = False
            row["_verified_cross_operation"] = False
            row["_verified_adapted"] = False


def _rate(n: int, d: int) -> float:
    return round(n / d, 4) if d else 0.0


def _passk_by(rows: List[Dict[str, Any]], keyfn) -> Dict[str, Any]:
    by: Dict[Any, Dict[str, int]] = defaultdict(lambda: {"n": 0, "p1": 0, "p3": 0, "p5": 0})
    for r in rows:
        k = keyfn(r)
        pk = r.get("lean_pass_at_k", {})
        by[k]["n"] += 1
        by[k]["p1"] += int(pk.get("1", False))
        by[k]["p3"] += int(pk.get("3", False))
        by[k]["p5"] += int(pk.get("5", False))
    return {str(k): {"n": v["n"], "pass@1": _rate(v["p1"], v["n"]),
                     "pass@3": _rate(v["p3"], v["n"]), "pass@5": _rate(v["p5"], v["n"])}
            for k, v in sorted(by.items(), key=lambda kv: str(kv[0]))}


def v7_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    p1 = sum(int(r.get("lean_pass_at_k", {}).get("1", False)) for r in rows)
    p3 = sum(int(r.get("lean_pass_at_k", {}).get("3", False)) for r in rows)
    p5 = sum(int(r.get("lean_pass_at_k", {}).get("5", False)) for r in rows)
    donorless = [r for r in rows if not r["_same_family_in_train"]]
    fail5 = [r for r in rows if not r["_verified5"]]
    # failure taxonomy by donor condition
    tax = Counter()
    for r in fail5:
        if not (r.get("predictions")):
            tax["no_candidates"] += 1
        elif r["_same_family_in_train"]:
            tax["same_family_present_but_failed"] += 1
        elif r["_same_operation_in_train"]:
            tax["cross_family_same_operation_donor_only"] += 1
        else:
            tax["no_same_operation_donor"] += 1
    return {
        "n_rows": n,
        "n_theorems": len({r["theorem_name"] for r in rows}),
        "pass@1": _rate(p1, n), "pass@3": _rate(p3, n), "pass@5": _rate(p5, n),
        "invalid@1": _rate(n - p1, n),
        "same_family_donor_rate": _rate(sum(r["_rank0_same_family"] for r in rows), n),
        "rows_same_family_in_train": sum(r["_same_family_in_train"] for r in rows),
        "rows_same_operation_in_train": sum(r["_same_operation_in_train"] for r in rows),
        "donorless_same_family_rows": len(donorless),
        "donorless_pass@5": _rate(sum(r["_verified5"] for r in donorless), len(donorless)),
        "cross_family_verified": sum(r["_verified_cross_family"] for r in rows),
        "cross_operation_verified": sum(r["_verified_cross_operation"] for r in rows),
        "adapted_verified": sum(r["_verified_adapted"] for r in rows),
        "per_family_pass_at_k": _passk_by(rows, lambda r: r["_family"]),
        "per_operation_pass_at_k": _passk_by(rows, lambda r: r["_operation"]),
        "failure_taxonomy": dict(tax),
    }


# ---------------- run orchestration ----------------


def _run_dataset(config, dataset: Path, weights, family_map, thm2fam, thm2op,
                 cache, verifier, top_k, held_label) -> List[Dict[str, Any]]:
    full = load_dataset(dataset)
    train, test = load_dataset_split(dataset, "test")
    if not test:
        return []
    train_families = {thm2fam.get(e.theorem_name) for e in train} - {None}
    train_ops = {thm2op.get(e.theorem_name, OP_UNKNOWN) for e in train} - {OP_UNKNOWN}
    baseline = MiniElfV5Baseline(v3=None, proposers=[make_proposer(config, weights, family_map)]).fit(train)
    result = evaluate(baseline, train=train, eval_examples=test, full_dataset=full,
                      k_values=DEFAULT_KS, top_k=top_k, verifier=verifier, cache=cache)
    annotate_rows(result.predictions, thm2fam, thm2op, train_families, train_ops, held_label)
    return result.predictions


def run_split(config, split_name, base_dir: Path, weights, family_map, thm2fam, thm2op,
              cache, verifier, top_k) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Run one config on one split. Folds (manifest.json present) are pooled."""
    manifest = base_dir / "manifest.json"
    rows: List[Dict[str, Any]] = []
    if manifest.exists():
        man = json.loads(manifest.read_text())
        for fold in man["folds"]:
            held = fold.get("held_family") or fold.get("held_operation")
            ds = base_dir / Path(fold["dir"]).name / "next_tactic.jsonl"
            rows += _run_dataset(config, ds, weights, family_map, thm2fam, thm2op,
                                 cache, verifier, top_k, held)
    else:
        ds = base_dir / "next_tactic.jsonl"
        rows = _run_dataset(config, ds, weights, family_map, thm2fam, thm2op,
                            cache, verifier, top_k, split_name)
    return v7_metrics(rows), rows


# (split_name, directory, configs to run)
def default_matrix(out_root: Path) -> List[Tuple[str, Path, Tuple[str, ...]]]:
    P = out_root
    return [
        ("current", P / "planner_blind_split_lean_cli",
         ("v5_retrieval", "v6_retrieval", "v6_no_same_family", "v6_no_same_operation", "v7_abstract")),
        ("family_holdout", P / "planner_blind_family_holdout",
         ("v5_retrieval", "v6_retrieval", "v7_abstract")),
        ("operation_holdout", P / "planner_blind_operation_holdout",
         ("v5_retrieval", "v6_retrieval", "v7_abstract")),
        ("kshot_0", P / "planner_blind_kshot_0", ("v6_retrieval",)),
        ("kshot_1", P / "planner_blind_kshot_1", ("v6_retrieval", "v7_abstract")),
        ("kshot_2", P / "planner_blind_kshot_2", ("v6_retrieval", "v7_abstract")),
        ("literal_holdout", P / "planner_blind_literal_holdout",
         ("v5_retrieval", "v6_retrieval", "v7_abstract")),
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--processed-root", type=Path, default=ROOT / "data/processed")
    ap.add_argument("--seeds", type=Path, default=ROOT / "data/seeds/planner_blind_seeds.jsonl")
    ap.add_argument("--weights", type=Path, default=ROOT / "data/configs/v6_retrieval.json")
    ap.add_argument("--output-dir", type=Path, default=ROOT / "data/baselines/v7_eval")
    ap.add_argument("--cache", type=Path, default=ROOT / "data/baselines/v7_eval/verification_cache.json")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--only-split", default=None, help="run a single split by name")
    ap.add_argument("--only-config", default=None, help="run a single config")
    ap.add_argument("--no-verify", dest="verify", action="store_false")
    ap.set_defaults(verify=True)
    args = ap.parse_args(argv)
    os.environ.setdefault("MINI_ELF_LEAN_COMMAND",
                          os.path.expanduser("~/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    weights = load_v6_weights(args.weights)
    thm2fam = family_map_from_seeds(args.seeds)
    # operation map from the union of all rows (the base split has every theorem)
    base_rows = load_dataset(args.processed_root / "planner_blind_split_lean_cli" / "next_tactic.jsonl")
    thm2op = operation_map(base_rows)

    cache = VerificationCache.load(args.cache, enabled=True) if args.verify else VerificationCache(enabled=False)
    verifier = make_lean_cli_verifier(timeout=60.0) if args.verify else None

    summary: Dict[str, Any] = {"top_k": args.top_k, "runs": {}}
    for split_name, base_dir, configs in default_matrix(args.processed_root):
        if args.only_split and split_name != args.only_split:
            continue
        for config in configs:
            if args.only_config and config != args.only_config:
                continue
            print(f"\n===== {split_name} :: {config} =====", flush=True)
            metrics, rows = run_split(config, split_name, base_dir, weights, family_map=thm2fam,
                                      thm2fam=thm2fam, thm2op=thm2op, cache=cache,
                                      verifier=verifier, top_k=args.top_k)
            if cache.enabled:
                cache.save()
            key = f"{split_name}::{config}"
            summary["runs"][key] = metrics
            run_dir = args.output_dir / f"{split_name}__{config}"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
            from mini_elf_lean.io_utils import write_jsonl
            write_jsonl(run_dir / "predictions.jsonl", rows)
            print(f"  pass@1={metrics['pass@1']:.3f} pass@5={metrics['pass@5']:.3f} "
                  f"donorless@5={metrics['donorless_pass@5']:.3f} "
                  f"xfam_verified={metrics['cross_family_verified']} "
                  f"adapted_verified={metrics['adapted_verified']} n={metrics['n_rows']}", flush=True)

    (args.output_dir / "v7_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nwrote {args.output_dir/'v7_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
