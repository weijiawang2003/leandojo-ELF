"""Mini-ELF v23 — Part 1: reranker candidate-outcome data audit.

Pools every (theorem, candidate, verified) row the project has produced
into one leakage-trackable dataset for the refreshed reranker, and
reports the counts/imbalance/leakage controls.

Sources (each candidate's verification is theorem-level deterministic,
so the label is consistent across generators):

  * **broad-core evals** (the v23 target distribution): the
    ``raw/predictions.jsonl`` of every v18/v20/v21/v22 broad-core eval
    dir. `raw` carries the full candidate set per theorem (the other
    rerank configs only reorder it). Each row keeps ``category`` and the
    ``source_model`` (the eval dir = which generator produced it).
  * **v15 family data** (auxiliary, disjoint theorems): the v11–v14
    candidate-outcome rows via
    ``rerank_dataset.build_candidate_outcome_dataset`` — extra
    negation/contradiction/forall examples whose theorems never appear
    in the broad-core set, so they are leakage-safe donors.

``state_before`` / ``theorem_statement`` are joined from the v18
broad-core seeds (predictions store only ``theorem_name``). **No
``state_after``** anywhere. Leakage is controlled at *evaluation* time
by leave-one-theorem-out (the row carries ``theorem_name`` so the eval
can exclude the held theorem's rows); this audit just records the pool.

Writes ``data/processed/v23_reranker_data/rows.jsonl`` +
``stats.json`` and ``docs/V23_RERANKER_DATA_AUDIT.md``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.rerank_dataset import (  # noqa: E402
    build_candidate_outcome_dataset, classify_error,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("audit_v23_reranker_data")

# broad-core eval dir -> source_model label.
BROAD_EVALS = {
    "v18_broad_only_eval": "v18_broad_only",
    "v20_broad_plus_eval_timeout_rerun": "v20_broad_plus",
    "v21_broad_plus_forall_eval": "v21_single_retrain",
    "v21_capacity_eval": "v21_capacity",
    "v21_routed_eval": "v21_routed",
    "v22_general_plus_exists_eval": "v22_plus_exists",
    "v22_general_balanced_eval": "v22_balanced",
    "v22_general_large_eval": "v22_large",
    "v22_general_balanced_large_eval": "v22_balanced_large",
}

# v15 family -> a coarse broad-core-ish category tag (legacy donors).
FAMILY_TO_CATEGORY = {
    "neg_exfalso": "negation", "neg_imp_exfalso": "negation",
    "forall_inst": "forall", "rewrite_succ": "equality_rewrite",
    "exists_reconstruct": "exists",
}


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            out.append(json.loads(s))
    return out


def _v18_seed_meta() -> Dict[str, Dict[str, str]]:
    meta: Dict[str, Dict[str, str]] = {}
    for r in _read_jsonl(ROOT / "data" / "seeds" / "v18_broad_core_seeds.jsonl"):
        meta[r["theorem_name"]] = {
            "theorem_statement": r.get("theorem_statement", ""),
            "state_before": r.get("state_before", ""),
        }
    return meta


def build_rows() -> List[Dict[str, Any]]:
    meta = _v18_seed_meta()
    rows: List[Dict[str, Any]] = []

    # ---- broad-core: raw predictions of each eval dir ----
    for eval_dir, model in BROAD_EVALS.items():
        p = ROOT / "data" / "baselines" / eval_dir / "raw" / "predictions.jsonl"
        for r in _read_jsonl(p):
            nm = r["theorem_name"]
            cat = r.get("category", "unknown")
            op = r.get("required_operation")
            m = meta.get(nm, {})
            ordering = r.get("ordering") or []
            sources = r.get("sources") or []
            verifs = r.get("verifications") or []
            for i, cand in enumerate(ordering):
                v = verifs[i] if i < len(verifs) else {}
                rows.append({
                    "theorem_name": nm, "category": cat,
                    "required_operation": op,
                    "theorem_statement": m.get("theorem_statement", ""),
                    "state_before": m.get("state_before", ""),
                    "candidate": cand,
                    "candidate_source": sources[i] if i < len(sources) else "unknown",
                    "beam_rank": i,
                    "verified": bool(v.get("success")),
                    "error_class": classify_error(v.get("error")),
                    "source_model": model,
                    "origin": "broad_core",
                })

    # ---- v15 family donors (auxiliary, disjoint theorems) ----
    fold_root = ROOT / "data" / "processed" / "proof_blocks_family_holdout"
    try:
        fam_rows = build_candidate_outcome_dataset(fold_root=fold_root)
    except Exception as exc:  # noqa: BLE001
        logger.warning("v15 family donor build skipped: %s", exc)
        fam_rows = []
    for cr in fam_rows:
        rows.append({
            "theorem_name": cr.theorem_name, "category": FAMILY_TO_CATEGORY.get(
                cr.family, "legacy"),
            "required_operation": cr.required_operation,
            "theorem_statement": cr.theorem_statement,
            "state_before": cr.state_before,
            "candidate": cr.candidate, "candidate_source": cr.candidate_source,
            "beam_rank": cr.beam_rank, "verified": bool(cr.verified),
            "error_class": cr.error_class, "source_model": f"v15_{cr.source_run}",
            "origin": "family_donor",
        })

    # dedup exact (theorem, candidate, source_model, beam_rank)
    seen = set()
    out = []
    for r in rows:
        k = (r["theorem_name"], r["candidate"], r["source_model"], r["beam_rank"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def compute_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    pos = sum(1 for r in rows if r["verified"])
    by_cat = defaultdict(lambda: {"n": 0, "verified": 0})
    by_model = defaultdict(lambda: {"n": 0, "verified": 0})
    v22bc_by_cat = defaultdict(lambda: {"n": 0, "verified": 0})
    uniq_tc = set()
    for r in rows:
        by_cat[r["category"]]["n"] += 1
        by_cat[r["category"]]["verified"] += int(r["verified"])
        by_model[r["source_model"]]["n"] += 1
        by_model[r["source_model"]]["verified"] += int(r["verified"])
        if r["source_model"] == "v22_plus_exists":
            v22bc_by_cat[r["category"]]["n"] += 1
            v22bc_by_cat[r["category"]]["verified"] += int(r["verified"])
        uniq_tc.add((r["theorem_name"], r["candidate"]))
    return {
        "n_rows": n, "n_positives": pos, "n_negatives": n - pos,
        "positive_fraction": round(pos / n, 4) if n else 0.0,
        "n_unique_theorem_candidate": len(uniq_tc),
        "n_theorems": len({r["theorem_name"] for r in rows}),
        "by_category": {k: dict(v) for k, v in sorted(by_cat.items())},
        "by_source_model": {k: dict(v) for k, v in sorted(by_model.items())},
        "v22_plus_exists_positives_by_category": {
            k: dict(v) for k, v in sorted(v22bc_by_cat.items())},
        "by_error_class": dict(Counter(r["error_class"] for r in rows)),
        "leakage_control": "leave-one-theorem-out at eval time; each row "
                           "carries theorem_name so the held theorem's rows "
                           "are excluded when scoring it.",
        "uses_state_after": False, "uses_manual_oracle": False,
    }


def write_md(path: Path, stats: Dict[str, Any]) -> None:
    L = ["# v23 reranker data audit (Part 1)\n\n",
         "Pooled candidate-outcome dataset for the refreshed reranker. Each "
         "candidate's `verified` label is lean-cli-deterministic at the "
         "theorem level (consistent across generators). **No state_after, no "
         "manual oracle.** Leakage is controlled at eval time by "
         "**leave-one-theorem-out** (rows carry `theorem_name`).\n\n",
         f"- total rows: **{stats['n_rows']}** "
         f"({stats['n_theorems']} theorems, "
         f"{stats['n_unique_theorem_candidate']} unique theorem×candidate)\n",
         f"- positives / negatives: **{stats['n_positives']} / "
         f"{stats['n_negatives']}** "
         f"(positive fraction {stats['positive_fraction']:.3f} — "
         "class imbalance handled by class-weighting, not resampling)\n\n",
         "## Positives by category (all sources)\n\n",
         "| category | rows | verified |\n|---|---:|---:|\n"]
    for k, v in stats["by_category"].items():
        L.append(f"| {k} | {v['n']} | {v['verified']} |\n")
    L.append("\n## Rows by source model\n\n| source_model | rows | verified |\n|---|---:|---:|\n")
    for k, v in stats["by_source_model"].items():
        L.append(f"| {k} | {v['n']} | {v['verified']} |\n")
    L.append("\n## v22 plus_exists broad-core positives by category "
             "(the v23 target distribution)\n\n"
             "| category | rows | verified |\n|---|---:|---:|\n")
    for k, v in stats["v22_plus_exists_positives_by_category"].items():
        L.append(f"| {k} | {v['n']} | {v['verified']} |\n")
    L.append("\n## Error-class distribution\n\n")
    for k, v in sorted(stats["by_error_class"].items(), key=lambda kv: -kv[1]):
        L.append(f"- `{k}`: {v}\n")
    L.append(f"\n**Leakage control:** {stats['leakage_control']}\n")
    path.write_text("".join(L), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out-rows", default=str(ROOT / "data" / "processed"
                                              / "v23_reranker_data" / "rows.jsonl"))
    ap.add_argument("--out-stats", default=str(ROOT / "data" / "processed"
                                               / "v23_reranker_data" / "stats.json"))
    ap.add_argument("--out-md", default=str(ROOT / "docs"
                                            / "V23_RERANKER_DATA_AUDIT.md"))
    args = ap.parse_args(argv)

    rows = build_rows()
    stats = compute_stats(rows)
    out_rows = Path(args.out_rows)
    out_rows.parent.mkdir(parents=True, exist_ok=True)
    with out_rows.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    Path(args.out_stats).write_text(json.dumps(stats, indent=2, ensure_ascii=False),
                                    encoding="utf-8")
    write_md(Path(args.out_md), stats)
    logger.info("v23 reranker data: %d rows, %d positives (%.1f%%), %d theorems",
                stats["n_rows"], stats["n_positives"],
                100 * stats["positive_fraction"], stats["n_theorems"])
    logger.info("wrote %s + %s + %s", args.out_rows, args.out_stats, args.out_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
