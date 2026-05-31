"""Mini-ELF v14 — warm-verifier rerun for v14 timeout candidates.

Same protocol as ``rerun_v12_timeouts.py`` but pointed at v14 outputs
(``data/baselines/v14_token_seq2seq/``). v14's initial eval at 120 s
saw 17 unique (theorem, candidate) timeouts even with a warm-up — the
lean-cli subprocess pays cold-start cost on every fresh invocation,
and the v14 cache started empty.

The rerun:

  1. Snapshots the v14 metrics_original (so the lower-bound is preserved
     for auditing).
  2. Discovers every (theorem, candidate) pair with ``error=='timeout'``
     across the v14 raw/literal_adapt_rerank predictions for all
     5 families.
  3. Runs a warm-up theorem.
  4. Re-verifies each unique timeout at ``timeout=180 s`` (a step up
     from 120 s, since some candidates need more elaborator budget).
  5. Replays pass@k with rerun outcomes substituted into the timed-out
     slots — same algorithm as v13's replay.

Outputs land at ``data/baselines/v14_timeout_rerun/``:
  * ``metrics_original.json`` — snapshot of v14 metrics
  * ``metrics_rerun.json``    — corrected pass@k per (fam, config)
  * ``changed_results.jsonl`` — per-candidate flip record
  * ``rerun_log.jsonl``       — verbatim subprocess outcomes
  * ``rerun_summary.json``    — counts

v12 and v13 metrics on disk are NOT touched.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import make_lean_cli_verifier  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rerun_v14_timeouts")


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


def _index_statements(fold_root: Path,
                      families: Sequence[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for fam in families:
        for r in _read_jsonl(fold_root / fam / "test.jsonl"):
            nm = r.get("theorem_name")
            st = r.get("theorem_statement")
            if nm and st and nm not in out:
                out[nm] = st
    return out


def discover_timeouts(v14_root: Path,
                      families: Sequence[str]) -> List[Dict[str, Any]]:
    """Walk v14 predictions and return every distinct
    (theorem, candidate) pair with error == 'timeout'."""
    seen = set()
    out: List[Dict[str, Any]] = []
    for fam in families:
        for cfg in ("raw", "literal_adapt_rerank"):
            p = v14_root / fam / cfg / "predictions.jsonl"
            for r in _read_jsonl(p):
                cands = r.get("candidates") or []
                verifs = r.get("verifications") or []
                for i, (c, v) in enumerate(zip(cands, verifs)):
                    if v.get("error") == "timeout":
                        key = (r["theorem_name"], c)
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append({
                            "family": fam,
                            "theorem_name": r["theorem_name"],
                            "rank_in_cfg": i,
                            "candidate": c,
                            "config_seen": cfg,
                        })
    return out


def replay_v14_metrics(v14_root: Path, families: Sequence[str],
                       rerun: Dict[tuple, Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for fam in families:
        out[fam] = {}
        fam_dir = v14_root / fam
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
                changed = False
                for i, (c, v) in enumerate(zip(cands, verifs)):
                    if v.get("error") == "timeout":
                        key = (nm, c)
                        rr = rerun.get(key)
                        if rr is not None:
                            verifs[i] = {
                                "success": bool(rr.get("success")),
                                "error": rr.get("error"),
                            }
                            changed = True
                p1, p5, p10 = (_pass_at(verifs, k) for k in (1, 5, 10))
                pass_k[1] += int(p1); pass_k[5] += int(p5); pass_k[10] += int(p10)
                if changed and (p5 != bool(r.get("pass@5"))):
                    row_flips.append({
                        "theorem_name": nm,
                        "config": cfg_dir.name,
                        "family": fam,
                        "pass@5_original": bool(r.get("pass@5")),
                        "pass@5_warm_rerun": p5,
                    })
            orig = json.loads(metrics_p.read_text(encoding="utf-8"))
            out[fam][cfg_dir.name] = {
                "n": n,
                "pass@1_original_lower_bound": orig.get("pass@1"),
                "pass@5_original_lower_bound": orig.get("pass@5"),
                "pass@10_original_lower_bound": orig.get("pass@10"),
                "pass@1_warm_rerun": pass_k[1] / n if n else 0.0,
                "pass@5_warm_rerun": pass_k[5] / n if n else 0.0,
                "pass@10_warm_rerun": pass_k[10] / n if n else 0.0,
                "row_flips": row_flips,
            }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--v14-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v14_token_seq2seq"))
    ap.add_argument("--fold-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v11_family_lofo"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v14_timeout_rerun"))
    ap.add_argument("--families", nargs="*",
                    default=["forall_inst", "rewrite_succ", "neg_exfalso",
                             "exists_reconstruct", "neg_imp_exfalso"])
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args(argv)

    v14_root = Path(args.v14_root)
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    # 1. Snapshot v14 metrics.
    snap: Dict[str, Any] = {}
    for fam in args.families:
        snap[fam] = {}
        fam_dir = v14_root / fam
        if not fam_dir.exists():
            continue
        for cfg_dir in sorted(fam_dir.iterdir()):
            mp = cfg_dir / "metrics.json"
            if mp.exists():
                snap[fam][cfg_dir.name] = json.loads(mp.read_text(encoding="utf-8"))
    (out_root / "metrics_original.json").write_text(
        json.dumps(snap, indent=2), encoding="utf-8")

    # 2. Discover.
    targets = discover_timeouts(v14_root, args.families)
    logger.info("v14 timeout candidates: %d unique", len(targets))
    with (out_root / "rerun_plan.jsonl").open("w", encoding="utf-8") as f:
        for t in targets:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    # 3. Map names to statements.
    statements = _index_statements(Path(args.fold_root), args.families)

    # 4. Warm-up + rerun.
    verifier = make_lean_cli_verifier(timeout=args.timeout)
    rerun_log: List[Dict[str, Any]] = []
    t0 = time.perf_counter()
    wu = verifier("__v14_rerun_warmup__", "(x : Nat) : x = x", "rfl")
    rerun_log.append({"theorem_name": "__warmup__", "candidate": "rfl",
                      "result": dict(wu, wallclock_ms=(time.perf_counter() - t0) * 1000.0)})
    logger.info("warmup: success=%s err=%r", wu.get("success"), wu.get("error"))

    results: Dict[tuple, Dict[str, Any]] = {}
    for c in targets:
        nm = c["theorem_name"]
        stmt = statements.get(nm)
        if stmt is None:
            logger.warning("SKIP %s (no statement)", nm)
            continue
        logger.info("rerun: %s cand=%r", nm, c["candidate"])
        t0 = time.perf_counter()
        try:
            res = verifier(nm, stmt, c["candidate"])
        except Exception as exc:  # noqa: BLE001
            res = {"success": False, "error": f"verifier_exception:{exc!r}"}
        wall = (time.perf_counter() - t0) * 1000.0
        results[(nm, c["candidate"])] = res
        rerun_log.append({
            "theorem_name": nm, "candidate": c["candidate"],
            "family": c["family"],
            "result": dict(res, wallclock_ms=wall),
        })

    # 5. Persist log + changed-results.
    with (out_root / "rerun_log.jsonl").open("w", encoding="utf-8") as f:
        for r in rerun_log:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    with (out_root / "changed_results.jsonl").open("w", encoding="utf-8") as f:
        for c in targets:
            rr = results.get((c["theorem_name"], c["candidate"]))
            if rr is None:
                continue
            flipped = bool(rr.get("success"))
            f.write(json.dumps({
                "family": c["family"],
                "theorem_name": c["theorem_name"],
                "candidate": c["candidate"],
                "rerun_success": flipped,
                "rerun_error": rr.get("error"),
                "flipped_timeout_to_verified": flipped,
            }, ensure_ascii=False) + "\n")

    # 6. Replay metrics.
    rerun_metrics = replay_v14_metrics(v14_root, args.families, results)
    (out_root / "metrics_rerun.json").write_text(
        json.dumps(rerun_metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    n_total = len(targets)
    n_verified = sum(1 for c in targets
                     if results.get((c["theorem_name"], c["candidate"]),
                                    {}).get("success"))
    n_still_timeout = sum(
        1 for c in targets
        if results.get((c["theorem_name"], c["candidate"]), {}).get("error") == "timeout"
    )
    summary = {
        "n_targets": n_total,
        "n_verified_after_rerun": n_verified,
        "n_still_timeout": n_still_timeout,
        "n_other_fail": n_total - n_verified - n_still_timeout,
        "timeout_seconds_used": args.timeout,
        "families": list(args.families),
    }
    (out_root / "rerun_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("v14 rerun summary: total=%d verified=%d still_timeout=%d",
                n_total, n_verified, n_still_timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
