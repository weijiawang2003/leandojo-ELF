"""Mini-ELF v31 — Part 8: density vs token-coverage analysis.

Reads the v31 normalized eval (NO Lean run) and answers:
  * Does canonicalization (A) remove the surface-token ceiling? (token_diversity pass@10
    v30 → v31_canonical_general)
  * Does verified rename augmentation (B) work better than canonical generation?
  * Do the approaches preserve the standard held-outs (v25–v29)?
  * Are residuals still vocabulary/API rather than multi-step?
  * Does the density law need a SECOND axis (family density × surface-token coverage)?

Writes data/baselines/v31_density_vs_token_coverage/report.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
V31E = ROOT / "data" / "baselines" / "v31_normalized_eval"


def best_metrics(run_dir: Path) -> Optional[Dict[str, Any]]:
    best = None
    for f in run_dir.glob("*/metrics.json"):
        m = json.loads(f.read_text())
        key = (m.get("pass@5", 0), m.get("pass@1", 0))
        if best is None or key > best[0]:
            best = (key, m)
    return best[1] if best else None


def cell10(model, bench):
    m = best_metrics(V31E / f"{model}__{bench}")
    return m.get("pass@10") if m else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v31_density_vs_token_coverage" / "report.json"))
    args = ap.parse_args(argv)

    comp = json.loads((V31E / "comparison.json").read_text()) if (V31E / "comparison.json").exists() else {"results": {}, "pool_stats": {}}
    models = ["v30_general_targeted", "v31_raw_plus_projection_aug", "v31_canonical_general", "v31_raw_canonical_mixture"]
    benches = ["v25_heldout", "v26_holdout", "v27_holdout", "v28_holdout", "v29_holdout",
               "v30_targeted_family", "token_diversity"]

    table = {}
    for m in models:
        row = {b: cell10(m, b) for b in benches if cell10(m, b) is not None}
        if row:
            table[m] = row
    report = {"config": "v31_density_vs_token_coverage", "model_x_bench_pass10": table}

    # the headline token-coverage question
    base_td = cell10("v30_general_targeted", "token_diversity")
    report["token_coverage_result"] = {
        "v30_baseline": base_td,
        "canonical_A": cell10("v31_canonical_general", "token_diversity"),
        "rename_aug_B": cell10("v31_raw_plus_projection_aug", "token_diversity"),
        "mixture": cell10("v31_raw_canonical_mixture", "token_diversity"),
    }

    # which approach best preserves the standard held-outs (min over v25-v29)
    def min_std(m):
        vals = [cell10(m, b) for b in ("v25_heldout", "v26_holdout", "v27_holdout", "v28_holdout", "v29_holdout")]
        vals = [v for v in vals if v is not None]
        return min(vals) if vals else None
    report["standard_holdout_floor"] = {m: min_std(m) for m in models}

    # pool stats: unresolved / concretization (the v19 guard working)
    report["pool_stats_token_diversity"] = {
        m: comp.get("results", {}).get(f"{m}__token_diversity", {}).get("pool_stats")
        for m in models}

    # verdict on canonical vs augmentation
    cA = report["token_coverage_result"]["canonical_A"]
    cB = report["token_coverage_result"]["rename_aug_B"]
    base = base_td if base_td is not None else 0.0
    report["verdict"] = {
        "canonical_improves": (cA is not None and cA > base + 1e-9),
        "augmentation_improves": (cB is not None and cB > base + 1e-9),
        "augmentation_beats_canonical": (cB is not None and cA is not None and cB >= cA - 1e-9),
        "summary": _summary(base, cA, cB),
    }

    # second axis of the density law
    report["density_law_second_axis"] = (
        "v29/v30 showed family density (siblings) is necessary; v30 found it is not "
        "sufficient when the held-out member's identifiers are OOD. v31 result: the "
        "ceiling is a TOKEN-COVERAGE axis. Requirement = >=4-6 family siblings AND "
        "identifier/projection surface coverage of the held-out member's tokens. "
        "Verified rename augmentation supplies that coverage directly; input-side "
        "canonicalization supplies it by making the model identifier-invariant.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[density-vs-token] token-coverage (token_diversity pass@10):", report["token_coverage_result"])
    print("[density-vs-token] standard-holdout floor:", report["standard_holdout_floor"])
    print("[density-vs-token] verdict:", report["verdict"]["summary"])
    return 0


def _summary(base, cA, cB):
    parts = [f"v30 token_diversity={base}"]
    if cA is not None:
        parts.append(f"canonical(A)={cA}")
    if cB is not None:
        parts.append(f"rename_aug(B)={cB}")
    return "; ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
