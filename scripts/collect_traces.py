#!/usr/bin/env python3
"""Thin CLI wrapper around `mini_elf_lean.collector.main` so the script is
runnable from the repository root without installing the package.

Usage:
    python scripts/collect_traces.py \\
        --seeds data/seeds/toy_seeds.jsonl \\
        --out data/traces/toy_success.jsonl \\
        --failed-out data/traces/toy_failed.jsonl \\
        -k 6 -t 0.7 -v
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.collector import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
