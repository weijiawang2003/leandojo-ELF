"""Mini-ELF v16 — Part 1: audit generator-bound failures.

Walks v15 per-config predictions and identifies the rows where:
  * pass@10 = True but pass@5 = False  (rank-bound generator failure)
  * pass@10 = False                    (corpus-shape-bound failure)
  * verified candidate is at rank 5-9   (the v15 reranker can't lift it)

For every such row we emit the candidate string, the operation tag,
the rank under each config (raw/rule/learned/policy), and a sibling-
shape heuristic (does any v11-LOFO train row share its tactic
prefix?).

Outputs:
  * stdout:    a human-readable summary,
  * json:      ``data/baselines/v16_audit/audit.json``,
  * markdown:  fed into ``docs/V16_GENERATOR_BOUND_FAILURE_AUDIT.md``
               (this script writes the .md too).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("audit_v16_generator_bound")

V15_FAMILIES = ("forall_inst", "rewrite_succ", "neg_exfalso",
                "exists_reconstruct", "neg_imp_exfalso")
V15_CONFIGS = ("raw", "rule", "learned", "policy")


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


def _load_v15_per_row(v15_root: Path
                     ) -> Dict[str, Dict[Tuple[str, str], Dict[str, Any]]]:
    """family -> (theorem_name, config) -> row dict."""
    out: Dict[str, Dict[Tuple[str, str], Dict[str, Any]]] = {}
    for fam in V15_FAMILIES:
        out[fam] = {}
        for cfg in V15_CONFIGS:
            p = v15_root / fam / cfg / "predictions.jsonl"
            for r in _read_jsonl(p):
                out[fam][(r["theorem_name"], cfg)] = r
    return out


def _load_train_tactics(fold_root: Path) -> Dict[str, set]:
    """family -> set of train tactic strings (used to flag shape
    presence/absence in train)."""
    out: Dict[str, set] = {}
    for fam in V15_FAMILIES:
        rows = _read_jsonl(fold_root / fam / "train.jsonl")
        out[fam] = {r.get("tactic", "").strip() for r in rows}
    return out


def _has_sibling_shape(candidate: str, train_tactics: set) -> bool:
    """Return True if any train tactic shares a non-trivial prefix
    with the candidate. Used to distinguish 'shape unseen in train'
    vs 'shape seen but model didn't surface it'."""
    if not candidate:
        return False
    head = candidate.split()[0] if candidate.split() else ""
    if not head:
        return False
    for t in train_tactics:
        if t.startswith(head + " ") or t == head:
            return True
        # match longer prefixes (first 8 chars)
        if t[:8] == candidate[:8] and len(candidate) >= 8:
            return True
    return False


def _classify_row(row: Dict[str, Any]) -> str:
    """Categorise the per-row failure."""
    p5 = row.get("pass@5", False)
    p10 = row.get("pass@10", False)
    rank = row.get("first_verified_rank")
    if p5:
        return "pass@5_ok"
    if p10:
        return "rank_bound_top5_to_top10"
    if rank is None:
        return "corpus_shape_bound_no_top10"
    return "other"


def _candidate_at_first_verified(row: Dict[str, Any]) -> Optional[str]:
    rank = row.get("first_verified_rank")
    if rank is None:
        return None
    ords = row.get("ordering") or []
    if 0 <= rank < len(ords):
        return ords[rank]
    return None


def audit(v15_root: Path, fold_root: Path) -> Dict[str, Any]:
    by_row = _load_v15_per_row(v15_root)
    train_tactics = _load_train_tactics(fold_root)

    audit_out: Dict[str, Any] = {"families": {}}
    summary: Dict[str, Any] = {}

    for fam in V15_FAMILIES:
        fam_rows: List[Dict[str, Any]] = []
        theorem_names = sorted({nm for (nm, _) in by_row[fam].keys()})

        for nm in theorem_names:
            policy_row = by_row[fam].get((nm, "policy"))
            if policy_row is None:
                continue
            cls = _classify_row(policy_row)
            entry: Dict[str, Any] = {
                "theorem_name": nm,
                "family": fam,
                "required_operation": policy_row.get("required_operation"),
                "classification_under_policy": cls,
                "first_verified_rank_under": {},
                "candidates_at_first_verified": {},
                "pass_at_under": {},
            }
            for cfg in V15_CONFIGS:
                r = by_row[fam].get((nm, cfg))
                if r is None:
                    continue
                entry["first_verified_rank_under"][cfg] = r.get(
                    "first_verified_rank")
                entry["candidates_at_first_verified"][cfg] = (
                    _candidate_at_first_verified(r))
                entry["pass_at_under"][cfg] = {
                    "pass@1": r.get("pass@1"),
                    "pass@5": r.get("pass@5"),
                    "pass@10": r.get("pass@10"),
                }
            verifying_cand = entry["candidates_at_first_verified"].get("policy")
            if verifying_cand:
                entry["sibling_shape_in_train"] = _has_sibling_shape(
                    verifying_cand, train_tactics.get(fam, set()))
            else:
                entry["sibling_shape_in_train"] = None
            fam_rows.append(entry)

        # Aggregate counts.
        n_rows = len(fam_rows)
        n_pass5 = sum(1 for r in fam_rows
                      if r["classification_under_policy"] == "pass@5_ok")
        n_rank_bound = sum(1 for r in fam_rows
                           if r["classification_under_policy"]
                           == "rank_bound_top5_to_top10")
        n_corpus_bound = sum(1 for r in fam_rows
                             if r["classification_under_policy"]
                             == "corpus_shape_bound_no_top10")
        summary[fam] = {
            "n_test_rows": n_rows,
            "pass@5_ok": n_pass5,
            "rank_bound_top5_to_top10": n_rank_bound,
            "corpus_shape_bound_no_top10": n_corpus_bound,
        }
        audit_out["families"][fam] = {"rows": fam_rows,
                                      "summary": summary[fam]}
    audit_out["aggregate"] = summary
    return audit_out


