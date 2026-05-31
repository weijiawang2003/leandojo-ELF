"""Mini-ELF v20 — Part 6: isolate the ranker-time abstraction effect.

The full six-config evaluation is produced by
``evaluate_v20_broad_core.py`` (which verifies every candidate with
lean-cli — a ~20-minute cold run). This script does NOT re-run Lean;
it reads the already-computed per-config metrics and predictions and
emits a focused comparison of the four configs the v20 brief's Part 6
asks about:

  * ``raw``             — v20 model beam order
  * ``policy``          — v15 + v17 operation-aware policy
  * ``abstract``        — v20 ranker-time abstract-pattern reranker
  * ``policy_abstract`` — policy then abstract-pattern tie-break

It reports, per config:
  * pass@1 / pass@5 / pass@10
  * unknown_identifier count (the v18 dominant failure)
  * whether implication / bool / equality_rewrite / list moved
  * a per-theorem reordering trace for the abstract reranker
    (how many positions each verifying candidate moved up vs raw)

This makes the ranker-time abstraction's contribution auditable
without paying the Lean cost twice.

No state_after, no manual oracle, no Mathlib, no re-verification.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v20_abstract_reranker")


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def _first_rank(rec: Dict[str, Any]) -> Optional[int]:
    for i, v in enumerate(rec.get("verifications", [])):
        if v.get("success"):
            return i
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--eval-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v20_broad_plus_eval"))
    ap.add_argument("--out-json",
                    default=str(ROOT / "data" / "baselines"
                                / "v20_abstract_reranker_comparison.json"))
    args = ap.parse_args(argv)

    eval_root = Path(args.eval_root)
    configs = ["raw", "policy", "abstract", "policy_abstract"]
    metrics: Dict[str, Dict[str, Any]] = {}
    preds: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for cfg in configs:
        mp = eval_root / cfg / "metrics.json"
        pp = eval_root / cfg / "predictions.jsonl"
        if not mp.exists():
            logger.error("missing metrics for config %s at %s", cfg, mp)
            return 1
        metrics[cfg] = json.loads(mp.read_text(encoding="utf-8"))
        preds[cfg] = {r["theorem_name"]: r for r in _read_jsonl(pp)}

    # Headline comparison
    comparison: Dict[str, Any] = {"configs": {}}
    for cfg in configs:
        m = metrics[cfg]
        comparison["configs"][cfg] = {
            "pass@1": m["pass@1"],
            "pass@5": m["pass@5"],
            "pass@10": m["pass@10"],
            "MRR": m["MRR"],
            "unknown_identifier": m["error_taxonomy"].get(
                "unknown_identifier", 0),
            "n_malformed_top1": m["n_malformed_top1"],
            "per_category_pass5": {
                cat: round(d["pass@5"], 3)
                for cat, d in m["per_category"].items()
            },
        }

    # Reordering trace: for each theorem, compare the abstract config's
    # first-verified rank against raw's. Negative delta = moved up.
    reorder_trace: List[Dict[str, Any]] = []
    moved_up = moved_down = unchanged = 0
    for nm, raw_rec in preds["raw"].items():
        abs_rec = preds["abstract"].get(nm)
        if not abs_rec:
            continue
        raw_rank = _first_rank(raw_rec)
        abs_rank = _first_rank(abs_rec)
        # Only meaningful when at least one config verified.
        if raw_rank is None and abs_rank is None:
            continue
        rr = raw_rank if raw_rank is not None else 99
        ar = abs_rank if abs_rank is not None else 99
        delta = ar - rr
        if delta < 0:
            moved_up += 1
        elif delta > 0:
            moved_down += 1
        else:
            unchanged += 1
        reorder_trace.append({
            "theorem_name": nm,
            "category": raw_rec.get("category"),
            "raw_first_rank": raw_rank,
            "abstract_first_rank": abs_rank,
            "delta": delta,
            "abstract_top1": abs_rec.get("ordering", ["<none>"])[0],
        })

    comparison["reorder_summary"] = {
        "moved_up": moved_up,
        "moved_down": moved_down,
        "unchanged": unchanged,
    }
    comparison["reorder_trace"] = reorder_trace
    comparison["uses_state_after"] = False
    comparison["uses_manual_oracle"] = False
    comparison["reranker_emits_placeholders"] = False

    Path(args.out_json).write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False),
        encoding="utf-8")

    # Console summary
    logger.info("ranker-time abstraction comparison (no re-verification):")
    for cfg in configs:
        c = comparison["configs"][cfg]
        logger.info("  %-16s pass@1=%.3f pass@5=%.3f pass@10=%.3f "
                    "unknown_id=%d", cfg, c["pass@1"], c["pass@5"],
                    c["pass@10"], c["unknown_identifier"])
    logger.info("reorder vs raw: moved_up=%d moved_down=%d unchanged=%d",
                moved_up, moved_down, unchanged)
    logger.info("wrote %s", args.out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
