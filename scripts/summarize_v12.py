"""Mini-ELF v12 — summarise the literal-adapt × rerank matrix.

Reads ``data/baselines/v12_eval/<fam>/<config>/metrics.json`` for each
family × config pair and prints a markdown table to stdout. Also
exports a JSON blob for downstream doc rendering.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


CONFIGS = ("raw", "literal_adapt", "rerank", "literal_adapt_rerank")
FAMILIES = ("forall_inst", "rewrite_succ", "neg_exfalso",
            "exists_reconstruct", "neg_imp_exfalso")


def _try(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default="data/baselines/v12_eval")
    ap.add_argument("--out-json", default="data/baselines/v12_eval/v12_summary.json")
    args = ap.parse_args(argv)

    root = Path(args.root)
    blob: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for fam in FAMILIES:
        blob[fam] = {}
        for cfg in CONFIGS:
            blob[fam][cfg] = _try(root / fam / cfg / "metrics.json") or {}

    # Markdown headline table: pass@5 per (family × config)
    print("## v12 pass@5 matrix\n")
    print("| family (n) | raw | +literal_adapt | +rerank | +both |")
    print("|---|---:|---:|---:|---:|")
    for fam in FAMILIES:
        n = (blob[fam].get("raw") or {}).get("n_test_theorems")
        cells = []
        for cfg in CONFIGS:
            m = blob[fam].get(cfg)
            cells.append(_fmt((m or {}).get("pass@5")))
        nstr = f"({n})" if n is not None else ""
        print(f"| `{fam}` {nstr} | {cells[0]} | {cells[1]} | {cells[2]} | **{cells[3]}** |")

    # Delta vs raw on pass@5
    print("\n## pass@5 Δ vs raw (per family × config)\n")
    print("| family | +literal_adapt | +rerank | +both |")
    print("|---|---:|---:|---:|")
    for fam in FAMILIES:
        raw = (blob[fam].get("raw") or {}).get("pass@5")
        if raw is None:
            continue
        deltas = []
        for cfg in ("literal_adapt", "rerank", "literal_adapt_rerank"):
            v = (blob[fam].get(cfg) or {}).get("pass@5")
            deltas.append(_fmt(None if v is None else v - raw))
        print(f"| `{fam}` | {deltas[0]} | {deltas[1]} | {deltas[2]} |")

    # Detailed counters for the +both config
    print("\n## Detailed counters (literal_adapt_rerank)\n")
    print("| family | verified | novel | xfam | xop | lit_adapt verified | rank_fix | malformed | stale |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for fam in FAMILIES:
        m = blob[fam].get("literal_adapt_rerank") or {}
        print(f"| `{fam}` | {_fmt(m.get('total_verified_candidates'))} "
              f"| {_fmt(m.get('novel_verified'))} "
              f"| {_fmt(m.get('cross_family_verified'))} "
              f"| {_fmt(m.get('cross_operation_verified'))} "
              f"| {_fmt(m.get('literal_adapt_verified'))} "
              f"| {_fmt(m.get('rank_failure_fixes'))} "
              f"| {_fmt(m.get('malformed_count'))} "
              f"| {_fmt(m.get('stale_literal_count'))} |")

    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(blob, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
