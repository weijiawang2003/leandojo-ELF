"""Mini-ELF v10 — full eval matrix builder (snapshot).

Reads every metrics.json the v10 eval loop has produced under
``data/baselines/v10_eval/`` and emits a markdown summary at
``docs/V10_FULL_EVAL_MATRIX.md``.

Honest reporting contract (same as v8):
  * Missing cells render as `—`, never as `0.000`.
  * The summary tracks measured-fold counts per regime/model so it is always
    clear how much of the matrix is in the table.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]


MODELS = ("baseline_v8", "redundancy_only", "combined_v10")


def _try(p: Path) -> Optional[Dict]:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _fmt(v) -> str:
    return "—" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))


def _regime_block(title: str, regime_root: Path) -> List[str]:
    out: List[str] = [f"## {title}", ""]
    if not regime_root.exists():
        out.append("_no folds measured yet_\n")
        return out
    folds = sorted(d for d in regime_root.iterdir() if d.is_dir())
    if not folds:
        out.append("_no folds measured yet_\n")
        return out
    out.append("| fold | model | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |")
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for fold in folds:
        for m in MODELS:
            md = _try(fold / m / "metrics.json")
            if md is None:
                out.append(f"| `{fold.name}` | `{m}` | — | — | — | — | — | — | — | — |")
            else:
                out.append(
                    f"| `{fold.name}` | `{m}` "
                    f"| {md.get('n_test_theorems', '—')} "
                    f"| {_fmt(md.get('pass@1'))} "
                    f"| {_fmt(md.get('pass@5'))} "
                    f"| {_fmt(md.get('pass@10'))} "
                    f"| {_fmt(md.get('total_verified_candidates'))} "
                    f"| {_fmt(md.get('novel_verified'))} "
                    f"| {_fmt(md.get('cross_family_verified'))} "
                    f"| {_fmt(md.get('cross_operation_verified'))} |")
    measured = sum(1 for f in folds for m in MODELS
                   if (f / m / "metrics.json").exists())
    total = len(folds) * len(MODELS)
    out.append("")
    out.append(f"**status:** {measured}/{total} cells measured.\n")
    return out


def _single_block(title: str, base: Path) -> List[str]:
    out: List[str] = [f"## {title}", ""]
    out.append("| model | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    measured = 0
    for m in MODELS:
        md = _try(base / m / "metrics.json")
        if md is None:
            out.append(f"| `{m}` | — | — | — | — | — | — | — | — |")
        else:
            measured += 1
            out.append(
                f"| `{m}` | {md.get('n_test_theorems', '—')} "
                f"| {_fmt(md.get('pass@1'))} "
                f"| {_fmt(md.get('pass@5'))} "
                f"| {_fmt(md.get('pass@10'))} "
                f"| {_fmt(md.get('total_verified_candidates'))} "
                f"| {_fmt(md.get('novel_verified'))} "
                f"| {_fmt(md.get('cross_family_verified'))} "
                f"| {_fmt(md.get('cross_operation_verified'))} |")
    out.append("")
    out.append(f"**status:** {measured}/{len(MODELS)} cells measured.\n")
    return out


def _clean_per_op_block(title: str, eval_clean_root: Path) -> List[str]:
    """Render the clean per-op matrix from data/baselines/v10_eval_clean/per_op/."""
    out: List[str] = [f"## {title}", ""]
    root = eval_clean_root / "per_op"
    if not root.exists():
        out.append("_clean per-op eval not yet run_\n")
        return out
    out.append("> **This is the corrected (leakage-free) operation_holdout matrix.** "
               "Each `combined_v10_per_op/<op>` model was trained from scratch with the "
               "held op's v10 cells excluded from train; `baseline_v8` is the zero-shot "
               "comparison (never saw any v10 cell). See "
               "`tests/test_v10_no_leakage.py` for the invariants.\n")
    out.append("| held operation | model | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |")
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    measured = 0
    folds = 0
    for op_dir in sorted(root.iterdir()):
        if not op_dir.is_dir():
            continue
        for tag in ("baseline_v8", "combined_v10_per_op"):
            folds += 1
            md = _try(op_dir / tag / "metrics.json")
            if md is None:
                out.append(f"| `{op_dir.name}` | `{tag}` | — | — | — | — | — | — | — | — |")
            else:
                measured += 1
                out.append(
                    f"| `{op_dir.name}` | `{tag}` "
                    f"| {md.get('n_test_theorems', '—')} "
                    f"| {_fmt(md.get('pass@1'))} "
                    f"| {_fmt(md.get('pass@5'))} "
                    f"| {_fmt(md.get('pass@10'))} "
                    f"| {_fmt(md.get('total_verified_candidates'))} "
                    f"| {_fmt(md.get('novel_verified'))} "
                    f"| {_fmt(md.get('cross_family_verified'))} "
                    f"| {_fmt(md.get('cross_operation_verified'))} |")
    out.append("")
    out.append(f"**status:** {measured}/{folds} cells measured.\n")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eval-root", type=Path,
                    default=ROOT / "data" / "baselines" / "v10_eval")
    ap.add_argument("--eval-clean-root", type=Path,
                    default=ROOT / "data" / "baselines" / "v10_eval_clean")
    ap.add_argument("--out-md", type=Path,
                    default=ROOT / "docs" / "V10_FULL_EVAL_MATRIX.md")
    args = ap.parse_args(argv)

    lines: List[str] = []
    lines.append("# Mini-ELF v10 — full eval matrix (status snapshot)")
    lines.append("")
    lines.append("> **⚠️ Leakage note.** The `redundancy_cell_holdout` and "
                 "`redundancy_operation_holdout` blocks below cite the **legacy** "
                 "`combined_v10` (trained on the v10 interpolation split, which leaks "
                 "36/40 test theorems into train). They are kept as in-distribution "
                 "diagnostics, NOT as holdout/generalisation results. The corrected "
                 "operation_holdout block (per-op LOFO) appears at the bottom. The "
                 "leakage is pinned by `tests/test_v10_no_leakage.py`.")
    lines.append("")
    lines.append("Cells marked `—` are not yet measured. Missing cells are explicitly "
                 "*not* `0.000`. Re-running `scripts/build_v10_full_matrix.py` rebuilds "
                 "this document. Legacy metrics from "
                 "`data/baselines/v10_eval/<regime>/<fold>/<model>/metrics.json`; "
                 "clean per-op metrics from "
                 "`data/baselines/v10_eval_clean/per_op/<op>/<model>/metrics.json`.")
    lines.append("")
    lines += _clean_per_op_block("✅ Clean operation_holdout (per-op LOFO)",
                                  args.eval_clean_root)
    lines += _regime_block("❌ redundancy_cell_holdout × model (LEAKED — in-distribution diagnostics)",
                            args.eval_root / "redundancy_cell_holdout")
    lines += _regime_block("❌ redundancy_operation_holdout × model (LEAKED — in-distribution diagnostics)",
                            args.eval_root / "redundancy_operation_holdout")
    lines += _regime_block("redundancy_family_holdout × model",
                            args.eval_root / "redundancy_family_holdout")
    lines += _regime_block("redundancy_low_shot × model",
                            args.eval_root / "redundancy_low_shot")
    lines += _regime_block("v8 negative-control cells × model",
                            args.eval_root / "v8_negative_controls")
    lines += _single_block("donorless_eval × model",
                            args.eval_root / "donorless_eval")

    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
