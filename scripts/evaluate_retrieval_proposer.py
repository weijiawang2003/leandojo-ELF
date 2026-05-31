"""V5 Part 4 — evaluate the retrieval proof-block proposer on planner-blind.

Runs (via the shared v5 evaluator) the retrieval-focused configurations and
prints a focused comparison on the primary targets (`forall_inst`,
`rewrite_succ`):

  * ``retrieval``          -> data/baselines/planner_blind_retrieval_proposer_test
  * ``retrieval_verbatim`` -> data/baselines/planner_blind_retrieval_verbatim_test
                              (adaptation OFF — shows what numeric substitution buys)
  * ``v3_retrieval``       -> data/baselines/planner_blind_v5_retrieval_fusion_test

Retrieval is **example reuse + light adaptation, not reasoning**; it needs
same-family donors, which the ``family_interpolation`` split provides without
leaking the test theorem. Theorem-level lean-cli verification only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate_mini_elf_v5 import main as v5_main  # noqa: E402

RUNS = [
    ("retrieval", "planner_blind_retrieval_proposer_test", False),
    ("retrieval_verbatim", "planner_blind_retrieval_verbatim_test", False),
    ("v3_retrieval", "planner_blind_v5_retrieval_fusion_test", True),
]


def _common_flags(args, out_dir: Path) -> List[str]:
    flags = [
        "--dataset", str(args.dataset),
        "--output-dir", str(out_dir),
        "--split", args.split,
        "--top-k", str(args.top_k),
        "--retrieval-neighbors", str(args.retrieval_neighbors),
    ]
    if args.seeds:
        flags += ["--seeds", str(args.seeds)]
    if args.verify:
        flags += ["--verify-with-lean-cli"]
    flags += ["--cache" if args.cache else "--no-cache"]
    return flags


def _read_metric(path: Path) -> Optional[Dict]:
    try:
        return json.loads((path / "metrics.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _fam(m: Dict, fam: str, k: str = "5") -> str:
    e = (m.get("per_family_pass_at_k") or {}).get(fam)
    if not e:
        return "  —  "
    return f"{e['pass_at_k'][k]['rate']:.3f}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--model-dir", required=True, type=Path)
    ap.add_argument("--output-root", type=Path, default=ROOT / "data" / "baselines")
    ap.add_argument("--seeds", type=Path, default=None)
    ap.add_argument("--split", default="test")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--retrieval-neighbors", type=int, default=24)
    ap.add_argument("--verify-with-lean-cli", dest="verify", action="store_true")
    ap.add_argument("--no-cache", dest="cache", action="store_false")
    ap.set_defaults(cache=True, verify=True)
    args = ap.parse_args(argv)

    results: Dict[str, Dict] = {}
    for config, suffix, needs_model in RUNS:
        out_dir = args.output_root / suffix
        flags = ["--config", config] + _common_flags(args, out_dir)
        if needs_model:
            flags += ["--model-dir", str(args.model_dir)]
        print(f"\n===== retrieval eval: {config} -> {out_dir} =====")
        rc = v5_main(flags)
        if rc != 0:
            print(f"warning: config {config} returned {rc}", file=sys.stderr)
        m = _read_metric(out_dir)
        if m:
            results[config] = m

    # Focused comparison table.
    print("\n================ RETRIEVAL PROPOSER SUMMARY (pass@5) ================")
    print(f"{'config':28} {'global':>8} {'forall_inst':>12} {'rewrite_succ':>13} {'novel_verified':>15}")
    for config, _suffix, _ in RUNS:
        m = results.get(config)
        if not m:
            print(f"{config:28}  (no metrics)")
            continue
        g = m.get("lean_verification", {}).get("pass_at_k", {}).get("5", {}).get("rate", 0.0)
        nv = (m.get("mini_elf_v5") or {}).get("novel_verified", "—")
        print(f"{config:28} {g:>8.3f} {_fam(m,'forall_inst'):>12} {_fam(m,'rewrite_succ'):>13} {str(nv):>15}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
