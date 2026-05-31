"""Mini-ELF v10 — scaling-relation analysis.

Reads the per-fold metrics.json files produced by ``run_v10_eval_loop.sh`` and
builds the operation-vs-coverage scaling table the v10 brief asks for:

  operation | train families | train rows | held-out pass@5 |
            cross_family_verified | cross_operation_verified

Plus a second table comparing the three v10 models (baseline_v8, redundancy_only,
combined_v10) by aggregate pass@5/pass@10/novel_verified across each regime,
and a per-operation "redundancy delta" between baseline_v8 and combined_v10.

Outputs ``docs/V10_SCALING_ANALYSIS.md`` and the raw computed dicts to
``data/baselines/v10_eval/scaling_summary.json``.

Honest reporting contract: a (model, regime, fold) cell missing on disk is
written as ``—``, **never** as ``0.000``. The v8 brief's no-fake-metric rule
carries through.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


MODELS = ("baseline_v8", "redundancy_only", "combined_v10")


def _fmt(v: Optional[float], *, pct: bool = False) -> str:
    if v is None:
        return "—"
    if pct:
        return f"{v:.3f}"
    return f"{v}"


def _try_load(p: Path) -> Optional[Dict]:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _per_op_train_features(processed_root: Path) -> Dict[str, Dict[str, int]]:
    """For each operation in the redundancy corpus, count its theorem-cells
    in the *full* corpus (before any holdout). This is the data-scaling
    independent variable."""
    pb_root = processed_root / "redundancy_lean_cli" / "next_tactic.jsonl"
    if not pb_root.exists():
        return {}
    rows: List[Dict] = []
    for ln in pb_root.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        rows.append(json.loads(s))
    per_op: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"n_train_rows": 0, "n_train_families": 0})
    fams_by_op: Dict[str, set] = defaultdict(set)
    for r in rows:
        m = r.get("metadata") or {}
        op = m.get("operation") or m.get("required_operation") or "unknown"
        fam = m.get("surface_family") or m.get("pattern_family")
        per_op[op]["n_train_rows"] += 1
        if fam is not None:
            fams_by_op[op].add(fam)
    for op, fams in fams_by_op.items():
        per_op[op]["n_train_families"] = len(fams)
    return per_op


def _read_op_holdout(eval_root: Path) -> Dict[str, Dict[str, Optional[Dict]]]:
    """For each operation_holdout fold and each model, load metrics.json."""
    base = eval_root / "redundancy_operation_holdout"
    out: Dict[str, Dict[str, Optional[Dict]]] = {}
    if not base.exists():
        return out
    for op_dir in sorted(base.iterdir()):
        if not op_dir.is_dir():
            continue
        out[op_dir.name] = {m: _try_load(op_dir / m / "metrics.json")
                            for m in MODELS}
    return out


def _read_cell_holdout(eval_root: Path) -> Dict[str, Dict[str, Optional[Dict]]]:
    base = eval_root / "redundancy_cell_holdout"
    out: Dict[str, Dict[str, Optional[Dict]]] = {}
    if not base.exists():
        return out
    for cell in sorted(base.iterdir()):
        if not cell.is_dir():
            continue
        out[cell.name] = {m: _try_load(cell / m / "metrics.json")
                          for m in MODELS}
    return out


def _read_aux_regime(eval_root: Path, name: str) -> Dict[str, Optional[Dict]]:
    base = eval_root / name
    out: Dict[str, Optional[Dict]] = {}
    if not base.exists():
        return {m: None for m in MODELS}
    for m in MODELS:
        out[m] = _try_load(base / m / "metrics.json")
    return out


def _aggregate(per_fold: Dict[str, Dict[str, Optional[Dict]]],
               metric: str) -> Dict[str, Optional[float]]:
    """Mean of `metric` across folds, per model. Missing folds skipped; if no
    fold has the metric, returns None (which renders as `—`)."""
    out: Dict[str, Optional[float]] = {}
    for model in MODELS:
        vals: List[float] = []
        for fold, by_model in per_fold.items():
            mdat = by_model.get(model)
            if mdat is None:
                continue
            v = mdat.get(metric)
            if v is None:
                continue
            vals.append(float(v))
        out[model] = (sum(vals) / len(vals)) if vals else None
    return out


def _aggregate_sum(per_fold: Dict[str, Dict[str, Optional[Dict]]],
                   metric: str) -> Dict[str, Optional[int]]:
    out: Dict[str, Optional[int]] = {}
    for model in MODELS:
        vals: List[int] = []
        for fold, by_model in per_fold.items():
            mdat = by_model.get(model)
            if mdat is None:
                continue
            v = mdat.get(metric)
            if v is None:
                continue
            vals.append(int(v))
        out[model] = sum(vals) if vals else None
    return out


def _build_scaling_table(per_op_train: Dict[str, Dict[str, int]],
                         op_holdout: Dict[str, Dict[str, Optional[Dict]]],
                         model: str) -> List[Dict]:
    """One row per held-out operation with the train features (BEFORE that op
    is held out -> n_train_families = total corpus families minus this op's)
    and the eval cell pass@5/verified counts."""
    rows: List[Dict] = []
    total_fams = sum(d["n_train_families"] for d in per_op_train.values())
    total_rows = sum(d["n_train_rows"] for d in per_op_train.values())
    for op, ofeats in sorted(per_op_train.items()):
        # under operation_holdout, train = all rows except this op's
        n_train_fams_during_holdout = total_fams - ofeats["n_train_families"]
        n_train_rows_during_holdout = total_rows - ofeats["n_train_rows"]
        cell = op_holdout.get(op, {}).get(model)
        rows.append({
            "operation": op,
            "n_corpus_families_for_op": ofeats["n_train_families"],
            "n_corpus_rows_for_op": ofeats["n_train_rows"],
            "n_train_families_during_holdout": n_train_fams_during_holdout,
            "n_train_rows_during_holdout": n_train_rows_during_holdout,
            "pass@5": (cell or {}).get("pass@5"),
            "pass@10": (cell or {}).get("pass@10"),
            "verified": (cell or {}).get("total_verified_candidates"),
            "novel_verified": (cell or {}).get("novel_verified"),
            "cross_family_verified": (cell or {}).get("cross_family_verified"),
            "cross_operation_verified": (cell or {}).get("cross_operation_verified"),
        })
    return rows


def _write_doc(out_md: Path, *,
               per_op_train: Dict[str, Dict[str, int]],
               op_holdout: Dict[str, Dict[str, Optional[Dict]]],
               cell_holdout: Dict[str, Dict[str, Optional[Dict]]],
               donorless: Dict[str, Optional[Dict]],
               neg_controls: Dict[str, Dict[str, Optional[Dict]]],
               ) -> None:

    lines: List[str] = []
    lines.append("# Mini-ELF v10 — scaling-relation analysis\n")
    lines.append("Auto-generated by `scripts/analyze_v10_scaling.py`. Missing "
                 "cells are reported as `—`, never as `0.000` (no-fake-metric "
                 "contract carried from v8).\n")
    lines.append("## Per-operation scaling under operation_holdout\n")
    lines.append("How many training families/rows the model sees while one "
                 "operation is held out, vs how well it transfers to that "
                 "held operation. Higher coverage on the rest of the corpus "
                 "is the v10 hypothesis; pass@5 column = the test.\n")
    for model in MODELS:
        lines.append(f"### model = `{model}`\n")
        lines.append("| operation | train fams (held out) | train rows (held out)"
                     " | pass@5 | pass@10 | verified | novel | xfam | xop |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in _build_scaling_table(per_op_train, op_holdout, model):
            lines.append(
                f"| `{r['operation']}` "
                f"| {r['n_train_families_during_holdout']} "
                f"| {r['n_train_rows_during_holdout']} "
                f"| {_fmt(r['pass@5'], pct=True)} "
                f"| {_fmt(r['pass@10'], pct=True)} "
                f"| {_fmt(r['verified'])} "
                f"| {_fmt(r['novel_verified'])} "
                f"| {_fmt(r['cross_family_verified'])} "
                f"| {_fmt(r['cross_operation_verified'])} |")
        lines.append("")

    lines.append("## Aggregate per-model summary (mean across folds)\n")
    lines.append("Means are computed over only the **measured** folds; "
                 "missing folds do not pull the mean toward zero. The "
                 "denominator (`n_measured_folds`) is reported next to each "
                 "value.\n")

    def _block(title: str, per_fold: Dict[str, Dict[str, Optional[Dict]]]):
        lines.append(f"### {title}\n")
        lines.append("| model | n_measured_folds | mean pass@5 | mean pass@10 | sum verified | sum novel_verified | sum cross_family | sum cross_operation |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        means5 = _aggregate(per_fold, "pass@5")
        means10 = _aggregate(per_fold, "pass@10")
        sum_v = _aggregate_sum(per_fold, "total_verified_candidates")
        sum_n = _aggregate_sum(per_fold, "novel_verified")
        sum_xf = _aggregate_sum(per_fold, "cross_family_verified")
        sum_xo = _aggregate_sum(per_fold, "cross_operation_verified")
        for m in MODELS:
            n_measured = sum(1 for f in per_fold.values()
                             if f.get(m) is not None)
            lines.append(
                f"| `{m}` | {n_measured} "
                f"| {_fmt(means5[m], pct=True)} | {_fmt(means10[m], pct=True)} "
                f"| {_fmt(sum_v[m])} | {_fmt(sum_n[m])} "
                f"| {_fmt(sum_xf[m])} | {_fmt(sum_xo[m])} |")
        lines.append("")

    _block("cell_holdout (32 folds, leave-one-(op,family)-cell-out)", cell_holdout)
    _block("operation_holdout (≤8 folds, leave-one-operation-out)", op_holdout)

    lines.append("## donorless_eval (cross-cohort transfer)\n")
    lines.append("v8/v9 baseline cell: `baseline_v8` pass@5 = 0.033, "
                 "cross_family_verified = 3. Asking whether the v10 redundancy "
                 "data moves the needle on the strictest donorless regime.\n")
    lines.append("| model | n | pass@5 | pass@10 | verified | novel | xfam | xop |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for m in MODELS:
        d = donorless.get(m)
        if d is None:
            lines.append(f"| `{m}` | — | — | — | — | — | — | — |")
        else:
            lines.append(
                f"| `{m}` | {d.get('n_test_theorems', '—')} "
                f"| {_fmt(d.get('pass@5'), pct=True)} "
                f"| {_fmt(d.get('pass@10'), pct=True)} "
                f"| {_fmt(d.get('total_verified_candidates'))} "
                f"| {_fmt(d.get('novel_verified'))} "
                f"| {_fmt(d.get('cross_family_verified'))} "
                f"| {_fmt(d.get('cross_operation_verified'))} |")
    lines.append("")

    lines.append("## v8 negative-control cells (`forall_inst`, `rewrite_succ`)\n")
    lines.append("v8 stayed at 0/n on both. v10's central question is whether "
                 "adding *redundancy* (the same operation reused across more "
                 "surface families) unblocks them.\n")
    for fold_name, per_model in neg_controls.items():
        lines.append(f"### `{fold_name}`\n")
        lines.append("| model | n | pass@5 | pass@10 | verified | novel | xfam | xop |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for m in MODELS:
            d = per_model.get(m)
            if d is None:
                lines.append(f"| `{m}` | — | — | — | — | — | — | — |")
            else:
                lines.append(
                    f"| `{m}` | {d.get('n_test_theorems', '—')} "
                    f"| {_fmt(d.get('pass@5'), pct=True)} "
                    f"| {_fmt(d.get('pass@10'), pct=True)} "
                    f"| {_fmt(d.get('total_verified_candidates'))} "
                    f"| {_fmt(d.get('novel_verified'))} "
                    f"| {_fmt(d.get('cross_family_verified'))} "
                    f"| {_fmt(d.get('cross_operation_verified'))} |")
        lines.append("")

    lines.append("## Honest limits\n")
    lines.append("* v10 tests **data scaling**, not a new architecture; the "
                 "seq2seq is identical to v8.\n"
                 "* The redundancy corpus is synthetic and theorem-level; "
                 "`state_after_is_real = False` for every cell.\n"
                 "* `cross_operation_verified > 0` cells are the strongest "
                 "signal; they require novel composition across operations "
                 "that the train pool never demonstrates together.\n"
                 "* This report contains no manual oracle candidates; only "
                 "Lean-verified model outputs count.\n")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--processed-root", type=Path,
                    default=ROOT / "data" / "processed")
    ap.add_argument("--eval-root", type=Path,
                    default=ROOT / "data" / "baselines" / "v10_eval")
    ap.add_argument("--out-md", type=Path,
                    default=ROOT / "docs" / "V10_SCALING_ANALYSIS.md")
    ap.add_argument("--out-summary", type=Path,
                    default=ROOT / "data" / "baselines" / "v10_eval"
                    / "scaling_summary.json")
    args = ap.parse_args(argv)

    per_op_train = _per_op_train_features(args.processed_root)
    op_holdout = _read_op_holdout(args.eval_root)
    cell_holdout = _read_cell_holdout(args.eval_root)
    donorless = _read_aux_regime(args.eval_root, "donorless_eval")

    neg_controls: Dict[str, Dict[str, Optional[Dict]]] = {}
    neg_root = args.eval_root / "v8_negative_controls"
    if neg_root.exists():
        for fold in sorted(neg_root.iterdir()):
            if not fold.is_dir():
                continue
            neg_controls[fold.name] = {m: _try_load(fold / m / "metrics.json")
                                       for m in MODELS}

    summary = {
        "per_operation_train_features": per_op_train,
        "operation_holdout": {
            op: {m: (md or {}) for m, md in by_m.items()}
            for op, by_m in op_holdout.items()
        },
        "cell_holdout": {
            cell: {m: (md or {}) for m, md in by_m.items()}
            for cell, by_m in cell_holdout.items()
        },
        "donorless_eval": {m: (md or {}) for m, md in donorless.items()},
        "v8_negative_controls": {
            f: {m: (md or {}) for m, md in by_m.items()}
            for f, by_m in neg_controls.items()
        },
    }
    args.out_summary.parent.mkdir(parents=True, exist_ok=True)
    args.out_summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                encoding="utf-8")

    _write_doc(args.out_md, per_op_train=per_op_train,
               op_holdout=op_holdout, cell_holdout=cell_holdout,
               donorless=donorless, neg_controls=neg_controls)

    print(f"wrote {args.out_md}")
    print(f"wrote {args.out_summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
