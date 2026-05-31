"""Evaluate Mini-ELF v2 with real lean-cli pass@k.

v2 shares v1's artifact layout (denoising AE + structured flow + reranker), so
evaluation is identical — this is a thin delegate to ``evaluate_mini_elf_v1``'s
engine so there is one evaluator, not two. Use it exactly like the v1 evaluator
(``--model-dir`` pointing at a ``combined_lean_cli_mini_elf_v2*`` model,
``--dataset`` at the split being measured). Theorem-level (``state_after_is_real=
false``).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate_mini_elf_v1 import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
