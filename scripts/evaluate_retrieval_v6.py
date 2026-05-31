"""V6 Part 6 — focused v5-vs-v6 retrieval comparison (retrieval alone).

Runs the structure-aware retrieval proposer against the v5 char-similarity
baseline on the planner-blind split and prints the failure-mode-focused deltas
(forall_inst pass@1, exists_elim_conj, the negation families). Retrieval-only
configs (no v3), so no model dir is needed.

  * ``v5_retrieval`` -> data/baselines/planner_blind_v6_v5retrieval_test
  * ``v6_retrieval`` -> data/baselines/planner_blind_v6_retrieval_test
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate_mini_elf_v6 import main as v6_main  # noqa: E402

RUNS = [("v5_retrieval", "planner_blind_v6_v5retrieval_test"),
        ("v6_retrieval", "planner_blind_v6_retrieval_test")]
FOCUS = ("forall_inst", "rewrite_succ", "exists_elim_conj",
         "neg_exfalso", "neg_imp_exfalso", "neg_or_cases")


def _read(path: Path) -> Optional[Dict]:
    try:
        return json.loads((path / "metrics.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def _famcell(m: Dict, fam: str, k: str) -> str:
    e = (m.get("per_family_pass_at_k") or {}).get(fam)
    return f"{e['pass_at_k'][k]['rate']:.3f}" if e else "  —  "


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--output-root", type=Path, default=ROOT / "data" / "baselines")
    ap.add_argument("--seeds", type=Path, default=None)
    ap.add_argument("--weights", type=Path, default=ROOT / "data" / "configs" / "v6_retrieval.json")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--no-cache", dest="cache", action="store_false")
    ap.set_defaults(cache=True)
    args = ap.parse_args(argv)

    results: Dict[str, Dict] = {}
    for config, suffix in RUNS:
        out = args.output_root / suffix
        flags = ["--config", config, "--dataset", str(args.dataset), "--output-dir", str(out),
                 "--split", "test", "--top-k", str(args.top_k), "--weights", str(args.weights),
                 "--verify-with-lean-cli", "--cache" if args.cache else "--no-cache"]
        if args.seeds:
            flags += ["--seeds", str(args.seeds)]
        print(f"\n===== retrieval-v6 eval: {config} -> {out} =====")
        if v6_main(flags) != 0:
            print(f"warning: {config} failed", file=sys.stderr)
        m = _read(out)
        if m:
            results[config] = m

    print("\n=========== RETRIEVAL v5 vs v6 (pass@1 / pass@5) ===========")
    header = f"{'metric':22} {'v5_retrieval':>16} {'v6_retrieval':>16}"
    print(header)
    def row(label, fn):
        print(f"{label:22} {fn(results.get('v5_retrieval', {})):>16} {fn(results.get('v6_retrieval', {})):>16}")
    def glob(m, k):
        pk = m.get("lean_verification", {}).get("pass_at_k", {}).get(k, {})
        return f"{pk.get('rate', 0.0):.3f}" if pk else "—"
    row("GLOBAL pass@1", lambda m: glob(m, "1"))
    row("GLOBAL pass@5", lambda m: glob(m, "5"))
    for fam in FOCUS:
        row(f"{fam} @1", lambda m, f=fam: _famcell(m, f, "1"))
        row(f"{fam} @5", lambda m, f=fam: _famcell(m, f, "5"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
