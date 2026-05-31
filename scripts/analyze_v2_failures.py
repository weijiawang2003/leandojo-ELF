"""Robustness analysis for a Mini-ELF eval directory (Part 8).

Reads a ``predictions.jsonl`` (must have been produced with ``--verify-with-lean-cli``
so each candidate carries a Lean result) and computes:

  * **reranker calibration** — mean score of Lean-verified vs Lean-failed
    candidates, plus top-1 false positives (high score, failed) and false
    negatives (a verified candidate ranked below a failed top-1).
  * **failure taxonomy** — classify the top-1 of each row that failed pass@1
    into a fixed set of error kinds (malformed / incomplete block / wrong
    conjunct / wrong disjunct / wrong iff direction / wrong equality direction /
    wrong witness / missing multistep / unknown), using the heuristic structure
    parser + reranker features.
  * **source effectiveness** — verified counts by candidate source, how many rows
    were rescued by the reranker (a verified candidate the frequency order would
    not have put in the top-1), and verified candidates that only appear below
    the top-5.

Writes ``<dir>/failures_analysis.json`` and optional markdown examples. Read-only
w.r.t. models; no Lean is invoked (it reuses the cached results in the
predictions). Never reads ``state_after``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_elf_lean.elf_rerank import extract_features  # noqa: E402
from mini_elf_lean.elf_structure import parse_prompt  # noqa: E402


def _verified(row, tac) -> bool:
    return bool((row.get("lean_results") or {}).get(tac, {}).get("success"))


def _classify(theorem_statement: str, state_before: str, candidate: str,
              family: Optional[str], requires_multistep: bool) -> str:
    """One error label for a failed top-1 candidate. Heuristic + honest: the
    structural signals (conjunct/disjunct) are reliable; the rest are best-effort
    family/shape buckets. ``known_token_ratio`` / binding are *not* used here
    because ``intro``/``cases`` introduce local names the parser can't see."""
    fr = extract_features(theorem_statement, state_before, candidate)
    d = fr.debug
    st = parse_prompt(theorem_statement, state_before)
    fam = (family or "").lower()

    if d["malformed_prefix"]:            # first token is not a Lean tactic
        return "malformed"
    if d["conjunct_consistency"] < 0:    # projected the wrong conjunct
        return "wrong_conjunct"
    if d["disjunct_consistency"] < 0:    # introduced the wrong disjunct
        return "wrong_disjunct"
    if st.goal_shape == "exists_goal":
        return "wrong_witness"
    if "iff" in fam:
        return "wrong_iff_direction"
    if "eq" in fam:
        return "wrong_equality_direction"
    if requires_multistep:               # incomplete / wrong composition
        return "missing_multistep"
    if not d["balanced_angle"] or d["incomplete_block"]:
        return "incomplete_block"
    return "unknown"


