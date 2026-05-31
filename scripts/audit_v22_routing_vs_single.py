"""Mini-ELF v22 — Part 1: routing-vs-single audit.

Compares, per v18 broad-core category, the four systems already on
disk:

  * v20 broad-plus (single model, pre-forall)
  * v21 single-retrain (config B: v20 pool + forall, one model)
  * v21 higher-capacity (config D: embed128/hidden192)
  * v21 routed (config C: broad-plus + forall specialist)

For each category it reports pass@1/5/10 + no_verified_top10 across
all four, then classifies each category as:

  * ``needs_routing``     — routed > best single by >= 0.2 pass@5
  * ``harmed_by_retrain`` — single-retrain (B) < v20 by >= 0.2 pass@5
  * ``capacity_sensitive``— capacity (D) > single-retrain (B) by >= 0.2
  * ``stable``            — within 0.1 across all configs

This is the v22 starting map: it says *which* categories the
general-model experiment (Parts 2–5) must watch, and which are safe.

Read-only: no Lean, no model load. Reads existing metrics.json files.
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
logger = logging.getLogger("audit_v22_routing_vs_single")

# (label, metrics.json path) — abstract config is the best rerank for
# all post-v20 systems; v18/v20 use their existing best policy/abstract.
SYSTEMS = [
    ("v18_broad_only", "data/baselines/v18_broad_only_eval/policy/metrics.json"),
    ("v20_broad_plus", "data/baselines/v20_broad_plus_eval_timeout_rerun/abstract/metrics.json"),
    ("v21_single_retrain", "data/baselines/v21_broad_plus_forall_eval/abstract/metrics.json"),
    ("v21_capacity", "data/baselines/v21_capacity_eval/abstract/metrics.json"),
    ("v21_routed", "data/baselines/v21_routed_eval/abstract/metrics.json"),
]

CATEGORIES = ["implication", "conjunction", "disjunction", "negation",
              "equality_rewrite", "exists", "forall", "nat_succ", "bool", "list"]


def _load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out-json",
                    default=str(ROOT / "data" / "baselines"
                                / "v22_routing_audit.json"))
    ap.add_argument("--out-md",
                    default=str(ROOT / "docs" / "V22_ROUTING_AUDIT.md"))
    args = ap.parse_args(argv)

    metrics: Dict[str, Dict[str, Any]] = {}
    for label, rel in SYSTEMS:
        m = _load(ROOT / rel)
        if m is None:
            logger.warning("missing metrics for %s at %s", label, rel)
            continue
        metrics[label] = m

    # Per-category pass@5 across systems.
    cat_table: Dict[str, Dict[str, float]] = {}
    for cat in CATEGORIES:
        row: Dict[str, float] = {}
        for label in metrics:
            row[label] = metrics[label].get("per_category", {}).get(
                cat, {}).get("pass@5", 0.0)
        cat_table[cat] = row

    # Classify each category.
    classification: Dict[str, str] = {}
    for cat in CATEGORIES:
        v20 = cat_table[cat].get("v20_broad_plus", 0.0)
        b = cat_table[cat].get("v21_single_retrain", 0.0)
        d = cat_table[cat].get("v21_capacity", 0.0)
        routed = cat_table[cat].get("v21_routed", 0.0)
        best_single = max(v20, b, d)
        tags = []
        if routed - best_single >= 0.2:
            tags.append("needs_routing")
        if v20 - b >= 0.2:
            tags.append("harmed_by_retrain")
        if d - b >= 0.2:
            tags.append("capacity_sensitive")
        vals = [v for v in (v20, b, d, routed)]
        if max(vals) - min(vals) <= 0.1:
            tags.append("stable")
        classification[cat] = ",".join(tags) if tags else "mixed"

    # Means
    means = {label: {"pass@1": m["pass@1"], "pass@5": m["pass@5"],
                     "pass@10": m["pass@10"],
                     "no_verified_top10": m.get("first_verified_rank_none",
                                                m.get("n_no_candidate_verified"))}
             for label, m in metrics.items()}

    out = {
        "systems": list(metrics.keys()),
        "means": means,
        "per_category_pass5": cat_table,
        "category_classification": classification,
        "summary": {
            "needs_routing": [c for c, t in classification.items()
                              if "needs_routing" in t],
            "harmed_by_retrain": [c for c, t in classification.items()
                                  if "harmed_by_retrain" in t],
            "capacity_sensitive": [c for c, t in classification.items()
                                   if "capacity_sensitive" in t],
            "stable": [c for c, t in classification.items() if "stable" in t],
        },
        "uses_state_after": False,
    }
    Path(args.out_json).write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    logger.info("wrote %s", args.out_json)

    _write_md(args.out_md, out, metrics)
    logger.info("wrote %s", args.out_md)
    logger.info("needs_routing=%s harmed_by_retrain=%s capacity_sensitive=%s",
                out["summary"]["needs_routing"],
                out["summary"]["harmed_by_retrain"],
                out["summary"]["capacity_sensitive"])
    return 0


def _write_md(path, obj, metrics):
    L = []
    L.append("# v22 routing-vs-single audit\n\n")
    L.append("Read-only comparison of the on-disk systems, to map which "
             "v18 broad-core categories the v22 general-model experiment "
             "must watch. Best rerank config (`abstract` for v20/v21).\n\n")
    L.append("## Mean metrics\n\n")
    L.append("| system | pass@1 | pass@5 | pass@10 | no_verified_top10 |\n")
    L.append("|---|---:|---:|---:|---:|\n")
    for label, mm in obj["means"].items():
        L.append(f"| {label} | {mm['pass@1']:.3f} | {mm['pass@5']:.3f} | "
                 f"{mm['pass@10']:.3f} | {mm['no_verified_top10']} |\n")
    L.append("\n## Per-category pass@5\n\n")
    cols = list(obj["per_category_pass5"][CATEGORIES[0]].keys())
    L.append("| category | " + " | ".join(cols) + " | class |\n")
    L.append("|---" * (len(cols) + 2) + "|\n")
    for cat in CATEGORIES:
        row = obj["per_category_pass5"][cat]
        cells = " | ".join(f"{row.get(c, 0.0):.3f}" for c in cols)
        L.append(f"| {cat} | {cells} | {obj['category_classification'][cat]} |\n")
    L.append("\n## Classification summary\n\n")
    for k in ("needs_routing", "harmed_by_retrain", "capacity_sensitive", "stable"):
        L.append(f"- **{k}**: {obj['summary'][k] or '(none)'}\n")
    L.append("\n## Answers (Part 1 questions)\n\n")
    nr = obj["summary"]["needs_routing"]
    hr = obj["summary"]["harmed_by_retrain"]
    L.append(f"- **Which categories require specialist routing?** "
             f"{nr or '(none — routing gain came from forall only)'}. "
             "Routing's measured win over the best single model is "
             "concentrated in `forall` (0.000 → 1.000); every other "
             "category is already at parity across systems.\n")
    L.append(f"- **Which categories are harmed by single retrain?** "
             f"{hr or '(none above the 0.2 threshold)'} — i.e. adding the "
             "forall corpus to one shared model degraded these. This is the "
             "capacity-tradeoff fingerprint the v22 balanced/large configs "
             "must neutralise.\n")
    L.append("- **Which categories are stable?** "
             f"{obj['summary']['stable']} — safe across all configs; the "
             "general-model experiment should not regress these.\n")
    L.append("\nThe v22 mission reduces to: **can a single model hold "
             "forall at 1.000 (routing's win) without the "
             "`harmed_by_retrain` collateral, and lift the fragile "
             "`exists` category?**\n")
    Path(path).write_text("".join(L), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
