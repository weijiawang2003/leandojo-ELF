#!/usr/bin/env python3
"""Generate a manual-candidate JSONL skeleton from a seeds file.

This does NOT propose tactics. It writes one ManualCandidateRecord per seed with
an empty `candidates` list and `state_before` pre-filled from the seed's
`initial_state`, so a human (or the `tactic-proposer` agent) can fill in
candidates that the collector will then verify with Lean.

Usage:
    python scripts/generate_manual_candidates.py \\
        --seeds data/seeds/toy_lean_cli_seeds.jsonl \\
        --out data/manual/my_candidates.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.io_utils import read_jsonl, write_jsonl  # noqa: E402
from mini_elf_lean.schemas import ManualCandidateRecord, TheoremSeed  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Emit a manual-candidate JSONL skeleton from seeds.")
    p.add_argument("--seeds", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--source", default="claude_code_agent")
    p.add_argument("--prompt-style", default="diverse")
    args = p.parse_args(argv)

    seeds = [TheoremSeed.model_validate(row) for row in read_jsonl(args.seeds)]
    if not seeds:
        print(f"error: no seeds in {args.seeds}", file=sys.stderr)
        return 2

    records = [
        ManualCandidateRecord(
            theorem_name=s.theorem_name,
            state_before=s.initial_state,
            candidates=[],  # <-- fill these in, then run the collector
            source=args.source,
            prompt_style=args.prompt_style,
        )
        for s in seeds
    ]
    n = write_jsonl(args.out, records)
    print(f"Wrote {n} skeleton candidate record(s) to {args.out}")
    print("Fill in each record's `candidates` list, then verify with the collector.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