def write_markdown(out_md: Path, audit_obj: Dict[str, Any]) -> None:
    lines: List[str] = []
    lines.append("# Mini-ELF v16 — Generator-Bound Failure Audit")
    lines.append("")
    lines.append("Auto-generated by `scripts/audit_v16_generator_bound.py`. "
                 "Pin: every row counted here is a row whose policy pass@5 "
                 "is False, classified by whether the verified candidate "
                 "exists in top-10 (rank-bound) or not (corpus-shape-bound).")
    lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append("| family | n_rows | pass@5 ok | rank-bound (5–9) | corpus-shape-bound (>10) |")
    lines.append("|---|---:|---:|---:|---:|")
    for fam, d in audit_obj["aggregate"].items():
        lines.append(f"| `{fam}` | {d['n_test_rows']} | "
                     f"{d['pass@5_ok']} | {d['rank_bound_top5_to_top10']} | "
                     f"{d['corpus_shape_bound_no_top10']} |")
    lines.append("")
    lines.append("## Per-row detail (failing rows only)")
    lines.append("")
    for fam, fam_d in audit_obj["families"].items():
        rows = [r for r in fam_d["rows"]
                if r["classification_under_policy"] != "pass@5_ok"]
        if not rows:
            continue
        lines.append(f"### `{fam}`")
        lines.append("")
        lines.append(
            "| theorem | classification | raw | rule | learned | policy | "
            "policy verified candidate | sibling shape in train |")
        lines.append("|---|---|---:|---:|---:|---:|---|:---:|")
        for r in rows:
            ranks = r["first_verified_rank_under"]
            cand = r["candidates_at_first_verified"].get("policy") or "—"
            cand_s = cand if len(cand) <= 60 else cand[:57] + "..."
            sib = (("✓" if r["sibling_shape_in_train"] else "✗")
                   if r["sibling_shape_in_train"] is not None else "n/a")
            lines.append(
                f"| `{r['theorem_name']}` | {r['classification_under_policy']} | "
                f"{ranks.get('raw','-')} | {ranks.get('rule','-')} | "
                f"{ranks.get('learned','-')} | {ranks.get('policy','-')} | "
                f"`{cand_s}` | {sib} |"
            )
        lines.append("")
    lines.append("## Targeting summary")
    lines.append("")
    rb = sum(d["rank_bound_top5_to_top10"]
             for d in audit_obj["aggregate"].values())
    cb = sum(d["corpus_shape_bound_no_top10"]
             for d in audit_obj["aggregate"].values())
    lines.append(f"* **{rb} rank-bound rows** — verified candidate exists in "
                 f"top-10 but lands at rank 5–9. v16's targeted retrain "
                 f"aims to pull these into top-5.")
    lines.append(f"* **{cb} corpus-shape-bound rows** — no verified "
                 f"candidate in top-10. v16 corpus augmentation aims to "
                 f"give the generator the missing shape.")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v15-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v15_learned_reranker"))
    ap.add_argument("--fold-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v11_family_lofo"))
    ap.add_argument("--out-json",
                    default=str(ROOT / "data" / "baselines"
                                / "v16_audit" / "audit.json"))
    ap.add_argument("--out-md",
                    default=str(ROOT / "docs"
                                / "V16_GENERATOR_BOUND_FAILURE_AUDIT.md"))
    args = ap.parse_args(argv)

    audit_obj = audit(Path(args.v15_root), Path(args.fold_root))
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(audit_obj, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    write_markdown(Path(args.out_md), audit_obj)
    for fam, d in audit_obj["aggregate"].items():
        logger.info("FAM %-22s n=%2d pass@5_ok=%2d rank_bound=%2d shape_bound=%2d",
                    fam, d["n_test_rows"], d["pass@5_ok"],
                    d["rank_bound_top5_to_top10"],
                    d["corpus_shape_bound_no_top10"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
