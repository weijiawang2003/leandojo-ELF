"""Thin CLI wrapper around mini_elf_lean.corpus_audit.main.

Usage:
    python scripts/audit_corpus.py \\
        --verified data/traces/basic_lean_cli_verified.jsonl \\
        --failed  data/traces/basic_lean_cli_failed.jsonl
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mini_elf_lean.corpus_audit import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
