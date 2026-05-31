"""Mini-ELF v20 — warm-verifier timeout rerun (evaluation-reliability
correction, mirrors the v13/v14 precedent).

The first v20 broad-core eval ran on a WSL instance whose ``lean``
subprocess intermittently returns spurious 30 s timeouts on tactics
that verify in ~0.4 s warm (e.g. ``exact hp`` on
``(p : Prop) (hp : p) : p``). Those spurious timeouts depress the
recorded pass@k.

This script:
  1. Scans the original eval's predictions for every distinct
     ``(theorem, candidate)`` pair whose stored verification is a
     ``timeout``.
  2. Re-verifies each, warm, with one warm-up theorem first and a
     single retry, at a longer timeout.
  3. Patches the on-disk lean cache so flipped (timeout→success or
     timeout→real-error) results are recorded.
  4. Records which pairs flipped.

The corrected metrics are then produced by re-running
``evaluate_v20_broad_core.py --out-root <..._timeout_rerun>`` against
the patched cache — the ORIGINAL ``v20_broad_plus_eval`` metrics on
disk are left untouched (honesty contract: evaluation reliability ≠
model improvement; we never overwrite a published number).

No state_after, no manual oracle, no Mathlib.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import (  # noqa: E402
    VerificationCache, make_lean_cli_verifier,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rerun_v20_timeouts")


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s:
            continue
        out.append(json.loads(s))
    return out


def _collect_timeout_pairs(eval_root: Path,
                           configs: List[str]) -> Dict[Tuple[str, str], str]:
    """Return {(theorem_name, candidate): statement} for every pair
    whose stored verification timed out in any config."""
    pairs: Dict[Tuple[str, str], str] = {}
    # We need the theorem statement to rebuild the seed; pull it from
    # the v18 seeds file.
    seeds = {r["theorem_name"]: r["theorem_statement"]
             for r in _read_jsonl(ROOT / "data" / "seeds"
                                  / "v18_broad_core_seeds.jsonl")}
    for cfg in configs:
        for r in _read_jsonl(eval_root / cfg / "predictions.jsonl"):
            nm = r["theorem_name"]
            for cand, v in zip(r.get("ordering", []),
                               r.get("verifications", [])):
                err = (v.get("error") or "").strip()
                if (not v.get("success")) and err.startswith("timeout"):
                    pairs[(nm, cand)] = seeds.get(nm, "")
    return pairs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--eval-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v20_broad_plus_eval"))
    ap.add_argument("--cache",
                    default=str(ROOT / "data" / "lean_cache"
                                / "v20_broad_plus_cache.json"))
    ap.add_argument("--out-summary",
                    default=str(ROOT / "data" / "baselines"
                                / "v20_broad_plus_eval"
                                / "timeout_rerun_summary.json"))
    ap.add_argument("--verifier-timeout", type=float, default=120.0)
    ap.add_argument("--retries", type=int, default=2)
    args = ap.parse_args(argv)

    eval_root = Path(args.eval_root)
    configs = ["raw", "rule", "learned", "policy", "abstract",
               "policy_abstract"]
    pairs = _collect_timeout_pairs(eval_root, configs)
    logger.info("found %d distinct timeout (theorem,candidate) pairs",
                len(pairs))
    if not pairs:
        logger.info("nothing to rerun")
        return 0

    cache = VerificationCache.load(Path(args.cache), enabled=True)
    verifier = make_lean_cli_verifier(timeout=args.verifier_timeout)

    # Warm up.
    t0 = time.perf_counter()
    wu = verifier("__v20_rerun_warmup__", "(x : Nat) : x = x", "rfl")
    logger.info("warmup: success=%s elapsed_ms=%.1f",
                wu.get("success"), (time.perf_counter() - t0) * 1000.0)

    flipped_to_success: List[Dict[str, str]] = []
    flipped_to_error: List[Dict[str, str]] = []
    still_timeout: List[Dict[str, str]] = []

    for (nm, cand), stmt in sorted(pairs.items()):
        if not stmt:
            logger.warning("no statement for %s; skipping", nm)
            continue
        result = None
        for attempt in range(args.retries + 1):
            res = verifier(nm, stmt, cand)
            result = res
            if res.get("success"):
                break
            err = (res.get("error") or "").strip()
            if not err.startswith("timeout"):
                break  # a real (non-timeout) error — stop retrying
        cache.put(nm, cand, {"success": bool(result.get("success")),
                             "error": result.get("error"),
                             "elapsed_ms": result.get("elapsed_ms")})
        if result.get("success"):
            flipped_to_success.append({"theorem": nm, "candidate": cand})
            logger.info("  FLIP→success %s :: %r", nm, cand[:50])
        elif (result.get("error") or "").strip().startswith("timeout"):
            still_timeout.append({"theorem": nm, "candidate": cand})
            logger.info("  still-timeout %s :: %r", nm, cand[:50])
        else:
            err1 = ((result.get("error") or "").splitlines() or [""])[0]
            flipped_to_error.append({"theorem": nm, "candidate": cand,
                                     "error": err1[:120]})
            logger.info("  →real-error %s :: %r  (%s)", nm, cand[:40],
                        err1[:60])

    cache.save()
    summary = {
        "n_timeout_pairs": len(pairs),
        "n_flipped_to_success": len(flipped_to_success),
        "n_flipped_to_real_error": len(flipped_to_error),
        "n_still_timeout": len(still_timeout),
        "flipped_to_success": flipped_to_success,
        "flipped_to_real_error": flipped_to_error,
        "still_timeout": still_timeout,
        "verifier_timeout_s": args.verifier_timeout,
        "uses_state_after": False,
        "uses_manual_oracle": False,
    }
    Path(args.out_summary).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("timeout rerun: %d→success, %d→real-error, %d still-timeout "
                "(of %d)",
                len(flipped_to_success), len(flipped_to_error),
                len(still_timeout), len(pairs))
    logger.info("cache patched at %s; now re-run evaluate_v20_broad_core.py "
                "with --out-root .../v20_broad_plus_eval_timeout_rerun "
                "and the SAME --cache to publish corrected metrics.",
                args.cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
