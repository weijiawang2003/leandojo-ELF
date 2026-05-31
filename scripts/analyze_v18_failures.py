"""Mini-ELF v18 — Part 7: classify v18 zero-shot failures.

Walks ``data/baselines/v18_zero_shot_v17_pipeline/policy/predictions.jsonl``
and labels every failing top-10 candidate slot with the v18 brief's
taxonomy class. Aggregates per-class counts per-category and emits
``data/baselines/v18_audit/failure_taxonomy.json`` plus a per-row
``classified.jsonl`` for spot-checking.

No new Lean calls — reads existing verification labels.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("analyze_v18_failures")


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


# v18 brief Part 7 taxonomy — order matters (first match wins).
_TAXONOMY = (
    ("verifier_backend_issue",
        re.compile(r"verifier_exception", re.I)),
    ("timeout", re.compile(r"^timeout$", re.I)),
    ("environment_or_import_issue",
        re.compile(r"unknown module|unknown constant", re.I)),
    ("unknown_identifier",
        re.compile(r"unknown identifier", re.I)),
    ("unknown_tactic",
        re.compile(r"unknown tactic", re.I)),
    ("malformed_parse",
        re.compile(r"unexpected end|unexpected token|expected ",
                   re.I)),
    ("type_mismatch_wrong_hypothesis",
        re.compile(r"type mismatch|expected to have type", re.I)),
    ("function_expected",
        re.compile(r"function expected", re.I)),
    ("unsolved_goals",
        re.compile(r"unsolved goals", re.I)),
    ("application_mismatch",
        re.compile(r"application type mismatch|application mismatch",
                   re.I)),
    ("invalid_constructor",
        re.compile(r"invalid `⟨|anonymous constructor", re.I)),
    ("no_goals",
        re.compile(r"no goals", re.I)),
    ("other_error", re.compile(r".+", re.I)),
)


def classify(err: Optional[str]) -> str:
    if not err:
        return "ok"
    for label, rx in _TAXONOMY:
        if rx.search(err):
            return label
    return "uncategorised"


def analyse(preds_path: Path) -> Dict[str, Any]:
    preds = _read_jsonl(preds_path)
    per_category: Dict[str, Dict[str, int]] = {}
    per_class: Dict[str, int] = {}
    per_row_classified: List[Dict[str, Any]] = []
    zero_top10 = 0
    n_total_rows = len(preds)
    n_total_slots = 0
    n_ok_slots = 0

    for r in preds:
        cat = r.get("category", "?")
        per_cat = per_category.setdefault(cat, {})
        any_verified = False
        row_class: Dict[str, int] = {}
        per_slot_classes: List[str] = []
        for v in r.get("verifications", []):
            n_total_slots += 1
            cls = classify(v.get("error")) if not v.get("success") else "ok"
            if cls == "ok":
                n_ok_slots += 1
                any_verified = True
            per_class[cls] = per_class.get(cls, 0) + 1
            per_cat[cls] = per_cat.get(cls, 0) + 1
            row_class[cls] = row_class.get(cls, 0) + 1
            per_slot_classes.append(cls)
        if not any_verified:
            zero_top10 += 1
        per_row_classified.append({
            "theorem_name": r["theorem_name"],
            "category": cat,
            "pass@5": r.get("pass@5"),
            "pass@10": r.get("pass@10"),
            "first_verified_rank": r.get("first_verified_rank"),
            "slot_classes": per_slot_classes,
            "class_counts": row_class,
        })

    return {
        "n_rows": n_total_rows,
        "n_top10_slots": n_total_slots,
        "n_ok_slots": n_ok_slots,
        "n_zero_top10_rows": zero_top10,
        "per_class_total": dict(sorted(per_class.items(),
                                       key=lambda kv: -kv[1])),
        "per_category_class_counts": per_category,
        "per_row_classified": per_row_classified,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--predictions",
                    default=str(ROOT / "data" / "baselines"
                                / "v18_zero_shot_v17_pipeline" / "policy"
                                / "predictions.jsonl"))
    ap.add_argument("--out-dir",
                    default=str(ROOT / "data" / "baselines" / "v18_audit"))
    args = ap.parse_args(argv)

    result = analyse(Path(args.predictions))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Don't blast per_row_classified into the headline json — split.
    headline = {k: v for k, v in result.items()
                if k != "per_row_classified"}
    (out_dir / "failure_taxonomy.json").write_text(
        json.dumps(headline, indent=2, ensure_ascii=False),
        encoding="utf-8")
    with (out_dir / "classified.jsonl").open("w", encoding="utf-8") as f:
        for r in result["per_row_classified"]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    logger.info("v18 failure taxonomy: rows=%d slots=%d ok=%d "
                "no-verify-rows=%d",
                result["n_rows"], result["n_top10_slots"],
                result["n_ok_slots"], result["n_zero_top10_rows"])
    for k, v in result["per_class_total"].items():
        logger.info("  %-32s %4d", k, v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
