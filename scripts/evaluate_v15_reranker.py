"""Mini-ELF v15 — evaluate per-fold learned rerankers on v14 candidates.

Reads the **composed** candidate pool (v14 token beam + v12 literal-
aware-decode additions) from v14's ``literal_adapt_rerank`` predictions,
then applies four rerankings on that fixed pool:

  1. ``raw``     — original beam-rank order (seq2seq beam first, then
     seq2seq_literal_adapt appended).
  2. ``rule``    — v12 rule-based reranker on the composed list.
  3. ``learned`` — v15 per-family learned reranker on the composed list.
  4. ``policy``  — operation-aware policy from
     :mod:`mini_elf_lean.v15_rerank_policy` (if importable).

All four configurations see the **identical candidate set**, so
pass@10 is the v14 generator's ceiling and is the same in every
config — only the order changes. The v13 / v14 warm-rerun
corrections are already baked into the verification labels.

Outputs at ``data/baselines/v15_learned_reranker/<fam>/<config>/``;
top-level summary at
``data/baselines/v15_learned_reranker/summary.json``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.learned_reranker import LearnedReranker  # noqa: E402
from mini_elf_lean.proof_block_reranker import rerank as rule_rerank_fn  # noqa: E402
from mini_elf_lean.rerank_dataset import (  # noqa: E402
    CandidateRow, classify_error,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v15_reranker")


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


def _pass_at(verifs: Sequence[Dict[str, Any]], k: int) -> bool:
    for v in verifs[:k]:
        if v.get("success"):
            return True
    return False


def _first_verified_rank(verifs: Sequence[Dict[str, Any]]) -> Optional[int]:
    for i, v in enumerate(verifs):
        if v.get("success"):
            return i
    return None


def _mrr(rows: Sequence[Dict[str, Any]]) -> float:
    total = 0.0
    for r in rows:
        rk = _first_verified_rank(r["verifications"])
        if rk is not None:
            total += 1.0 / (rk + 1)
    return total / max(len(rows), 1)


def _load_test_meta(fold_root: Path,
                    fam: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in _read_jsonl(fold_root / fam / "test.jsonl"):
        nm = r.get("theorem_name")
        if nm and nm not in out:
            out[nm] = r
    return out


def _load_v14_warm_corrections(v14_rerun_root: Path
                               ) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Apply v14 warm-rerun outcomes — required so the learned
    reranker is judged against the same candidate-level labels the
    v14 headline used."""
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    p = v14_rerun_root / "changed_results.jsonl"
    for r in _read_jsonl(p):
        nm = r.get("theorem_name")
        cand = r.get("candidate")
        if nm is None or cand is None:
            continue
        out[(nm, cand)] = {
            "success": bool(r.get("rerun_success")),
            "error": r.get("rerun_error"),
        }
    return out


def _build_composed_pool(
    *, fam: str, v14_root: Path, warm_corrections: Dict[Tuple[str, str], Dict[str, Any]],
    test_meta: Dict[str, Dict[str, Any]],
) -> Dict[str, List[CandidateRow]]:
    """For each test theorem, return the composed candidate pool the
    v14 + LA pipeline produced, with warm-corrected verified labels.

    Combines:
      * v14_raw/predictions.jsonl  — the original v14 token-beam (the
        true beam_rank live here).
      * v14_literal_adapt_rerank/predictions.jsonl — has the LA-added
        candidates AND their verification labels.

    The output ``beam_rank`` is set so:
      * primary (token_seq2seq / seq2seq) candidates carry their
        position in the v14 raw beam (0..9),
      * literal_adapt candidates carry rank 100 + their relative
        position in the LA group (so the raw-config sort places them
        after the primary beam, matching the v12 compose_candidates
        convention).
    """
    raw_p = v14_root / fam / "raw" / "predictions.jsonl"
    lar_p = v14_root / fam / "literal_adapt_rerank" / "predictions.jsonl"
    raw_index: Dict[str, Dict[str, int]] = {}
    for pred in _read_jsonl(raw_p):
        nm = pred["theorem_name"]
        cands = pred.get("candidates") or []
        raw_index[nm] = {c: i for i, c in enumerate(cands)}

    out: Dict[str, List[CandidateRow]] = {}
    for pred in _read_jsonl(lar_p):
        nm = pred["theorem_name"]
        tm = test_meta.get(nm) or {}
        cands = pred.get("candidates") or []
        srcs = pred.get("sources") or []
        vers = pred.get("verifications") or []
        # Walk the composed list once; assign correct beam_ranks.
        la_counter = 0
        rows: List[CandidateRow] = []
        for i, c in enumerate(cands):
            src = srcs[i] if i < len(srcs) else "unknown"
            v = vers[i] if i < len(vers) else {}
            corr = warm_corrections.get((nm, c))
            if corr is not None and v.get("error") == "timeout":
                v = corr
            if src == "seq2seq_literal_adapt":
                # Appended after primary beam — keep relative order.
                beam_rank = 100 + la_counter
                la_counter += 1
            else:
                # Primary beam: look up the candidate's true position
                # in v14_raw. Fallback to composed-list position if not
                # found (shouldn't happen).
                beam_rank = raw_index.get(nm, {}).get(c, i)
            rows.append(CandidateRow(
                theorem_name=nm, family=fam,
                required_operation=tm.get("required_operation"),
                theorem_statement=tm.get("theorem_statement", ""),
                state_before=tm.get("state_before", ""),
                candidate=c,
                candidate_source=src,
                beam_rank=beam_rank,
                verified=bool(v.get("success")),
                error_class=classify_error(v.get("error")),
                source_run="v14_literal_adapt_rerank",
            ))
        out[nm] = rows
    return out


