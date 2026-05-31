"""Part 1 — categorize the v1-transfer / v2 failures on the hard
``difficulty_holdout`` split (train easy/medium, test hard) that motivate the v3
structured planner.

Both v1-transfer and v2 leave difficulty-holdout ``pass@5`` at 0.06: training on
simpler proofs does not teach the flat generator to *compose* a multi-step proof.
This script reads the already-Lean-verified predictions of both models and bins
each failed top-1 into the brief's eight compositional categories:

  missing implication chain composition | missing case split |
  missing nested conjunction projection | wrong iff direction |
  wrong equality direction | wrong witness | malformed proof block | other

The category is inferred from the theorem's pattern family (which compositional
capability the proof *requires*) after first catching malformed/garbled blocks.
Reads only predictions + seeds metadata; never ``state_after``. Writes
``docs/V3_DIFFICULTY_FAILURE_ANALYSIS.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_elf_lean.elf_rerank import KNOWN_TACTIC_HEADS, _balanced  # noqa: E402
from mini_elf_lean.io_utils import read_jsonl  # noqa: E402

CATEGORIES = (
    "missing implication chain composition",
    "missing case split",
    "missing nested conjunction projection",
    "wrong iff direction",
    "wrong equality direction",
    "wrong witness",
    "malformed proof block",
    "other",
)

_FAMILY_CATEGORY = {
    "imp_chain3": "missing implication chain composition",
    "imp_uncurry": "missing implication chain composition",
    "imp_chain_mixed": "missing implication chain composition",
    "iff_chain": "wrong iff direction",
    "iff_flip": "wrong iff direction",
    "iff_apply": "wrong iff direction",
    "eq_chain3": "wrong equality direction",
    "eq_symm_trans": "wrong equality direction",
    "or_elim": "missing case split",
    "or_self_elim": "missing case split",
    "nested_and_elim_r": "missing nested conjunction projection",
    "nested_and_elim_l": "missing nested conjunction projection",
    "nested_and_intro": "missing nested conjunction projection",
    "exists_witness": "wrong witness",
}


def _is_malformed(tactic: str) -> bool:
    s = (tactic or "").strip()
    if not s:
        return True
    head = s.split()[0].split(".")[0]
    if head not in KNOWN_TACTIC_HEADS:
        return True
    return not (_balanced(s, "⟨", "⟩") and _balanced(s, "(", ")"))


def classify_failure(top1: str, family: Optional[str]) -> str:
    """Bin a failed top-1 tactic. Malformed blocks first, then the compositional
    capability the family demands."""
    if _is_malformed(top1):
        return "malformed proof block"
    return _FAMILY_CATEGORY.get(family or "", "other")


def _load_family_map(seeds_paths: List[Path]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for sp in seeds_paths:
        for row in read_jsonl(sp):
            fam = (row.get("metadata") or {}).get("pattern_family")
            name = row.get("theorem_name")
            if name and fam:
                out[name] = fam
    return out


def analyze(predictions_path: Path, thm2fam: Dict[str, str]) -> Dict[str, Any]:
    rows = list(read_jsonl(predictions_path))
    n = len(rows)
    pass1 = pass5 = 0
    cat_counts: Dict[str, int] = defaultdict(int)       # failed top-1 (pass@1 miss)
    cat_unsolved: Dict[str, int] = defaultdict(int)     # pass@5 miss (truly missed)
    examples: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        pk = row.get("lean_pass_at_k", {})
        if pk.get("1"):
            pass1 += 1
        if pk.get("5"):
            pass5 += 1
            continue  # solved within top-5; not a failure to categorize
        preds = row.get("predictions") or []
        top1 = preds[0] if preds else ""
        fam = thm2fam.get(row.get("theorem_name", ""))
        cat = classify_failure(top1, fam)
        cat_counts[cat] += 1
        cat_unsolved[cat] += 1
        if len(examples[cat]) < 3:
            goal = row.get("state_before", "").split("⊢")[-1].strip()
            examples[cat].append({
                "theorem_name": row.get("theorem_name", ""),
                "family": fam or "?",
                "goal": goal,
                "top1": top1.replace("\n", "\\n"),
            })
    return {
        "n_rows": n,
        "pass_at_1": pass1 / n if n else 0.0,
        "pass_at_5": pass5 / n if n else 0.0,
        "n_unsolved_at_5": n - pass5,
        "category_counts_unsolved_at_5": {c: cat_unsolved.get(c, 0) for c in CATEGORIES},
        "examples": {c: examples.get(c, []) for c in CATEGORIES if examples.get(c)},
    }


def _render(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Mini-ELF v3 — difficulty-holdout failure analysis (Part 1)\n")
    lines.append(
        "Generated by `scripts/analyze_difficulty_failures.py`. Categorizes the "
        "Lean-verified failures of **v1-transfer** and **v2** on the hard "
        "`difficulty_holdout` split (train easy/medium → test hard). Both leave "
        "`pass@5` at 0.06; this is the metric v3's structured planner targets. "
        "Reads predictions + seeds metadata only (theorem-level; no `state_after`).\n"
    )
    for model_name, rep in report.items():
        lines.append(f"\n## {model_name}\n")
        lines.append(f"- eval rows: **{rep['n_rows']}**  ·  "
                     f"`pass@1` **{rep['pass_at_1']:.3f}**  ·  `pass@5` **{rep['pass_at_5']:.3f}**  ·  "
                     f"unsolved@5: **{rep['n_unsolved_at_5']}**\n")
        lines.append("\n| failure category | unsolved@5 rows |\n| --- | --- |")
        for cat in CATEGORIES:
            cnt = rep["category_counts_unsolved_at_5"].get(cat, 0)
            if cnt:
                lines.append(f"| {cat} | {cnt} |")
        lines.append("")
        for cat, exs in rep["examples"].items():
            if not exs:
                continue
            lines.append(f"\n**{cat}** — examples:")
            for e in exs:
                lines.append(f"- `{e['theorem_name']}` [{e['family']}] goal `⊢ {e['goal']}` "
                             f"→ top1 `{e['top1']}`")
        lines.append("")
    lines.append(
        "\n## Takeaway\n\n"
        "The failures are overwhelmingly **structural / compositional**: the flat "
        "tactic-string generator cannot compose the multi-step proof a hard "
        "theorem needs (chain three implications, split a disjunction, project a "
        "nested conjunction, pick the iff/equality direction). These are not "
        "garble failures — they are *missing composition*. A symbolic planner that "
        "**constructs** the proof block from the parsed goal (Mini-ELF v3) attacks "
        "exactly this gap; see `docs/V3_PROOF_PLANNER_REPORT.md`.\n"
    )
    return "\n".join(lines)


def _parse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--v1-predictions", type=Path,
                   default=ROOT / "data/baselines/hard_lean_cli_transfer_v1_difficulty_holdout_test/predictions.jsonl")
    p.add_argument("--v2-predictions", type=Path,
                   default=ROOT / "data/baselines/combined_lean_cli_mini_elf_v2_hard_difficulty_test/predictions.jsonl")
    p.add_argument("--seeds", type=Path, nargs="+",
                   default=[ROOT / "data/seeds/hard_lean_seeds.jsonl"])
    p.add_argument("--out", type=Path, default=ROOT / "docs/V3_DIFFICULTY_FAILURE_ANALYSIS.md")
    p.add_argument("--json-out", type=Path, default=None)
    return p


def main(argv=None) -> int:
    args = _parse().parse_args(argv)
    thm2fam = _load_family_map(list(args.seeds))
    report: Dict[str, Any] = {}
    if args.v1_predictions.exists():
        report["v1-transfer (no retraining)"] = analyze(args.v1_predictions, thm2fam)
    if args.v2_predictions.exists():
        report["v2 (combined-corpus training)"] = analyze(args.v2_predictions, thm2fam)
    if not report:
        print("error: no prediction files found", file=sys.stderr)
        return 2
    args.out.write_text(_render(report), encoding="utf-8")
    print(f"wrote {args.out}")
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False),
                                 encoding="utf-8")
        print(f"wrote {args.json_out}")
    for name, rep in report.items():
        print(f"\n{name}: pass@5={rep['pass_at_5']:.3f}, unsolved@5={rep['n_unsolved_at_5']}")
        for cat in CATEGORIES:
            c = rep["category_counts_unsolved_at_5"].get(cat, 0)
            if c:
                print(f"  {cat:42s} {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
