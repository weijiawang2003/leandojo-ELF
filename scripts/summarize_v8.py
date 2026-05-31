"""Mini-ELF v8 — print a compact summary of the v8 eval matrix.

Walks ``data/baselines/v8_eval/<regime>/<config>/metrics.json`` and prints a
table:

    regime                       config           pass@1  pass@5  pass@10  novel  cross_fam  cross_op

Also writes ``data/baselines/v8_eval/v8_summary.json`` with the same rows for
the doc generator to consume.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(ROOT / "data" / "baselines" / "v8_eval"))
    args = ap.parse_args()
    root = Path(args.root)

    rows: List[Dict[str, Any]] = []
    if root.exists():
        for regime_dir in sorted(root.iterdir()):
            if not regime_dir.is_dir():
                continue
            for config_dir in sorted(regime_dir.iterdir()):
                m = config_dir / "metrics.json"
                if not m.exists():
                    continue
                d = json.loads(m.read_text(encoding="utf-8"))
                rows.append({
                    "regime": regime_dir.name,
                    "config": config_dir.name,
                    "n": d.get("n_test_theorems", 0),
                    "pass@1": d.get("pass@1", 0.0),
                    "pass@5": d.get("pass@5", 0.0),
                    "pass@10": d.get("pass@10", 0.0),
                    "novel_verified": d.get("novel_verified", 0),
                    "donorless_verified": d.get("donorless_verified", 0),
                    "cross_family_verified": d.get("cross_family_verified", 0),
                    "cross_operation_verified": d.get("cross_operation_verified", 0),
                })

    # Also include the seq2seq-direct eval outputs (legacy path)
    for sub in (ROOT / "data" / "baselines").glob("v8_seq2seq_*"):
        m = sub / "metrics.json"
        if not m.exists():
            continue
        d = json.loads(m.read_text(encoding="utf-8"))
        rows.append({
            "regime": sub.name.replace("v8_seq2seq_", ""),
            "config": "seq2seq_direct",
            "n": d.get("n_test_theorems", 0),
            "pass@1": d.get("pass@1", 0.0),
            "pass@5": d.get("pass@5", 0.0),
            "pass@10": d.get("pass@10", 0.0),
            "novel_verified": d.get("novel_verified", 0),
            "donorless_verified": d.get("donorless_verified", 0),
            "cross_family_verified": d.get("cross_family_verified", 0),
            "cross_operation_verified": d.get("cross_operation_verified", 0),
        })

    rows.sort(key=lambda r: (r["regime"], r["config"]))
    (root / "v8_summary.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    if not rows:
        print("(no v8 eval outputs yet)")
        return 0

    print(f"{'regime':<28} {'config':<22} "
          f"{'n':>4} {'p@1':>6} {'p@5':>6} {'p@10':>6} "
          f"{'novel':>6} {'xfam':>5} {'xop':>5}")
    print("-" * 100)
    for r in rows:
        print(f"{r['regime']:<28} {r['config']:<22} "
              f"{r['n']:>4} "
              f"{r['pass@1']:>6.3f} {r['pass@5']:>6.3f} {r['pass@10']:>6.3f} "
              f"{r['novel_verified']:>6} {r['cross_family_verified']:>5} "
              f"{r['cross_operation_verified']:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
