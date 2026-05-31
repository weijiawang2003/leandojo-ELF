"""Mini-ELF v12 — evaluate v11 candidates + literal-adapt + reranker.

Composes four configurations on the SAME v11 family-LOFO test set:

  1. ``raw``               — v11 candidates, beam order, no v12 processing.
  2. ``literal_adapt``     — v11 candidates + literal-adapt augmentation,
                             beam order preserved (originals first, adapted
                             appended in dedup order).
  3. ``rerank``            — v11 candidates, reranked.
  4. ``literal_adapt_rerank`` — both: composed candidate list reranked.

Per (fold, config) we compute lean-cli pass@1/5/10 by re-using the
verification cache: every candidate the v11 eval already ran is cached
under ``(theorem_name, tactic) -> result``; new candidates emitted by
the literal-adapt step are verified fresh. The reranker is purely
syntactic and never invokes Lean.

Inputs:
  * ``data/baselines/v11_family_lofo_eval/<fam>/v11/predictions.jsonl``
    (raw model beam output + lean-cli outcomes, per test row).
  * ``data/processed/proof_blocks_v11_family_lofo/<fam>/test.jsonl``
    (state_before / required_operation per row — predictions don't
    carry state_before).
  * ``data/lean_cache/v12_seq2seq_cache.json`` (shared verification
    cache; the v11 cache is also consulted by tactic content).

Outputs (per fold per config):
  * ``data/baselines/v12_eval/<fam>/<config>/metrics.json``
  * ``data/baselines/v12_eval/<fam>/<config>/predictions.jsonl``

This driver does NOT load the seq2seq model; it operates on v11's
already-emitted beam outputs. That makes the v12 evaluation fast and
fully cache-friendly.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import (  # noqa: E402
    VerificationCache, make_lean_cli_verifier,
)
from mini_elf_lean.literal_aware_decode import (  # noqa: E402
    SOURCE_LITERAL_ADAPT, SOURCE_SEQ2SEQ, compose_candidates,
)
from mini_elf_lean.proof_block_reranker import rerank  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v12_literal_rerank")


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


def _load_test_index(test_p: Path) -> Dict[str, Dict[str, Any]]:
    """theorem_name -> the first test.jsonl row carrying it.
    Predictions.jsonl drops state_before; we look it up here."""
    by_name: Dict[str, Dict[str, Any]] = {}
    for r in _read_jsonl(test_p):
        nm = r.get("theorem_name")
        if nm and nm not in by_name:
            by_name[nm] = r
    return by_name


def _load_train_index(train_p: Path) -> set:
    """Gold tactic strings from train.jsonl — used to compute
    novel_verified (verified candidate not seen in train)."""
    out: set = set()
    for r in _read_jsonl(train_p):
        t = r.get("tactic")
        if t:
            out.add(t.strip())
    return out


def _pass_at(verifs: Sequence[Dict[str, Any]], k: int) -> bool:
    for v in verifs[:k]:
        if v.get("success"):
            return True
    return False


def _verify(cache: VerificationCache, verifier, theorem_name: str,
            theorem_statement: str, tactic: str) -> Dict[str, Any]:
    hit = cache.get(theorem_name, tactic)
    if hit is not None:
        return hit
    if verifier is None:
        return {"success": False, "error": "no_verifier", "elapsed_ms": 0.0}
    try:
        res = verifier(theorem_name, theorem_statement, tactic)
    except Exception as exc:  # noqa: BLE001
        res = {"success": False, "error": f"verifier_exception:{exc}",
               "elapsed_ms": 0.0}
    cache.put(theorem_name, tactic, res)
    return res


CONFIGS = ("raw", "literal_adapt", "rerank", "literal_adapt_rerank")


def _make_candidates(
    raw: Sequence[str], *, state_before: str, theorem_statement: str,
    required_operation: Optional[str], config: str,
) -> List[Tuple[str, str]]:
    """Return a list of ``(tactic, source)`` tuples ordered according to
    the chosen config. The reranker is applied last when the config name
    contains ``rerank``."""
    if config == "raw":
        return [(c, SOURCE_SEQ2SEQ) for c in raw]
    composed = compose_candidates(raw, state_before=state_before,
                                  theorem_statement=theorem_statement)
    if config == "literal_adapt":
        return [(t, s) for (t, s, _meta) in composed]
    # reranker variants
    if config == "rerank":
        # Reranker on raw candidates only (no literal-adapt mixed in).
        items = [(c, SOURCE_SEQ2SEQ) for c in raw]
    else:  # literal_adapt_rerank
        items = [(t, s) for (t, s, _meta) in composed]
    reranked = rerank(items, state_before=state_before,
                      required_operation=required_operation)
    return [(c.tactic, c.source) for c in reranked]


def evaluate_fold(*, fam: str, fold_dir: Path, v11_pred_p: Path,
                  out_root: Path, cache: VerificationCache,
                  verifier, k_max: int = 10) -> Dict[str, Any]:
    test_index = _load_test_index(fold_dir / "test.jsonl")
    train_tactics = _load_train_index(fold_dir / "train.jsonl")
    if not v11_pred_p.exists():
        return {"fam": fam, "error": f"missing predictions at {v11_pred_p}"}

    preds = _read_jsonl(v11_pred_p)
    if not preds:
        return {"fam": fam, "error": "empty predictions"}

    summary: Dict[str, Any] = {"fam": fam, "n_test_theorems": len(preds),
                               "configs": {}}

    for config in CONFIGS:
        per_row_records: List[Dict[str, Any]] = []
        pass_k = {1: 0, 5: 0, 10: 0}
        total_verified_cands = 0
        novel_verified = 0
        cross_family_verified = 0
        cross_operation_verified = 0
        literal_adapt_verified = 0
        stale_literal_count = 0
        rank_failure_fixes = 0  # cases where the verifying candidate's
                                # *reranked* position is <= 5 but its
                                # *original* beam position was > 5
        malformed_count = 0

        for pred in preds:
            nm = pred["theorem_name"]
            tr = test_index.get(nm) or {}
            state = tr.get("state_before", "")
            stmt = tr.get("theorem_statement", "")
            req_op = tr.get("required_operation") or pred.get("required_operation")
            raw_cands = pred.get("candidates") or []
            cands = _make_candidates(
                raw_cands, state_before=state, theorem_statement=stmt,
                required_operation=req_op, config=config,
            )[:k_max]
            # Stale-literal count: candidates whose tactic carries a
            # numeric literal that doesn't match the goal's first literal.
            from mini_elf_lean.proof_block_reranker import (
                _first_goal_literal as _gl, _candidate_literals as _cl,
                _is_malformed,
            )
            goal_lit = _gl(state)
            for t, _src in cands:
                cl = _cl(t)
                if goal_lit is not None and cl and goal_lit not in cl:
                    stale_literal_count += 1
                if _is_malformed(t):
                    malformed_count += 1

            verifications: List[Dict[str, Any]] = []
            for t, _src in cands:
                res = _verify(cache, verifier, nm, stmt, t)
                verifications.append(res)

            # pass@k
            p1 = _pass_at(verifications, 1)
            p5 = _pass_at(verifications, 5)
            p10 = _pass_at(verifications, 10)
            pass_k[1] += int(p1)
            pass_k[5] += int(p5)
            pass_k[10] += int(p10)

            fam_absent = pred.get("family_absent_from_train", True)
            op_absent = pred.get("operation_absent_from_train", False)

            verified_indices: List[int] = []
            for j, (t, src) in enumerate(cands):
                if verifications[j].get("success"):
                    verified_indices.append(j)
                    total_verified_cands += 1
                    if t.strip() not in train_tactics:
                        novel_verified += 1
                    if fam_absent:
                        cross_family_verified += 1
                    if op_absent:
                        cross_operation_verified += 1
                    if src == SOURCE_LITERAL_ADAPT:
                        literal_adapt_verified += 1

            # rank_failure_fix metric: the verifying candidate (if any)
            # was at rank > 5 in raw beam but rank <= 5 in this config.
            if config != "raw" and verified_indices:
                top_verified_rank_now = verified_indices[0]
                # find this candidate in raw beam
                first_verified_tactic = cands[top_verified_rank_now][0].strip()
                raw_index = None
                for k, rc in enumerate(raw_cands):
                    if rc.strip() == first_verified_tactic:
                        raw_index = k
                        break
                if (raw_index is not None and raw_index >= 5
                        and top_verified_rank_now < 5):
                    rank_failure_fixes += 1

            per_row_records.append({
                "theorem_name": nm,
                "family_absent_from_train": fam_absent,
                "operation_absent_from_train": op_absent,
                "candidates": [t for t, _ in cands],
                "sources": [s for _, s in cands],
                "verifications": [{"success": bool(v.get("success")),
                                   "error": v.get("error")} for v in verifications],
                "pass@1": p1, "pass@5": p5, "pass@10": p10,
            })

        n = len(preds)
        cfg_summary = {
            "n_test_theorems": n,
            "pass@1": pass_k[1] / n if n else 0.0,
            "pass@5": pass_k[5] / n if n else 0.0,
            "pass@10": pass_k[10] / n if n else 0.0,
            "total_verified_candidates": total_verified_cands,
            "novel_verified": novel_verified,
            "cross_family_verified": cross_family_verified,
            "cross_operation_verified": cross_operation_verified,
            "literal_adapt_verified": literal_adapt_verified,
            "stale_literal_count": stale_literal_count,
            "rank_failure_fixes": rank_failure_fixes,
            "malformed_count": malformed_count,
        }
        # write
        out_dir = out_root / fam / config
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "metrics.json").write_text(
            json.dumps(cfg_summary, indent=2), encoding="utf-8")
        with (out_dir / "predictions.jsonl").open("w", encoding="utf-8") as f:
            for r in per_row_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        summary["configs"][config] = cfg_summary
        logger.info("  %s/%s pass@1=%.3f pass@5=%.3f pass@10=%.3f "
                    "verified=%d novel=%d literal_adapt=%d rank_fix=%d "
                    "malformed=%d stale=%d",
                    fam, config, cfg_summary["pass@1"], cfg_summary["pass@5"],
                    cfg_summary["pass@10"], total_verified_cands,
                    novel_verified, literal_adapt_verified,
                    rank_failure_fixes, malformed_count, stale_literal_count)

    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v11-eval-root",
                    default=str(ROOT / "data" / "baselines" / "v11_family_lofo_eval"))
    ap.add_argument("--v11-fold-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v11_family_lofo"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "baselines" / "v12_eval"))
    ap.add_argument("--cache",
                    default=str(ROOT / "data" / "lean_cache"
                                / "v12_seq2seq_cache.json"))
    ap.add_argument("--verifier-timeout", type=float, default=20.0)
    ap.add_argument("--no-verify", dest="verify", action="store_false")
    ap.set_defaults(verify=True)
    ap.add_argument("--families", nargs="*", default=[
        "forall_inst", "rewrite_succ", "neg_exfalso",
        "exists_reconstruct", "neg_imp_exfalso",
    ])
    args = ap.parse_args(argv)

    cache = VerificationCache.load(Path(args.cache), enabled=True) \
        if args.verify else VerificationCache(enabled=False)
    # Also seed from the v11 cache so verifications already done get a hit
    v11_cache_path = ROOT / "data" / "lean_cache" / "v11_seq2seq_cache.json"
    if v11_cache_path.exists() and args.verify:
        try:
            v11_data = json.loads(v11_cache_path.read_text(encoding="utf-8"))
            for k, v in v11_data.items():
                if k not in cache._store:
                    cache._store[k] = v
            cache.dirty = True
            logger.info("seeded v12 cache with %d entries from v11 cache",
                        len(v11_data))
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not seed from v11 cache: %s", exc)

    verifier = make_lean_cli_verifier(timeout=args.verifier_timeout) \
        if args.verify else None

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    summaries: List[Dict[str, Any]] = []
    for fam in args.families:
        v11_pred = Path(args.v11_eval_root) / fam / "v11" / "predictions.jsonl"
        fold = Path(args.v11_fold_root) / fam
        if not v11_pred.exists() or not fold.exists():
            logger.warning("SKIP %s (missing inputs)", fam)
            continue
        logger.info("EVAL fam=%s", fam)
        s = evaluate_fold(fam=fam, fold_dir=fold, v11_pred_p=v11_pred,
                          out_root=out_root, cache=cache, verifier=verifier)
        summaries.append(s)
        if args.verify:
            cache.save()

    # Combined summary
    (out_root / "v12_summary.json").write_text(
        json.dumps({"folds": summaries}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("ALL V12 EVAL DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
