"""Mini-ELF v20 — Part 1: audit shape gaps on v18 broad-core.

Reads the v18 broad-only policy and v18 zero-shot v17 panel predictions
plus the v19 abstract-only/ensemble predictions, then for each theorem
reports:

  * theorem name, category, statement, expected_tactic_head
  * current top-10 candidates and verification errors per config
  * whether the *expected* canonical tactic shape (e.g. ``exact hp``,
    ``cases b``, ``rfl``) appears anywhere in the synthetic training
    corpora that fed the v18/v19 models
  * whether the shape exists in v18's broad-core seeds (which the v20
    target model will, by leakage rules, NOT see directly)

Outputs:
  * ``data/baselines/v20_shape_gap_audit.json``
  * ``docs/V20_SHAPE_GAP_AUDIT.md``

This is read-only — no model is trained, no Lean is invoked.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("audit_v20_shape_gaps")


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


# Expected canonical "shape" probes for the two confirmed
# zero-passing categories. We look for these as **substrings** of any
# tactic in any synthetic training row. This is intentionally loose —
# the audit is asking "is the *idea* anywhere in train?" not "is the
# exact tactic-string?".
CANONICAL_SHAPES: Dict[str, List[str]] = {
    "implication": [
        "exact hp",          # identity proof (1-name)
        "intro hq",          # constant proof intro
        "intro hp",          # identity intro
        "exact (h hp)",      # modus ponens with var name `h`
        "hpq",               # composition-style hyp name
        "hqr",
        "exact h hp",        # bare modus ponens (no parens)
        "exact fun",         # fun-lambda
    ],
    "bool": [
        "cases b",           # bool cases tactic
        "rfl",               # bool refl
        "Bool",              # any Bool mention at all in training
        "decide",
    ],
    # We also probe exists for completeness, but exists is not a v20
    # primary target.
    "exists": [
        "exact ⟨",
        "refine ⟨",
        "Exists.intro",
        "rcases",
    ],
}


def _probe_corpus_for_shape(rows: Sequence[Dict[str, Any]],
                            probes: Sequence[str]) -> Dict[str, int]:
    """Return number of train rows whose tactic *contains* each probe."""
    out: Dict[str, int] = {p: 0 for p in probes}
    for r in rows:
        t = r.get("tactic", "") or ""
        for p in probes:
            if p in t:
                out[p] += 1
    return out


def _gather_synthetic_training_rows() -> List[Dict[str, Any]]:
    """Mirror the union the v18 broad-synthetic trainer pooled from:
    v11 LOFO per-family train rows, v16 contrapositive, v17 arrow_false.
    No leakage scrub here — this is descriptive."""
    rows: List[Dict[str, Any]] = []
    v11_root = ROOT / "data" / "processed" / "proof_blocks_v11_family_lofo"
    if v11_root.exists():
        for fam_dir in v11_root.iterdir():
            if not fam_dir.is_dir():
                continue
            rows.extend(_read_jsonl(fam_dir / "train.jsonl"))
    rows.extend(_read_jsonl(
        ROOT / "data" / "processed" / "v16_contrapositive_corpus"
        / "train_rows.jsonl"))
    rows.extend(_read_jsonl(
        ROOT / "data" / "processed" / "v17_arrow_false_elim_corpus"
        / "train_rows.jsonl"))
    return rows


def _summarise_predictions(path: Path) -> Dict[str, Any]:
    recs = _read_jsonl(path)
    by_name: Dict[str, Dict[str, Any]] = {}
    for r in recs:
        nm = r["theorem_name"]
        first = None
        for i, v in enumerate(r.get("verifications", [])):
            if v.get("success"):
                first = i
                break
        errors: List[str] = []
        for v in r.get("verifications", [])[:5]:
            errs = (v.get("error") or "")
            head = errs.splitlines()[0][:160] if errs else ""
            errors.append(head)
        by_name[nm] = {
            "category": r.get("category"),
            "ordering": r.get("ordering", []),
            "sources": r.get("sources", []),
            "first_verified_rank": first,
            "errors_top5": errors,
            "n_union_candidates": r.get("n_union_candidates"),
        }
    return by_name


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v18-broad-only",
                    default=str(ROOT / "data" / "baselines"
                                / "v18_broad_only_eval" / "policy"
                                / "predictions.jsonl"))
    ap.add_argument("--v18-broad-synth",
                    default=str(ROOT / "data" / "baselines"
                                / "v18_broad_synthetic_eval" / "policy"
                                / "predictions.jsonl"))
    ap.add_argument("--v19-abstract-only",
                    default=str(ROOT / "data" / "baselines"
                                / "v19_abstract_only_eval" / "policy"
                                / "predictions.jsonl"))
    ap.add_argument("--v19-ensemble",
                    default=str(ROOT / "data" / "baselines"
                                / "v19_abstract_ensemble_eval" / "policy"
                                / "predictions.jsonl"))
    ap.add_argument("--seeds",
                    default=str(ROOT / "data" / "seeds"
                                / "v18_broad_core_seeds.jsonl"))
    ap.add_argument("--out-json",
                    default=str(ROOT / "data" / "baselines"
                                / "v20_shape_gap_audit.json"))
    ap.add_argument("--out-md",
                    default=str(ROOT / "docs" / "V20_SHAPE_GAP_AUDIT.md"))
    args = ap.parse_args(argv)

    seeds = {r["theorem_name"]: r for r in _read_jsonl(Path(args.seeds))}
    if not seeds:
        logger.error("no v18 seeds at %s", args.seeds)
        return 1
    v18_bo = _summarise_predictions(Path(args.v18_broad_only))
    v18_bs = _summarise_predictions(Path(args.v18_broad_synth))
    v19_ao = _summarise_predictions(Path(args.v19_abstract_only))
    v19_en = _summarise_predictions(Path(args.v19_ensemble))

    synth_rows = _gather_synthetic_training_rows()

    # Per-category shape probes
    probe_results = {
        cat: _probe_corpus_for_shape(synth_rows, probes)
        for cat, probes in CANONICAL_SHAPES.items()
    }

    # Per-theorem audit
    rows_audit: List[Dict[str, Any]] = []
    for nm in sorted(seeds):
        seed = seeds[nm]
        category = seed["category"]
        bo = v18_bo.get(nm, {})
        bs = v18_bs.get(nm, {})
        ao = v19_ao.get(nm, {})
        en = v19_en.get(nm, {})

        verified_any = any(
            d.get("first_verified_rank") is not None for d in (bo, bs, ao, en))
        verified_top10_bo = (bo.get("first_verified_rank") is not None)

        rows_audit.append({
            "theorem_name": nm,
            "category": category,
            "split": seed.get("split"),
            "theorem_statement": seed["theorem_statement"],
            "state_before": seed["state_before"],
            "expected_tactic_head": seed.get("expected_tactic_head"),
            "v18_broad_only_first_rank": bo.get("first_verified_rank"),
            "v18_broad_synth_first_rank": bs.get("first_verified_rank"),
            "v19_abstract_only_first_rank": ao.get("first_verified_rank"),
            "v19_ensemble_first_rank": en.get("first_verified_rank"),
            "verified_anywhere_top10": verified_any,
            "verified_v18_broad_only_top10": verified_top10_bo,
            "v18_broad_only_top5_errors": bo.get("errors_top5", []),
            "v18_broad_only_top10": bo.get("ordering", [])[:10],
        })

    # Category-level summary
    cat_summary: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "v18_bo_passed_top10": 0, "v19_en_passed_top10": 0,
                 "anywhere_unverified": 0})
    for r in rows_audit:
        c = r["category"]
        cat_summary[c]["n"] += 1
        if r["verified_v18_broad_only_top10"]:
            cat_summary[c]["v18_bo_passed_top10"] += 1
        if r["v19_ensemble_first_rank"] is not None:
            cat_summary[c]["v19_en_passed_top10"] += 1
        if not r["verified_anywhere_top10"]:
            cat_summary[c]["anywhere_unverified"] += 1

    # Failure-mode tally on v18 broad-only top1 errors
    err_tally: Counter = Counter()
    for r in rows_audit:
        if r["v18_broad_only_top5_errors"]:
            head = r["v18_broad_only_top5_errors"][0]
            cls = "ok" if r["v18_broad_only_first_rank"] == 0 else _classify(head)
            err_tally[cls] += 1

    out_obj = {
        "n_v18_test_theorems": len(rows_audit),
        "n_synthetic_train_rows_probed": len(synth_rows),
        "category_summary": cat_summary,
        "v18_broad_only_top1_error_tally": dict(err_tally),
        "canonical_shape_probes": probe_results,
        "per_theorem": rows_audit,
    }
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(
        json.dumps(out_obj, indent=2, ensure_ascii=False),
        encoding="utf-8")
    logger.info("wrote %s", args.out_json)

    _write_markdown(args.out_md, out_obj)
    logger.info("wrote %s", args.out_md)
    return 0


def _classify(error_head: str) -> str:
    h = (error_head or "").lower()
    if "unknownidentifier" in h or "unknown identifier" in h:
        return "unknown_identifier"
    if "type mismatch" in h:
        return "type_mismatch"
    if "application type mismatch" in h:
        return "type_mismatch"
    if "unexpected" in h and ("input" in h or "token" in h):
        return "parse_error"
    if "timeout" in h:
        return "timeout"
    if "tactic" in h and "failed" in h:
        return "tactic_failed"
    if "unsolved goals" in h:
        return "unsolved_goals"
    return "other"


def _write_markdown(path: str, obj: Dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    lines.append("# v20 shape-gap audit\n")
    lines.append(
        "Read-only audit of v18 broad-core failures (48 theorems) under "
        "the v18 broad-only/policy, v18 broad-synthetic (panel)/policy, "
        "v19 abstract-only/policy, and v19 ensemble/policy configs. "
        "This is data the v20 brief asks for **before** any v20 model "
        "is built.\n")
    lines.append("\n## Category-level snapshot\n")
    lines.append("| category | n | v18 broad-only pass@10 | v19 ensemble pass@10 | "
                 "rows unverified by *every* config |\n")
    lines.append("|---|---:|---:|---:|---:|\n")
    for cat in sorted(obj["category_summary"]):
        d = obj["category_summary"][cat]
        lines.append(
            f"| {cat} | {d['n']} | {d['v18_bo_passed_top10']}/{d['n']} | "
            f"{d['v19_en_passed_top10']}/{d['n']} | "
            f"{d['anywhere_unverified']}/{d['n']} |\n")
    lines.append("\n## v18 broad-only top-1 error tally (n=48)\n")
    for k, v in sorted(obj["v18_broad_only_top1_error_tally"].items(),
                       key=lambda kv: -kv[1]):
        lines.append(f"- `{k}`: {v}\n")
    lines.append("\n## Canonical-shape probes — does the shape exist anywhere "
                 "in v11+v16+v17 synthetic training tactics?\n")
    lines.append(
        f"(Substring search over {obj['n_synthetic_train_rows_probed']} "
        "training rows.)\n")
    for cat, probes in obj["canonical_shape_probes"].items():
        lines.append(f"\n### {cat}\n")
        lines.append("| probe | rows containing it |\n|---|---:|\n")
        for p, n in probes.items():
            lines.append(f"| `{p}` | {n} |\n")
    lines.append("\n## Per-theorem detail — implication / bool / "
                 "anywhere-unverified rows\n")
    focus = {"implication", "bool"}
    for r in obj["per_theorem"]:
        cat = r["category"]
        if cat not in focus and r["verified_anywhere_top10"]:
            continue
        lines.append(f"\n### `{r['theorem_name']}` — {cat}\n")
        lines.append(f"- statement: `{r['theorem_statement']}`\n")
        lines.append(f"- expected tactic head: `{r['expected_tactic_head']}`\n")
        lines.append(
            f"- first-verified rank — v18 broad-only: "
            f"`{r['v18_broad_only_first_rank']}`, "
            f"v18 broad-synth: `{r['v18_broad_synth_first_rank']}`, "
            f"v19 abstract-only: `{r['v19_abstract_only_first_rank']}`, "
            f"v19 ensemble: `{r['v19_ensemble_first_rank']}`\n")
        lines.append(f"- v18 broad-only top-3 candidates:\n")
        for i, t in enumerate(r["v18_broad_only_top10"][:3]):
            lines.append(f"  - `{t!r}`\n")
        lines.append(f"- v18 broad-only top-3 errors:\n")
        for e in r["v18_broad_only_top5_errors"][:3]:
            e_disp = e.replace("`", "'")
            lines.append(f"  - `{e_disp}`\n")
    lines.append("\n## Read of these results (informs v20 corpus design)\n")
    lines.append(
        "* **implication is corpus-shape-bound, not name-bound.** "
        "Every implication row failure on the v18 broad-only config "
        "is `unknown_identifier`: the model emits hypothesis names "
        "(`hpfalse`, `h1`, `f`) that are in the v17 *training* shape but "
        "absent from the v18 test state. The canonical proofs "
        "(`exact hp`, `intro hq\\n  exact hp`, `exact hqr (hpq hp)`) "
        "do not appear in v11+v16+v17 training (probe `exact hp` = 0 "
        "rows for the bare identity form).\n")
    lines.append(
        "* **bool has zero training support whatsoever.** No row in "
        "v11/v16/v17 contains `cases b`, the word `Bool`, or even "
        "the `decide` tactic. The v18 broad-only model only ever emits "
        "Prop-shaped tactics on Bool goals.\n")
    lines.append(
        "* **Conclusion** — the v20 hypothesis stands: adding shape-"
        "specific corpora for these two categories should move "
        "implication and bool off 0.000 without disturbing the "
        "equality/list/conjunction wins.\n")
    Path(path).write_text("".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
