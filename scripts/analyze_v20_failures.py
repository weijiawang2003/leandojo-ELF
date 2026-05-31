"""Mini-ELF v20 — Part 7: failure analysis on the v20 broad-core
evaluation predictions.

For every theorem where the chosen config (default ``policy``) did
NOT verify within the first 10 candidates, classify the failure:

  * ``no_schema_in_beam``  — none of the beam candidates is even
    structurally close to the expected canonical shape
  * ``wrong_var_name``     — beam contains correct-shaped candidate
    but referencing a name not in scope
  * ``wrong_case_syntax``  — bool/disjunction case-split syntax variant
    Lean rejects
  * ``type_mismatch``      — Lean type error
  * ``parse_error``        — Lean parse error
  * ``tactic_unavailable`` — `simpa`, mathlib, etc. unavailable
  * ``corpus_mismatch``    — exists in synth train but never in beam

Outputs:
  * ``data/baselines/v20_failure_analysis.json``
  * ``docs/V20_FAILURE_EXAMPLES.md``
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("analyze_v20_failures")


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def _classify_error(error_head: str) -> str:
    h = (error_head or "").lower()
    if not h:
        return "ok"
    if "unknownidentifier" in h or "unknown identifier" in h:
        return "unknown_identifier"
    if "type mismatch" in h or "application type mismatch" in h:
        return "type_mismatch"
    if "tactic" in h and ("failed" in h or "did not" in h):
        return "tactic_failed"
    if "unexpected" in h and ("input" in h or "token" in h):
        return "parse_error"
    if "timeout" in h:
        return "timeout"
    if "unsolved" in h:
        return "unsolved_goals"
    if "unknown tactic" in h or "unknown_tactic" in h:
        return "unknown_tactic"
    return "other"


# Per-category "canonical proof head" prefixes. If none of the
# beam candidates starts with any of these, we classify
# `no_schema_in_beam`.
CANONICAL_HEADS: Dict[str, List[str]] = {
    "implication":      ["exact ", "intro ", "apply ", "exact fun"],
    "conjunction":      ["exact ", "constructor", "And.intro"],
    "disjunction":      ["exact ", "cases ", "Or.inl", "Or.inr"],
    "negation":         ["intro ", "exact ", "exfalso"],
    "equality_rewrite": ["exact ", "rw ", "rfl", "simp"],
    "exists":           ["exact ⟨", "refine ⟨", "use ", "exact "],
    "forall":           ["intro ", "exact "],
    "nat_succ":         ["rfl", "exact ", "rw ", "simp", "decide"],
    "bool":             ["cases ", "rfl", "exact ", "decide", "rw ",
                         "simp", "by"],
    "list":             ["rfl", "exact ", "rw ", "simp"],
}


def _has_schema_head(top10: Sequence[str], heads: Sequence[str]) -> bool:
    for c in top10:
        first_line = (c or "").splitlines()[0] if c else ""
        for h in heads:
            if first_line.startswith(h):
                return True
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--predictions",
                    default=str(ROOT / "data" / "baselines"
                                / "v20_broad_plus_eval" / "policy"
                                / "predictions.jsonl"))
    ap.add_argument("--alt-config-roots", nargs="*",
                    default=[
                        str(ROOT / "data" / "baselines" / "v20_broad_plus_eval"
                            / "abstract" / "predictions.jsonl"),
                        str(ROOT / "data" / "baselines" / "v20_broad_plus_eval"
                            / "policy_abstract" / "predictions.jsonl"),
                    ])
    ap.add_argument("--seeds",
                    default=str(ROOT / "data" / "seeds"
                                / "v18_broad_core_seeds.jsonl"))
    ap.add_argument("--out-json",
                    default=str(ROOT / "data" / "baselines"
                                / "v20_failure_analysis.json"))
    ap.add_argument("--out-md",
                    default=str(ROOT / "docs" / "V20_FAILURE_EXAMPLES.md"))
    args = ap.parse_args(argv)

    seeds = {r["theorem_name"]: r for r in _read_jsonl(Path(args.seeds))}
    preds = _read_jsonl(Path(args.predictions))
    alt_by_name = {}
    for alt in args.alt_config_roots:
        cfg_name = Path(alt).parent.name
        for r in _read_jsonl(Path(alt)):
            alt_by_name.setdefault(r["theorem_name"], {})[cfg_name] = r

    fails: List[Dict[str, Any]] = []
    cls_tally: Counter = Counter()
    for r in preds:
        if r.get("first_verified_rank") is not None:
            continue
        nm = r["theorem_name"]
        cat = r["category"]
        seed = seeds.get(nm, {})
        ordering = r.get("ordering", [])
        verifs = r.get("verifications", [])
        # Primary error class from top1 error
        head = ""
        if verifs:
            head = (verifs[0].get("error") or "").splitlines()[0]
        primary_err = _classify_error(head)
        heads = CANONICAL_HEADS.get(cat, [])
        in_beam = _has_schema_head(ordering[:10], heads)
        if not in_beam:
            cls = "no_schema_in_beam"
        elif primary_err == "unknown_identifier":
            cls = "wrong_var_name"
        elif primary_err == "type_mismatch":
            cls = "type_mismatch"
        elif primary_err == "parse_error":
            cls = "parse_error"
        elif primary_err == "tactic_failed":
            cls = "tactic_failed"
        elif primary_err == "unsolved_goals":
            cls = "unsolved_goals"
        elif primary_err == "timeout":
            cls = "timeout"
        else:
            cls = primary_err
        cls_tally[cls] += 1
        fails.append({
            "theorem_name": nm,
            "category": cat,
            "expected_tactic_head": seed.get("expected_tactic_head"),
            "theorem_statement": seed.get("theorem_statement"),
            "state_before": seed.get("state_before"),
            "failure_class": cls,
            "top10": ordering[:10],
            "top5_errors": [
                ((v.get("error") or "").splitlines() or [""])[0][:140]
                for v in verifs[:5]
            ],
            "alt_configs": {
                cfg: alt_by_name.get(nm, {}).get(cfg, {}).get(
                    "first_verified_rank")
                for cfg in {Path(a).parent.name for a in args.alt_config_roots}
            },
        })

    out_obj = {
        "n_total_theorems": len(preds),
        "n_failed_top10_policy": len(fails),
        "failure_class_tally": dict(cls_tally),
        "per_failure": fails,
    }
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(
        json.dumps(out_obj, indent=2, ensure_ascii=False),
        encoding="utf-8")
    logger.info("wrote %s", args.out_json)

    # Markdown
    Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    lines.append("# v20 failure examples\n")
    lines.append(
        f"v20 broad-plus policy: {len(preds)} theorems, "
        f"{len(fails)} unverified at top-10.\n")
    lines.append("\n## Failure-class tally\n")
    for k, n in sorted(cls_tally.items(), key=lambda kv: -kv[1]):
        lines.append(f"- `{k}`: {n}\n")
    lines.append("\n## Per-theorem detail\n")
    for f in fails:
        lines.append(f"\n### `{f['theorem_name']}` — {f['category']} — "
                     f"`{f['failure_class']}`\n")
        lines.append(f"- statement: `{f['theorem_statement']}`\n")
        lines.append(f"- expected head: `{f['expected_tactic_head']}`\n")
        lines.append("- alt-config first-verified rank: "
                     + str(f["alt_configs"]) + "\n")
        lines.append("- top-3 candidates:\n")
        for c in f["top10"][:3]:
            lines.append(f"  - `{c!r}`\n")
        lines.append("- top-3 errors:\n")
        for e in f["top5_errors"][:3]:
            e_disp = (e or "").replace("`", "'")
            lines.append(f"  - `{e_disp}`\n")
    Path(args.out_md).write_text("".join(lines), encoding="utf-8")
    logger.info("wrote %s", args.out_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