def _order_raw(cand_rows: Sequence[CandidateRow]) -> List[int]:
    """`raw` config: original token-beam order. seq2seq candidates
    come first in their beam_rank order; seq2seq_literal_adapt
    candidates are appended after them, also in beam_rank order. This
    is the order the v14 ``literal_adapt`` (no rerank) config would
    produce."""
    seq2seq_idx: List[int] = []
    la_idx: List[int] = []
    other_idx: List[int] = []
    for i, r in enumerate(cand_rows):
        if r.candidate_source == "seq2seq_literal_adapt":
            la_idx.append(i)
        elif r.candidate_source == "token_seq2seq":
            seq2seq_idx.append(i)
        elif r.candidate_source == "seq2seq":
            # v12 raw label - also treat as primary beam
            seq2seq_idx.append(i)
        else:
            other_idx.append(i)
    # The composed list in v14 literal_adapt_rerank is the v12-reranked
    # order; the underlying beam-rank field is the position in that
    # reranked list (not the true v14 token-beam rank). We approximate
    # the "raw" composed order by sorting by (source-group, beam_rank)
    # which puts primary beam candidates first.
    seq2seq_idx.sort(key=lambda i: cand_rows[i].beam_rank)
    la_idx.sort(key=lambda i: cand_rows[i].beam_rank)
    other_idx.sort(key=lambda i: cand_rows[i].beam_rank)
    return seq2seq_idx + la_idx + other_idx


def _order_rule(cand_rows: Sequence[CandidateRow]) -> List[int]:
    """`rule` config: apply v12 rule-based reranker. Wrap the
    (tactic, source) pairs and map back to indices."""
    if not cand_rows:
        return []
    items = [(r.candidate, r.candidate_source) for r in cand_rows]
    state_before = cand_rows[0].state_before
    required_operation = cand_rows[0].required_operation
    reranked = rule_rerank_fn(items, state_before=state_before,
                              required_operation=required_operation)
    idx_by_tactic: Dict[str, List[int]] = {}
    for j, r in enumerate(cand_rows):
        idx_by_tactic.setdefault(r.candidate, []).append(j)
    order: List[int] = []
    for c in reranked:
        js = idx_by_tactic.get(c.tactic, [])
        if js:
            order.append(js.pop(0))
    # Add any remaining (shouldn't happen but safety)
    seen = set(order)
    for j in range(len(cand_rows)):
        if j not in seen:
            order.append(j)
    return order


def _order_learned(model: LearnedReranker,
                   cand_rows: Sequence[CandidateRow]) -> List[int]:
    if not cand_rows:
        return []
    scored: List[Tuple[int, float, int]] = []
    for i, r in enumerate(cand_rows):
        p = model.score_row(r)
        scored.append((i, p, r.beam_rank))
    scored.sort(key=lambda t: (-t[1], t[2]))
    return [t[0] for t in scored]


