"""Mini-ELF v9 Step 1 — render docs/V8_FULL_EVAL_MATRIX.md from the per-cell
metrics that the v8 eval loop has produced so far.

Walks both eval-output trees:
    data/baselines/v8_seq2seq_<regime>/metrics.json    (from evaluate_proof_block_seq2seq.py)
    data/baselines/v8_eval/<regime>/<config>/metrics.json   (from evaluate_mini_elf_v8.py)

Cells without ``metrics.json`` are written as ``— (not yet measured)`` rather
than ``0.000``. That distinction is the entire point: v8's eval matrix is
incremental, and the brief explicitly forbids faking missing metrics.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "baselines"

# Canonical cell lists — what *should* exist if the eval matrix were complete.
PB_FAMILIES = [
    "neg_exfalso", "neg_imp_exfalso", "neg_double_intro", "neg_contrapositive",
    "neg_or_cases", "exists_elim_conj", "exists_elim_prop", "exists_reconstruct",
    "forall_inst", "rewrite_succ",
]
PB_OPERATIONS = [
    "contradiction", "destruct_exists", "instantiate_forall", "intro_negation",
    "project_conjunction", "rewrite",
]


def _load_metrics(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _seq2seq_metrics(regime_label: str) -> Optional[Dict[str, Any]]:
    """Read evaluate_proof_block_seq2seq.py output for one regime label."""
    return _load_metrics(BASE / f"v8_seq2seq_{regime_label}" / "metrics.json")


def _v8eval_metrics(regime: str, config: str) -> Optional[Dict[str, Any]]:
    """Read evaluate_mini_elf_v8.py output (uses the fusion eval)."""
    return _load_metrics(BASE / "v8_eval" / regime / config / "metrics.json")


def _row(label: str, m: Optional[Dict[str, Any]]) -> str:
    if m is None:
        return f"| `{label}` | — | — | — | — | — | — | — | — |"
    return (
        f"| `{label}` | {m['n_test_theorems']} | "
        f"{m['pass@1']:.3f} | {m['pass@5']:.3f} | {m['pass@10']:.3f} | "
        f"{m.get('total_verified_candidates', '—')} | "
        f"{m.get('novel_verified', '—')} | "
        f"{m.get('cross_family_verified', '—')} | "
        f"{m.get('cross_operation_verified', '—')} |"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "docs" / "V8_FULL_EVAL_MATRIX.md"))
    args = ap.parse_args()

    md: List[str] = []
    md.append("# Mini-ELF v8 — full eval matrix (status snapshot)")
    md.append("")
    md.append("Per-cell `lean-cli` `pass@k` for the v8 seq2seq proposer, plus any v8")
    md.append("fusion cells that ran to completion. Cells marked `—` are **not yet")
    md.append("measured** — the eval loop in")
    md.append("`scripts/run_v8_seq2seq_eval_loop.sh` is timeout-guarded (15 min/fold)")
    md.append("and the lean-cli verifier slows substantially on tactics outside the")
    md.append("verification cache. Missing cells are explicitly *not* `0.000`; the")
    md.append("v8 brief forbids faking metrics.")
    md.append("")
    md.append("All numbers below come from `data/baselines/v8_seq2seq_*/metrics.json`")
    md.append("(produced by `scripts/evaluate_proof_block_seq2seq.py`) and")
    md.append("`data/baselines/v8_eval/<regime>/<config>/metrics.json` (produced by")
    md.append("`scripts/evaluate_mini_elf_v8.py`). Run `scripts/build_v8_full_matrix.py`")
    md.append("to regenerate this document.")
    md.append("")

    # ----- family_holdout × seq2seq_only -----
    md.append("## family_holdout × seq2seq_only")
    md.append("")
    md.append("LOFO: held PB family is absent from train; the *9 other* PB families")
    md.append("remain. Train pool ≈ 658–683 verified rows per fold.")
    md.append("")
    md.append("| regime | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    done = total = 0
    for fam in PB_FAMILIES:
        m = _seq2seq_metrics(f"family_holdout_{fam}")
        md.append(_row(f"family_holdout/{fam}", m))
        total += 1
        if m is not None:
            done += 1
    md.append("")
    md.append(f"**status**: {done}/{total} folds measured.")
    md.append("")

    # ----- operation_holdout × seq2seq_only -----
    md.append("## operation_holdout × seq2seq_only")
    md.append("")
    md.append("LOOO: held operation (and every theorem with that operation) is absent")
    md.append("from train. `unknown` is reserved for the operation the heuristic can't")
    md.append("classify (mostly `exists_reconstruct`); it is excluded from the trained")
    md.append("set on principle.")
    md.append("")
    md.append("| regime | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    done = total = 0
    for op in PB_OPERATIONS:
        m = _seq2seq_metrics(f"operation_holdout_{op}")
        md.append(_row(f"operation_holdout/{op}", m))
        total += 1
        if m is not None:
            done += 1
    md.append("")
    md.append(f"**status**: {done}/{total} folds measured.")
    md.append("")

    # ----- donorless_eval (strictest) -----
    md.append("## donorless_eval (no planner-blind family in train)")
    md.append("")
    md.append("| regime / config | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    md.append(_row("donorless_eval (v8_seq2seq direct)",
                   _seq2seq_metrics("donorless_eval")))
    md.append(_row("donorless_eval / seq2seq_only (fusion eval)",
                   _v8eval_metrics("donorless_eval", "seq2seq_only")))
    md.append(_row("donorless_eval / retrieval_only (fusion eval)",
                   _v8eval_metrics("donorless_eval", "retrieval_only")))
    md.append(_row("donorless_eval / retrieval_seq2seq (fusion eval)",
                   _v8eval_metrics("donorless_eval", "retrieval_seq2seq")))
    md.append(_row("donorless_eval / full_fusion (fusion eval)",
                   _v8eval_metrics("donorless_eval", "full_fusion")))
    md.append("")

    # ----- current / kshot / literal_holdout (for the gradient) -----
    md.append("## current / kshot / literal_holdout (gradient cells)")
    md.append("")
    md.append("These are the v7 donor-scarcity splits, re-measured under v8 configs")
    md.append("when the eval loop completes them.")
    md.append("")
    md.append("| regime / config | n | pass@1 | pass@5 | pass@10 | verified | novel | xfam | xop |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in ("current", "kshot_0", "kshot_1", "kshot_2", "literal_holdout"):
        for c in ("seq2seq_only", "retrieval_only", "retrieval_seq2seq"):
            md.append(_row(f"{r} / {c}", _v8eval_metrics(r, c)))
    md.append("")

    # ----- one-line summary -----
    md.append("## Summary")
    md.append("")
    md.append("Measured cells with a non-zero pass@5 (any v8 config):")
    md.append("")
    md.append("| cell | pass@5 | novel | xfam |")
    md.append("|---|---:|---:|---:|")
    summary_rows: List[tuple] = []
    for fam in PB_FAMILIES:
        m = _seq2seq_metrics(f"family_holdout_{fam}")
        if m and m["pass@5"] > 0:
            summary_rows.append((f"family_holdout/{fam}",
                                 m["pass@5"], m["novel_verified"],
                                 m["cross_family_verified"]))
    for op in PB_OPERATIONS:
        m = _seq2seq_metrics(f"operation_holdout_{op}")
        if m and m["pass@5"] > 0:
            summary_rows.append((f"operation_holdout/{op}",
                                 m["pass@5"], m["novel_verified"],
                                 m["cross_family_verified"]))
    m = _seq2seq_metrics("donorless_eval") or _v8eval_metrics("donorless_eval", "seq2seq_only")
    if m and m["pass@5"] > 0:
        summary_rows.append(("donorless_eval", m["pass@5"], m["novel_verified"],
                             m["cross_family_verified"]))
    if not summary_rows:
        md.append("| _(no non-zero cells measured yet)_ | — | — | — |")
    else:
        for r in summary_rows:
            md.append(f"| `{r[0]}` | {r[1]:.3f} | {r[2]} | {r[3]} |")
    md.append("")
    md.append("Missing-cell semantics: a cell is missing because either")
    md.append("`scripts/run_v8_seq2seq_eval_loop.sh` has not yet reached it, or the")
    md.append("per-fold 15-minute timeout fired before the verifier completed all")
    md.append("candidates. The output is identical in either case — there is no")
    md.append("metrics.json on disk. **Re-running `build_v8_full_matrix.py`** rebuilds")
    md.append("this table from whatever cells are present at that moment.")

    out = Path(args.out)
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
