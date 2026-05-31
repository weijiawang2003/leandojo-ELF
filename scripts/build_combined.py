"""Build the combined (basic + hard) processed dataset for Mini-ELF v2 training.

A single ``build_dataset`` call can only stamp one ``corpus_source``; the combined
corpus needs per-theorem provenance (basic vs hard) and difficulty. So we merge
per-theorem metadata from both seed files (basic theorems default to
``difficulty=easy`` / ``corpus_source=basic``; hard theorems keep their declared
difficulty + ``corpus_source=hard``) and pass that map straight through, so each
row's ``metadata`` carries ``corpus_source`` / ``pattern_family`` / ``difficulty``.

Splits use the requested strategy over the *union* of theorems. Because hash
assignment is deterministic per (theorem_name, seed), a theorem lands in the same
split here as in its standalone dataset — so evaluating a combined-trained model
on the standalone basic/hard test splits stays leakage-free for the hash strategy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mini_elf_lean.dataset_builder import BuildFilters, SplitConfig, build_dataset  # noqa: E402
from mini_elf_lean.splits import SPLIT_STRATEGIES, assign_splits, load_theorem_metadata  # noqa: E402


def _merged_meta(basic_seeds: Path, hard_seeds: Path) -> dict:
    meta: dict = {}
    for name, m in load_theorem_metadata(basic_seeds).items():
        meta[name] = {
            "pattern_family": m.get("pattern_family"),
            "difficulty": m.get("difficulty") or "easy",  # basic corpus = easy
            "requires_multistep": bool(m.get("requires_multistep")),
            "requires_copy": bool(m.get("requires_copy")),
            "requires_structure": bool(m.get("requires_structure")),
            "corpus_source": "basic",
        }
    for name, m in load_theorem_metadata(hard_seeds).items():
        meta[name] = {
            "pattern_family": m.get("pattern_family"),
            "difficulty": m.get("difficulty") or "hard",
            "requires_multistep": bool(m.get("requires_multistep")),
            "requires_copy": bool(m.get("requires_copy")),
            "requires_structure": bool(m.get("requires_structure")),
            "corpus_source": "hard",
        }
    return meta


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--basic-verified", type=Path, default=Path("data/traces/basic_lean_cli_verified.jsonl"))
    p.add_argument("--hard-verified", type=Path, default=Path("data/traces/hard_lean_cli_verified.jsonl"))
    p.add_argument("--basic-seeds", type=Path, default=Path("data/seeds/basic_lean_seeds.jsonl"))
    p.add_argument("--hard-seeds", type=Path, default=Path("data/seeds/hard_lean_seeds.jsonl"))
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--split-strategy", choices=SPLIT_STRATEGIES, default="hash")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    meta = _merged_meta(args.basic_seeds, args.hard_seeds)
    split_override = assign_splits(meta.keys(), meta, args.split_strategy, seed=args.seed)
    summary = build_dataset(
        [args.basic_verified, args.hard_verified], args.output_dir,
        filters=BuildFilters(backends=("lean-cli",)),
        splits=SplitConfig(seed=args.seed),
        split_override=split_override, split_strategy=args.split_strategy,
        theorem_meta=meta,
    )
    print(json.dumps(summary.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