def evaluate_family(
    *, fam: str, v14_root: Path, fold_root: Path,
    warm_corrections: Dict[Tuple[str, str], Dict[str, Any]],
    model: LearnedReranker, out_root: Path, policy=None,
) -> Dict[str, Any]:
    test_meta = _load_test_meta(fold_root, fam)
    pool = _build_composed_pool(
        fam=fam, v14_root=v14_root,
        warm_corrections=warm_corrections, test_meta=test_meta,
    )
    if not pool:
        logger.warning("no v14+LA pool for %s", fam)
        return {"fam": fam, "error": "no_pool"}

    configs = ["raw", "rule", "learned"]
    if policy is not None:
        configs.append("policy")

    summary: Dict[str, Any] = {"fam": fam, "n_test_theorems": len(pool),
                               "configs": {}}

    for cfg in configs:
        pass_k = {1: 0, 3: 0, 5: 0, 10: 0}
        per_row: List[Dict[str, Any]] = []
        n_malformed_top1 = 0
        n_false_top1 = 0
        verified_ceiling_match = 0
        for nm, cand_rows in pool.items():
            if cfg == "raw":
                order = _order_raw(cand_rows)
            elif cfg == "rule":
                order = _order_rule(cand_rows)
            elif cfg == "learned":
                order = _order_learned(model, cand_rows)
            elif cfg == "policy":
                order = policy.reorder(
                    cand_rows, model=model,
                    state_before=cand_rows[0].state_before if cand_rows else "",
                    required_operation=(cand_rows[0].required_operation
                                        if cand_rows else None),
                )
            else:  # pragma: no cover
                order = list(range(len(cand_rows)))
            reordered = [cand_rows[j] for j in order]
            verifs = [{"success": r.verified,
                       "error": None if r.verified else r.error_class}
                      for r in reordered]
            p1 = _pass_at(verifs, 1)
            p3 = _pass_at(verifs, 3)
            p5 = _pass_at(verifs, 5)
            p10 = _pass_at(verifs, 10)
            pass_k[1] += int(p1); pass_k[3] += int(p3)
            pass_k[5] += int(p5); pass_k[10] += int(p10)

            top1 = reordered[0] if reordered else None
            if top1 is not None:
                if top1.error_class in {"parse_error", "unknown_tactic"}:
                    n_malformed_top1 += 1
                if not top1.verified:
                    n_false_top1 += 1
            if ({r.candidate for r in reordered if r.verified}
                    == {r.candidate for r in cand_rows if r.verified}):
                verified_ceiling_match += 1

            per_row.append({
                "theorem_name": nm,
                "config": cfg,
                "ordering": [r.candidate for r in reordered][:10],
                "sources": [r.candidate_source for r in reordered][:10],
                "verifications": verifs,
                "pass@1": p1, "pass@3": p3, "pass@5": p5, "pass@10": p10,
                "first_verified_rank": _first_verified_rank(verifs),
                "required_operation": (cand_rows[0].required_operation
                                       if cand_rows else None),
            })

        n = len(pool)
        cfg_metrics = {
            "n_test_theorems": n,
            "pass@1": pass_k[1] / n if n else 0.0,
            "pass@3": pass_k[3] / n if n else 0.0,
            "pass@5": pass_k[5] / n if n else 0.0,
            "pass@10": pass_k[10] / n if n else 0.0,
            "MRR": _mrr(per_row),
            "n_malformed_top1": n_malformed_top1,
            "n_false_top1": n_false_top1,
            "verified_ceiling_match_rows": verified_ceiling_match,
            "config": cfg,
            "uses_state_after": False,
        }
        out_dir = out_root / fam / cfg
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "metrics.json").write_text(
            json.dumps(cfg_metrics, indent=2, ensure_ascii=False),
            encoding="utf-8")
        with (out_dir / "predictions.jsonl").open("w", encoding="utf-8") as f:
            for r in per_row:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        summary["configs"][cfg] = cfg_metrics
        logger.info(
            "  %s/%s pass@1=%.3f pass@3=%.3f pass@5=%.3f pass@10=%.3f "
            "MRR=%.3f mal_top1=%d false_top1=%d ceiling_ok=%d/%d",
            fam, cfg, cfg_metrics["pass@1"], cfg_metrics["pass@3"],
            cfg_metrics["pass@5"], cfg_metrics["pass@10"],
            cfg_metrics["MRR"], n_malformed_top1, n_false_top1,
            verified_ceiling_match, n,
        )

    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v14-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v14_token_seq2seq"))
    ap.add_argument("--v14-rerun-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v14_timeout_rerun"))
    ap.add_argument("--fold-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v11_family_lofo"))
    ap.add_argument("--model-root",
                    default=str(ROOT / "data" / "models" / "v15_reranker"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v15_learned_reranker"))
    ap.add_argument("--families", nargs="*",
                    default=["forall_inst", "rewrite_succ", "neg_exfalso",
                             "exists_reconstruct", "neg_imp_exfalso"])
    ap.add_argument("--with-policy", action="store_true")
    args = ap.parse_args(argv)

    warm = _load_v14_warm_corrections(Path(args.v14_rerun_root))

    policy = None
    if args.with_policy:
        try:
            from mini_elf_lean import v15_rerank_policy
            policy = v15_rerank_policy
        except ImportError:
            logger.warning("v15_rerank_policy module missing; skipping policy")

    summaries: List[Dict[str, Any]] = []
    out_root = Path(args.out_root)
    for fam in args.families:
        model_dir = Path(args.model_root) / fam
        if not (model_dir / "weights.json").exists():
            logger.warning("SKIP %s (no learned reranker)", fam)
            continue
        model = LearnedReranker.load(model_dir)
        s = evaluate_family(
            fam=fam, v14_root=Path(args.v14_root),
            fold_root=Path(args.fold_root), warm_corrections=warm,
            model=model, out_root=out_root, policy=policy,
        )
        summaries.append(s)

    (out_root / "summary.json").write_text(
        json.dumps({"folds": summaries, "uses_state_after": False},
                   indent=2, ensure_ascii=False),
        encoding="utf-8")
    logger.info("V15 EVAL DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