def analyze(predictions: List[Dict[str, Any]], thm2fam: Dict[str, str],
            thm2diff: Dict[str, str], thm2multistep: Dict[str, bool]) -> Dict[str, Any]:
    verified_scores: List[float] = []
    failed_scores: List[float] = []
    taxonomy: Counter = Counter()
    by_source_verified: Counter = defaultdict(int)
    rescued = 0          # verified top-1 that was NOT the highest sample_count candidate
    only_below_top5 = 0  # rows whose only verified candidate is ranked >5
    fp_examples: List[Dict] = []  # high score, failed
    fn_examples: List[Dict] = []  # verified candidate ranked below a failed top-1
    tax_examples: Dict[str, Dict] = {}

    for row in predictions:
        name = row.get("theorem_name", "")
        preds = row.get("predictions") or []
        prov = row.get("prediction_provenance") or [{} for _ in preds]
        stmt, state = row.get("theorem_statement", ""), row.get("state_before", "")

        # calibration + source counts
        best_count, best_count_tac = -1, None
        for i, tac in enumerate(preds):
            sc = prov[i].get("reranker_score") if i < len(prov) else None
            ok = _verified(row, tac)
            if sc is not None:
                (verified_scores if ok else failed_scores).append(sc)
            cnt = prov[i].get("sample_count", 0) if i < len(prov) else 0
            if cnt > best_count:
                best_count, best_count_tac = cnt, tac
            if ok:
                by_source_verified[prov[i].get("source", "?") if i < len(prov) else "?"] += 1

        top1 = preds[0] if preds else ""
        top1_ok = _verified(row, top1)
        # reranker rescue: top-1 verified but it wasn't the most-sampled candidate
        if top1_ok and best_count_tac is not None and top1 != best_count_tac:
            rescued += 1

        # false positive: failed top-1 with a high reranker score
        if not top1_ok and prov and prov[0].get("reranker_score", 0) is not None:
            sc0 = prov[0].get("reranker_score")
            if sc0 is not None and sc0 > 0.7:
                if len(fp_examples) < 8:
                    fp_examples.append({"theorem": name, "candidate": top1, "score": round(sc0, 3)})

        # false negative: a verified candidate ranked below the failed top-1
        if not top1_ok:
            for i, tac in enumerate(preds[1:], start=1):
                if _verified(row, tac):
                    if len(fn_examples) < 8:
                        sc = prov[i].get("reranker_score") if i < len(prov) else None
                        fn_examples.append({"theorem": name, "rank": i + 1, "candidate": tac,
                                            "score": round(sc, 3) if sc is not None else None})
                    break

        # taxonomy of the failed top-1
        if preds and not top1_ok:
            label = _classify(stmt, state, top1, thm2fam.get(name),
                              bool(thm2multistep.get(name)))
            taxonomy[label] += 1
            tax_examples.setdefault(label, {"theorem": name, "goal": state.splitlines()[-1] if state else "",
                                            "top1": top1})

    def _mean(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    return {
        "reranker_calibration": {
            "mean_score_verified": _mean(verified_scores),
            "mean_score_failed": _mean(failed_scores),
            "n_verified_scored": len(verified_scores),
            "n_failed_scored": len(failed_scores),
            "top1_false_positives": fp_examples,
            "top1_false_negatives": fn_examples,
        },
        "failure_taxonomy": dict(taxonomy.most_common()),
        "failure_taxonomy_examples": tax_examples,
        "source_effectiveness": {
            "verified_by_source": dict(by_source_verified),
            "rows_reranker_rescued_top1": rescued,
        },
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--baseline-dir", required=True, type=Path)
    p.add_argument("--seeds", type=Path, nargs="+", default=None)
    p.add_argument("--markdown", type=Path, default=None, help="append example tables to this .md")
    args = p.parse_args(argv)

    preds_path = args.baseline_dir / "predictions.jsonl"
    if not preds_path.exists():
        print(f"error: {preds_path} not found", file=sys.stderr)
        return 2
    predictions = [json.loads(l) for l in preds_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    thm2fam: Dict[str, str] = {}
    thm2diff: Dict[str, str] = {}
    thm2multistep: Dict[str, bool] = {}
    from mini_elf_lean.io_utils import read_jsonl
    for sp in args.seeds or []:
        for row in read_jsonl(sp):
            name = row.get("theorem_name")
            meta = row.get("metadata") or {}
            if name:
                thm2fam[name] = meta.get("pattern_family")
                thm2diff[name] = meta.get("difficulty")
                thm2multistep[name] = bool(meta.get("requires_multistep"))

    out = analyze(predictions, thm2fam, thm2diff, thm2multistep)
    (args.baseline_dir / "failures_analysis.json").write_text(
        json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))

    if args.markdown:
        with args.markdown.open("a", encoding="utf-8") as fh:
            fh.write(f"\n### {args.baseline_dir.name}\n\n")
            cal = out["reranker_calibration"]
            fh.write(f"- reranker mean score: verified={cal['mean_score_verified']} "
                     f"failed={cal['mean_score_failed']}\n")
            fh.write(f"- failure taxonomy: {out['failure_taxonomy']}\n")
            if out["failure_taxonomy_examples"]:
                fh.write("- examples:\n")
                for label, ex in out["failure_taxonomy_examples"].items():
                    fh.write(f"  - `{label}`: {ex['theorem']} goal=`{ex['goal']}` "
                             f"top1=`{ex['top1']}`\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
