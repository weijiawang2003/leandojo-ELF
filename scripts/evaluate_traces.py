#!/usr/bin/env python3
"""Thin CLI wrapper around `mini_elf_lean.evaluate_traces.main`.

Usage:
    python scripts/evaluate_traces.py data/traces/toy_success.jsonl
    python scripts/evaluate_traces.py data/traces/*.jsonl --json
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.evaluate_traces import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
