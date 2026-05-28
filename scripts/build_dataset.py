"""Build a modeling-ready dataset from verified TraceRecord JSONL.

Usage:

    python scripts/build_dataset.py \\
        --input data/traces/*.jsonl \\
        --output-dir data/processed \\
        --backend lean-cli

Outputs (always written, even when empty):

    data/processed/next_tactic.jsonl
    data/processed/plain_tactics.txt
    data/processed/theorem_splits.json
    data/processed/summary.json

The script intentionally writes a ``summary.json`` even on an empty include set
so CI / later steps can detect "ran successfully, included zero rows" vs
"didn't run at all".
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Make src/ importable when invoked as `python scripts/build_dataset.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mini_elf_lean.dataset_builder import (  # noqa: E402
    BuildFilters,
    SplitConfig,
    build_dataset,
    expand_inputs,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument(
        "--input", required=True, nargs="+",
        help="One or more paths or glob patterns to trace JSONL files.",
    )
    p.add_argument(
        "--output-dir", required=True, type=Path,
        help="Destination for next_tactic.jsonl / plain_tactics.txt / theorem_splits.json / summary.json.",
    )
    p.add_argument(
        "--backend", action="append", default=None, choices=("mock", "lean-cli", "leandojo"),
        help="Repeatable; restrict to these backends. Default: lean-cli + leandojo. "
             "Use --allow-mock to also include mock records.",
    )
    p.add_argument("--allow-mock", action="store_true",
                   help="Include records whose backend=='mock'. Mock 'verification' is heuristic and unreal — opt in.")
    p.add_argument("--include-failed", action="store_true",
                   help="Keep success=False records (useful for negative samples / error-recovery training).")
    pf = p.add_mutually_exclusive_group()
    pf.add_argument("--include-proof-finished", dest="include_proof_finished", action="store_true")
    pf.add_argument("--exclude-proof-finished", dest="include_proof_finished", action="store_false")
    p.set_defaults(include_proof_finished=True)
    p.add_argument("--max-tactic-len", type=int, default=None,
                   help="Drop records whose tactic string exceeds this many characters.")
    p.add_argument("--max-state-len", type=int, default=None,
                   help="Drop records where state_before or state_after exceed this many characters.")
    p.add_argument("--no-dedup", dest="dedup", action="store_false",
                   help="Disable deduplication by (theorem_name, state_before, tactic).")
    p.set_defaults(dedup=True)
    p.add_argument("--train-frac", type=float, default=0.8)
    p.add_argument("--val-frac", type=float, default=0.1)
    p.add_argument("--test-frac", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=42, help="Split-assignment seed (stable across runs).")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")

    try:
        inputs = expand_inputs(args.input)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    backends = tuple(args.backend) if args.backend else ("lean-cli", "leandojo")
    if args.allow_mock and "mock" not in backends:
        # If the user opted into mock data but didn't explicitly list 'mock' as
        # an allowed backend, add it — otherwise --allow-mock would be silently
        # neutered by the backend filter.
        backends = backends + ("mock",)

    filters = BuildFilters(
        backends=backends,
        allow_mock=args.allow_mock,
        include_failed=args.include_failed,
        include_proof_finished=args.include_proof_finished,
        max_tactic_len=args.max_tactic_len,
        max_state_len=args.max_state_len,
        dedup=args.dedup,
    )
    splits = SplitConfig(
        train=args.train_frac, val=args.val_frac, test=args.test_frac, seed=args.seed,
    )

    summary = build_dataset(inputs, args.output_dir, filters=filters, splits=splits)
    print(json.dumps(summary.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
