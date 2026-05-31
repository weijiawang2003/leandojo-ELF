"""V7 Part 3 — print the donor-scarcity pass@k gradient from a v7_summary.json.

Reads the combined summary written by ``evaluate_retrieval_v7.py`` and prints:
  1. the headline pass@1/pass@5 matrix (split x config),
  2. a donor-scarcity panel (donorless pass@5, cross-family/adapted verified),
  3. per-family pass@5 under family holdout (which families collapse),
  4. the failure taxonomy by donor condition.
Decoupled from Lean so it can be re-run on saved metrics."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]

SPLIT_ORDER = ["current", "kshot_2", "kshot_1", "literal_holdout",
               "family_holdout", "operation_holdout", "kshot_0"]
CONFIG_ORDER = ["v5_retrieval", "v6_retrieval", "v6_no_same_family",
                "v6_no_same_operation", "v7_abstract"]


def _runs(summary: Dict) -> Dict[str, Dict]:
    return summary.get("runs", {})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--summary", type=Path, default=ROOT / "data/baselines/v7_eval/v7_summary.json")
    args = ap.parse_args(argv)
    summary = json.loads(args.summary.read_text())
    runs = _runs(summary)
    by_split: Dict[str, Dict[str, Dict]] = defaultdict(dict)
    for key, m in runs.items():
        split, config = key.split("::", 1)
        by_split[split][config] = m
    splits = [s for s in SPLIT_ORDER if s in by_split] + [s for s in by_split if s not in SPLIT_ORDER]
    configs = [c for c in CONFIG_ORDER if any(c in by_split[s] for s in splits)]

    print("\n=========== V7 pass@5 gradient (split x config) ===========")
    hdr = f"{'split':20}" + "".join(f"{c:>20}" for c in configs)
    print(hdr)
    for s in splits:
        row = f"{s:20}"
        for c in configs:
            m = by_split[s].get(c)
            cell = f"{m['pass@5']:.3f}" if m else "—"
            row += f"{cell:>20}"
        print(row)

    print("\n=========== V7 pass@1 (split x config) ===========")
    print(hdr)
    for s in splits:
        row = f"{s:20}"
        for c in configs:
            m = by_split[s].get(c)
            cell = f"{m['pass@1']:.3f}" if m else "—"
            row += f"{cell:>20}"
        print(row)

    print("\n=========== donor-scarcity panel (v6_retrieval) ===========")
    print(f"{'split':20}{'n':>6}{'pass@5':>9}{'donorless@5':>13}{'xfam_verif':>12}{'xop_verif':>11}{'adapt_verif':>12}{'sf_donor_rate':>15}")
    for s in splits:
        m = by_split[s].get("v6_retrieval") or by_split[s].get("v6_no_same_family")
        if not m:
            continue
        print(f"{s:20}{m['n_rows']:>6}{m['pass@5']:>9.3f}{m['donorless_pass@5']:>13.3f}"
              f"{m['cross_family_verified']:>12}{m['cross_operation_verified']:>11}"
              f"{m['adapted_verified']:>12}{m['same_family_donor_rate']:>15.3f}")

    # per-family pass@5 under family holdout
    fh = by_split.get("family_holdout", {})
    if fh:
        print("\n=========== family_holdout per-family pass@5 ===========")
        configs_fh = [c for c in CONFIG_ORDER if c in fh]
        fams = sorted({f for c in configs_fh for f in fh[c].get("per_family_pass_at_k", {})})
        print(f"{'family':22}" + "".join(f"{c:>16}" for c in configs_fh))
        for fam in fams:
            row = f"{fam:22}"
            for c in configs_fh:
                e = fh[c].get("per_family_pass_at_k", {}).get(fam)
                cell = f"{e['pass@5']:.3f}" if e else "—"
                row += f"{cell:>16}"
            print(row)

    # failure taxonomy
    print("\n=========== failure taxonomy (v6_retrieval, by donor condition) ===========")
    for s in splits:
        m = by_split[s].get("v6_retrieval")
        if m and m.get("failure_taxonomy"):
            print(f"  {s:20} {m['failure_taxonomy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
