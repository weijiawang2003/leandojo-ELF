"""Compute summary statistics over a JSONL trace file.

Reads one or more JSONL files and emits the metrics demanded by the
`tactic-data-quality` skill: success rate, proof completion rate, duplicate
rate, tactic frequency, automation tactic frequency, goal reduction, unique
states/theorems, and backend/model/source/prompt_style distributions, plus
honesty warnings (all-mock data, high automation, high duplication, lean-cli
placeholder states).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, List, Optional

from .io_utils import read_jsonl
from .tactic_sanitizer import AUTOMATION_TACTICS, tactic_head

logger = logging.getLogger(__name__)

# Placeholder written by LeanCliRunner when it verifies a whole file. If every
# successful record carries this, we did not collect true intermediate states.
_LEAN_CLI_PLACEHOLDER = "<verified by lean-cli>"

# Thresholds for warnings.
_HIGH_AUTOMATION = 0.6
_HIGH_DUPLICATE = 0.3


def _dist(records: List[dict], key: str) -> dict:
    return dict(Counter(str(r.get(key)) for r in records).most_common())


def summarize(records: Iterable) -> dict:
    records = list(records)
    n = len(records)
    if n == 0:
        return {"total_records": 0, "warnings": ["empty trace file"]}

    succ = [r for r in records if r.get("success")]
    failed = [r for r in records if not r.get("success")]
    finished = [r for r in succ if r.get("proof_finished")]

    state_changed = sum(1 for r in succ if r.get("state_changed"))
    goals_before = [r.get("num_goals_before") or 0 for r in succ]
    goals_after = [r.get("num_goals_after") or 0 for r in succ]
    reduced = [b - a for b, a in zip(goals_before, goals_after)]

    unique_states_before = {r.get("state_before") for r in records}
    unique_states_after = {r.get("state_after") for r in succ if r.get("state_after")}
    unique_theorems = {r.get("theorem_name") for r in records}
    unique_tactics = {r.get("tactic") for r in records}

    tactic_heads = Counter(tactic_head(r.get("tactic", "")) for r in succ)
    auto_succ = sum(c for t, c in tactic_heads.items() if t in AUTOMATION_TACTICS)

    pair_counts = Counter((r.get("state_before"), r.get("tactic")) for r in succ)
    duplicate_pairs = sum(c - 1 for c in pair_counts.values() if c > 1)

    automation_ratio = auto_succ / len(succ) if succ else 0.0
    duplicate_rate = duplicate_pairs / len(succ) if succ else 0.0

    summary = {
        "total_records": n,
        "successful_transitions": len(succ),
        "failed_attempts": len(failed),
        "success_rate": len(succ) / n,
        "proof_finished_count": len(finished),
        "proof_completion_rate": len(finished) / n,
        "proof_finished_ratio": len(finished) / len(succ) if succ else 0.0,
        "state_changed_rate": state_changed / len(succ) if succ else 0.0,
        "avg_goals_before": sum(goals_before) / len(succ) if succ else 0.0,
        "avg_goals_after": sum(goals_after) / len(succ) if succ else 0.0,
        "avg_goals_reduced": sum(reduced) / len(succ) if succ else 0.0,
        "unique_theorems": len(unique_theorems),
        "unique_states_before": len(unique_states_before),
        "unique_states_after": len(unique_states_after),
        "unique_tactics": len(unique_tactics),
        "duplicate_transition_pairs": duplicate_pairs,
        "duplicate_rate": duplicate_rate,
        "automation_tactic_count": auto_succ,
        "automation_tactic_ratio": automation_ratio,
        "top_tactics": tactic_heads.most_common(20),
        "backend_distribution": _dist(records, "backend"),
        "model_distribution": _dist(records, "model"),
        "source_distribution": _dist(records, "source"),
        "prompt_style_distribution": _dist(records, "prompt_style"),
    }
    summary["warnings"] = _warnings(records, succ, summary)
    return summary


def _warnings(records: List[dict], succ: List[dict], summary: dict) -> List[str]:
    warnings: List[str] = []

    models = {str(r.get("model")) for r in records}
    backends = {str(r.get("backend")) for r in records}
    if models <= {"mock"} or backends <= {"mock"}:
        warnings.append(
            "ALL records come from a mock backend - these are NOT real Lean "
            "verifications. Do not report them as a verified dataset."
        )

    if summary["automation_tactic_ratio"] >= _HIGH_AUTOMATION:
        warnings.append(
            f"High automation ratio ({summary['automation_tactic_ratio']:.0%}): "
            "the dataset leans heavily on simp/omega/aesop/...; consider an "
            "ablation that excludes automation tactics."
        )

    if summary["duplicate_rate"] >= _HIGH_DUPLICATE:
        warnings.append(
            f"High duplicate rate ({summary['duplicate_rate']:.0%}) of "
            "(state_before, tactic) pairs; dedupe before training."
        )

    if succ and all(r.get("state_after") == _LEAN_CLI_PLACEHOLDER for r in succ):
        warnings.append(
            "Every successful record's state_after is the lean-cli placeholder "
            f"({_LEAN_CLI_PLACEHOLDER!r}): these are whole-file verifications, "
            "NOT true intermediate proof states. Use the leandojo backend for "
            "real state_before then tactic then state_after transitions."
        )

    return warnings


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Summarize Lean tactic trace JSONL files.")
    p.add_argument(
        "inputs", nargs="*", type=Path,
        help="One or more JSONL trace files. May also be passed via --path.",
    )
    p.add_argument(
        "--path", type=Path, action="append", default=[],
        help="Add a JSONL trace file to evaluate. Repeatable; combinable with positional inputs.",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON instead of a human report.")
    p.add_argument("-v", "--verbose", action="count", default=0)
    return p


def _print_human(summary: dict) -> None:
    keys_order = [
        "total_records", "successful_transitions", "failed_attempts", "success_rate",
        "proof_finished_count", "proof_completion_rate", "proof_finished_ratio",
        "state_changed_rate", "avg_goals_before", "avg_goals_after", "avg_goals_reduced",
        "unique_theorems", "unique_states_before", "unique_states_after", "unique_tactics",
        "duplicate_transition_pairs", "duplicate_rate",
        "automation_tactic_count", "automation_tactic_ratio",
    ]
    print("=== Trace summary ===")
    for k in keys_order:
        if k not in summary:
            continue
        v = summary[k]
        if isinstance(v, float):
            print(f"{k:32s} {v:.4f}")
        else:
            print(f"{k:32s} {v}")

    for label, dist_key in [
        ("Backend", "backend_distribution"),
        ("Model", "model_distribution"),
        ("Source", "source_distribution"),
        ("Prompt style", "prompt_style_distribution"),
    ]:
        dist = summary.get(dist_key)
        if dist:
            inline = ", ".join(f"{k}={v}" for k, v in dist.items())
            print(f"{label + ' distribution':32s} {inline}")

    if summary.get("top_tactics"):
        print("\nTop tactics (head, count):")
        for head, count in summary["top_tactics"]:
            print(f"  {head:24s} {count}")

    warnings = summary.get("warnings") or []
    if warnings:
        print("\n!!! Warnings:")
        for w in warnings:
            print(f"  - {w}")


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    level = logging.WARNING - 10 * min(args.verbose, 2)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    paths = list(args.inputs) + list(args.path)
    if not paths:
        print("error: no input files given (use positional args or --path)", file=sys.stderr)
        return 2

    records = []
    for path in paths:
        records.extend(read_jsonl(path))
    summary = summarize(records)

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        _print_human(summary)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
