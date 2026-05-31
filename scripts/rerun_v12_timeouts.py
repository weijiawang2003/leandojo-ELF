"""Mini-ELF v13 — warm-verifier rerun of v12 timeout candidates.

v12 left several forall_inst and one rewrite_succ candidates marked as
``timeout`` by lean-cli (20-s cap, cold-start). For three of those the
adapted candidate is the correct proof shape with the right goal literal
substituted (``exact h 5``, ``exact h 13``, ``exact h 8``), but the
20-s subprocess wall-clock expired before the elaborator finished. The
v12 brief explicitly required reporting those as FAIL — not retconning
them into the would-be 6/7 = 0.857 forall_inst pass@5.

This script re-verifies *only* the v12 timeout candidates at a higher
timeout (default 120 s) — optionally after a one-shot warm-up theorem
that pays the lean JIT/imports cost once before the real reruns. It
never touches the v12 metrics; instead it writes a parallel directory
``data/baselines/v13_timeout_rerun/`` with:

  * ``metrics_original.json`` — snapshot of v12 ``metrics.json`` for
    every (fam, config). Untouched copy of v12.
  * ``metrics_rerun.json``   — corrected metrics computed by replaying
    v12's pass@k logic over each row's verification list, with the
    rerun outcomes substituted into the timed-out slots. v12 lower
    bound vs v13 warm-verifier corrected are reported side-by-side.
  * ``changed_results.jsonl`` — one row per timeout candidate, with
    original vs rerun outcome and (when it changes) the resulting
    row-level pass@1/5/10 flip.
  * ``rerun_log.jsonl``      — verbatim subprocess outcome for every
    candidate the rerun touched (success/fail/timeout, elapsed_ms,
    error truncated).

Constraints honoured (verbatim from v13 brief):
  - Do not change model architecture before rechecking timeouts.
  - Do not retcon previous metrics silently. (v12 originals are preserved
    untouched at their original path; this script writes a *parallel*
    output tree and a corrected-metrics file with both lower bound and
    warm-verifier numbers.)
  - Do not use state_after.
  - Do not count manual oracle candidates.
  - Do not revive leaked v10 metrics.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import make_lean_cli_verifier  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("rerun_v12_timeouts")


# ---------------- helpers ----------------


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


def _index_test_statements(fold_root: Path, families: Sequence[str]) -> Dict[str, str]:
    """theorem_name -> theorem_statement (first occurrence wins)."""
    out: Dict[str, str] = {}
    for fam in families:
        p = fold_root / fam / "test.jsonl"
        for r in _read_jsonl(p):
            nm = r.get("theorem_name")
            st = r.get("theorem_statement")
            if nm and st and nm not in out:
                out[nm] = st
    return out


def _pass_at(verifs: Sequence[Dict[str, Any]], k: int) -> bool:
    for v in verifs[:k]:
        if v.get("success"):
            return True
    return False


def _syntactically_valid(tactic: str) -> bool:
    """Cheap pre-filter: tactics that obviously cannot typecheck
    (mid-token truncations etc.) are excluded so we don't burn a
    120-second subprocess on garbage like ``refintro hn``.

    We only veto tactics that:
      * are empty,
      * end in an unmatched open bracket or pipe,
      * contain a clearly malformed identifier head like ``refintro``
        (well-formed Lean has ``refine`` then a separator).
    Everything else is sent to lean for the true verdict.
    """
    t = tactic.strip()
    if not t:
        return False
    # Obvious truncations / fused tokens. We DO NOT veto on length or on
    # the presence of stray ``.`` or ``[`` — only on patterns that no
    # well-formed tactic ever produces.
    if t in {"refintro", "refintroh"} or t.startswith("refintro "):
        return False
    return True


# ---------------- timeout discovery ----------------


def collect_timeout_candidates(
    v12_root: Path,
    families: Sequence[str],
    config: str = "literal_adapt_rerank",
) -> List[Dict[str, Any]]:
    """Walk v12 predictions and return every timeout candidate row, with
    the metadata needed to re-verify (theorem_name, rank, source,
    candidate string, original error, family, row pass flags)."""
    out: List[Dict[str, Any]] = []
    for fam in families:
        pred_p = v12_root / fam / config / "predictions.jsonl"
        if not pred_p.exists():
            logger.warning("missing v12 predictions: %s", pred_p)
            continue
        for r in _read_jsonl(pred_p):
            cands = r.get("candidates") or []
            srcs = r.get("sources") or []
            verifs = r.get("verifications") or []
            for i, (c, s, v) in enumerate(zip(cands, srcs, verifs)):
                if v.get("error") == "timeout":
                    out.append({
                        "family": fam,
                        "theorem_name": r["theorem_name"],
                        "rank": i,
                        "source": s,
                        "candidate": c,
                        "original_error": v.get("error"),
                        "original_success": bool(v.get("success")),
                        "row_pass@1": bool(r.get("pass@1")),
                        "row_pass@5": bool(r.get("pass@5")),
                        "row_pass@10": bool(r.get("pass@10")),
                        "config": config,
                    })
    return out


def filter_targets(
    cands: Sequence[Dict[str, Any]],
    *,
    families: Sequence[str],
    require_literal_adapt: bool,
    include_part3_rw_h: bool,
    include_completeness: bool,
) -> List[Dict[str, Any]]:
    """Pick which timeout rows to actually re-verify.

    Mirrors the v13 brief's intent: Part 1 hits source=seq2seq_literal_adapt
    timeouts in forall_inst/rewrite_succ; Part 3 explicitly adds the
    rewrite_succ_ij rw [h] (source=seq2seq) row even though its source
    isn't literal_adapt. Completeness mode additionally reruns any other
    syntactically-valid timeout so docs/V13_FAILURE_EXAMPLES.md can audit
    the residual failure types.
    """
    fam_set = set(families)
    out: List[Dict[str, Any]] = []
    for c in cands:
        if c["family"] not in fam_set:
            continue
        if not _syntactically_valid(c["candidate"]):
            continue
        if require_literal_adapt and c["source"] == "seq2seq_literal_adapt":
            out.append(c); continue
        if (include_part3_rw_h
                and c["family"] == "rewrite_succ"
                and c["theorem_name"] == "rewrite_succ_ij"
                and c["candidate"].strip() == "rw [h]"):
            out.append(c); continue
        if include_completeness:
            out.append(c); continue
    # Dedup on (theorem_name, candidate)
    seen = set()
    dedup: List[Dict[str, Any]] = []
    for c in out:
        key = (c["theorem_name"], c["candidate"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(c)
    return dedup


# ---------------- rerun executor ----------------


def warm_up(verifier, *, statement: str = "(x : Nat) : x = x", tactic: str = "rfl") -> Dict[str, Any]:
    """Run one trivial theorem to pay the lean cold-start / JIT cost
    once before the real reruns. Returns the warm-up verifier result so
    callers can log it (and confirm lean is actually on PATH)."""
    t0 = time.perf_counter()
    res = verifier("__v13_warmup__", statement, tactic)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    res = dict(res)
    res["elapsed_ms_total"] = elapsed_ms
    return res


def rerun_one(verifier, *, theorem_name: str, theorem_statement: str, tactic: str) -> Dict[str, Any]:
    t0 = time.perf_counter()
    try:
        res = verifier(theorem_name, theorem_statement, tactic)
    except Exception as exc:  # noqa: BLE001
        res = {"success": False, "error": f"verifier_exception:{exc!r}", "elapsed_ms": 0.0}
    res = dict(res)
    res["wallclock_ms"] = (time.perf_counter() - t0) * 1000.0
    return res


# ---------------- metrics replay ----------------


def replay_metrics(
    v12_root: Path,
    families: Sequence[str],
    rerun_results: Dict[tuple, Dict[str, Any]],  # (theorem_name, candidate) -> rerun result
) -> Dict[str, Any]:
    """Replay v12's per-row pass@k using rerun outcomes substituted
    into the timed-out verification slots. Returns a nested dict
    ``{fam: {config: metrics}}`` parallel to v12 but with corrected
    pass@k where applicable."""
    out: Dict[str, Any] = {}
    for fam in families:
        out[fam] = {}
        fam_dir = v12_root / fam
        if not fam_dir.exists():
            continue
        for cfg_dir in sorted(fam_dir.iterdir()):
            if not cfg_dir.is_dir():
                continue
            pred_p = cfg_dir / "predictions.jsonl"
            metrics_p = cfg_dir / "metrics.json"
            if not (pred_p.exists() and metrics_p.exists()):
                continue
            preds = _read_jsonl(pred_p)
            n = len(preds)
            pass_k = {1: 0, 5: 0, 10: 0}
            row_flips: List[Dict[str, Any]] = []
            for r in preds:
                nm = r["theorem_name"]
                cands = r.get("candidates") or []
                verifs = list(r.get("verifications") or [])
                # Substitute rerun results for any timed-out slot
                changed = False
                for i, (c, v) in enumerate(zip(cands, verifs)):
                    if v.get("error") == "timeout":
                        key = (nm, c)
                        rr = rerun_results.get(key)
                        if rr is not None:
                            verifs[i] = {
                                "success": bool(rr.get("success")),
                                "error": rr.get("error"),
                            }
                            changed = True
                p1, p5, p10 = (_pass_at(verifs, k) for k in (1, 5, 10))
                pass_k[1] += int(p1); pass_k[5] += int(p5); pass_k[10] += int(p10)
                if changed and (p1 != bool(r.get("pass@1"))
                                or p5 != bool(r.get("pass@5"))
                                or p10 != bool(r.get("pass@10"))):
                    row_flips.append({
                        "theorem_name": nm,
                        "config": cfg_dir.name,
                        "family": fam,
                        "original": {"pass@1": bool(r.get("pass@1")),
                                     "pass@5": bool(r.get("pass@5")),
                                     "pass@10": bool(r.get("pass@10"))},
                        "rerun":    {"pass@1": p1, "pass@5": p5, "pass@10": p10},
                    })
            md_original = json.loads(metrics_p.read_text(encoding="utf-8"))
            md_corrected = dict(md_original)
            md_corrected["pass@1"] = pass_k[1] / n if n else 0.0
            md_corrected["pass@5"] = pass_k[5] / n if n else 0.0
            md_corrected["pass@10"] = pass_k[10] / n if n else 0.0
            out[fam][cfg_dir.name] = {
                "n": n,
                "pass@1_original_lower_bound": md_original.get("pass@1"),
                "pass@5_original_lower_bound": md_original.get("pass@5"),
                "pass@10_original_lower_bound": md_original.get("pass@10"),
                "pass@1_warm_rerun": md_corrected["pass@1"],
                "pass@5_warm_rerun": md_corrected["pass@5"],
                "pass@10_warm_rerun": md_corrected["pass@10"],
                "row_flips": row_flips,
            }
    return out


# ---------------- main ----------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v12-root",
                    default=str(ROOT / "data" / "baselines" / "v12_eval"))
    ap.add_argument("--fold-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v11_family_lofo"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "baselines" / "v13_timeout_rerun"))
    ap.add_argument("--families", nargs="*",
                    default=["forall_inst", "rewrite_succ",
                             "exists_reconstruct"])
    ap.add_argument("--timeout", type=float, default=120.0,
                    help="Per-tactic lean-cli timeout in seconds (default 120).")
    ap.add_argument("--no-warmup", dest="warmup", action="store_false")
    ap.set_defaults(warmup=True)
    ap.add_argument("--config", default="literal_adapt_rerank",
                    help="v12 config to enumerate timeouts from. "
                         "literal_adapt_rerank carries the superset of "
                         "candidates so this is the right default.")
    ap.add_argument("--no-literal-adapt", dest="require_literal_adapt",
                    action="store_false",
                    help="Skip the source=seq2seq_literal_adapt filter.")
    ap.set_defaults(require_literal_adapt=True)
    ap.add_argument("--no-part3-rw-h", dest="part3_rw_h", action="store_false",
                    help="Skip the rewrite_succ_ij rw [h] explicit rerun.")
    ap.set_defaults(part3_rw_h=True)
    ap.add_argument("--include-completeness", action="store_true",
                    help="Also rerun every other syntactically-valid timeout "
                         "(non-literal_adapt, non-part3) for audit coverage.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the rerun plan and exit; do not invoke lean.")
    args = ap.parse_args(argv)

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    # 1. Snapshot v12 metrics untouched.
    snapshot: Dict[str, Any] = {}
    for fam in args.families:
        snapshot[fam] = {}
        fam_dir = Path(args.v12_root) / fam
        if not fam_dir.exists():
            continue
        for cfg_dir in sorted(fam_dir.iterdir()):
            mp = cfg_dir / "metrics.json"
            if mp.exists():
                snapshot[fam][cfg_dir.name] = json.loads(mp.read_text(encoding="utf-8"))
    (out_root / "metrics_original.json").write_text(
        json.dumps(snapshot, indent=2), encoding="utf-8")
    logger.info("wrote metrics_original.json snapshot (untouched v12)")

    # 2. Discover timeout candidates.
    all_timeouts = collect_timeout_candidates(
        Path(args.v12_root), args.families, config=args.config)
    targets = filter_targets(
        all_timeouts, families=args.families,
        require_literal_adapt=args.require_literal_adapt,
        include_part3_rw_h=args.part3_rw_h,
        include_completeness=args.include_completeness,
    )
    logger.info("discovered %d total timeout slots; selected %d rerun targets",
                len(all_timeouts), len(targets))

    # Print the rerun plan in dry-run mode and exit before invoking lean.
    plan_path = out_root / "rerun_plan.jsonl"
    with plan_path.open("w", encoding="utf-8") as f:
        for c in targets:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    logger.info("wrote rerun plan to %s", plan_path)
    if args.dry_run:
        logger.info("--dry-run: stopping before lean invocation")
        return 0

    # 3. Map theorem_name -> theorem_statement (predictions don't carry it).
    statements = _index_test_statements(Path(args.fold_root), args.families)
    missing = [c for c in targets if c["theorem_name"] not in statements]
    if missing:
        logger.error(
            "FATAL: %d targets have no theorem_statement in the fold-root: %s",
            len(missing), {c["theorem_name"] for c in missing})
        return 2

    # 4. Build the high-timeout lean-cli verifier (separate from v12's
    #    20-s verifier; we never reuse the v12 cache so timed-out keys
    #    can't hit a stale 'timeout' record).
    verifier = make_lean_cli_verifier(timeout=args.timeout)

    rerun_log: List[Dict[str, Any]] = []
    if args.warmup:
        wu = warm_up(verifier)
        logger.info("warm-up: success=%s error=%r elapsed_ms=%.1f",
                    wu.get("success"), wu.get("error"),
                    wu.get("wallclock_ms", wu.get("elapsed_ms", 0.0)) if isinstance(wu, dict) else 0)
        rerun_log.append({"theorem_name": "__warmup__", "candidate": "rfl",
                          "result": wu})

    # 5. Rerun.
    rerun_results: Dict[tuple, Dict[str, Any]] = {}
    for c in targets:
        nm = c["theorem_name"]
        stmt = statements[nm]
        tactic = c["candidate"]
        logger.info("rerun: %s rank=%d src=%s cand=%r (timeout=%.0fs)",
                    nm, c["rank"], c["source"], tactic, args.timeout)
        res = rerun_one(verifier, theorem_name=nm, theorem_statement=stmt,
                        tactic=tactic)
        rerun_log.append({
            "theorem_name": nm,
            "candidate": tactic,
            "family": c["family"],
            "rank": c["rank"],
            "source": c["source"],
            "original_error": c["original_error"],
            "result": res,
        })
        rerun_results[(nm, tactic)] = res

    # 6. Persist per-candidate log and changed-results jsonl.
    with (out_root / "rerun_log.jsonl").open("w", encoding="utf-8") as f:
        for r in rerun_log:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    changed_path = out_root / "changed_results.jsonl"
    with changed_path.open("w", encoding="utf-8") as f:
        for c in targets:
            rr = rerun_results.get((c["theorem_name"], c["candidate"]))
            if rr is None:
                continue
            flipped = bool(rr.get("success")) and not c["original_success"]
            f.write(json.dumps({
                "theorem_name": c["theorem_name"],
                "family": c["family"],
                "config": c["config"],
                "rank": c["rank"],
                "source": c["source"],
                "candidate": c["candidate"],
                "original": {"success": c["original_success"],
                             "error": c["original_error"]},
                "rerun": {"success": bool(rr.get("success")),
                          "error": rr.get("error")},
                "flipped_timeout_to_verified": flipped,
            }, ensure_ascii=False) + "\n")

    # 7. Replay pass@k metrics with rerun outcomes substituted.
    rerun_metrics = replay_metrics(Path(args.v12_root), args.families, rerun_results)
    (out_root / "metrics_rerun.json").write_text(
        json.dumps(rerun_metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 8. Console summary.
    n_total = len(targets)
    n_verified = sum(1 for c in targets
                     if rerun_results.get((c["theorem_name"], c["candidate"]),
                                          {}).get("success"))
    n_still_timeout = sum(
        1 for c in targets
        if (rerun_results.get((c["theorem_name"], c["candidate"]), {})
            .get("error") == "timeout")
    )
    n_other_fail = n_total - n_verified - n_still_timeout
    logger.info(
        "rerun summary: total=%d verified=%d still_timeout=%d other_fail=%d",
        n_total, n_verified, n_still_timeout, n_other_fail,
    )
    summary = {
        "n_targets": n_total,
        "n_verified_after_rerun": n_verified,
        "n_still_timeout": n_still_timeout,
        "n_other_fail": n_other_fail,
        "timeout_seconds_used": args.timeout,
        "warmup_used": args.warmup,
        "families": list(args.families),
        "config_enumerated": args.config,
    }
    (out_root / "rerun_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
