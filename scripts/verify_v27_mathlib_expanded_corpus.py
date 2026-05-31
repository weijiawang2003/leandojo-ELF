"""Mini-ELF v27 — Part 5a: re-verify the v27 expanded corpus (integrity gate).

Independent re-check of `data/traces/v27_mathlib_expanded_{verified,failed}.jsonl`
with the **trusted** verifier (and a gold one-per-file spot-check on a sample), to
assert:
  * every "verified" row still typechecks under `import Mathlib` (no stale
    positives);
  * every "failed" row is still rejected (no candidate silently became valid);
  * no unverified positive — i.e. no verified row that gold would reject.

Writes `data/baselines/v27_corpus_integrity/report.json`. Exit code is non-zero
iff any verified row fails re-verification or any gold mismatch is found. Real
Lean typecheck; no state_after; manual targets never used as model predictions.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.mathlib_batched_verifier import (  # noqa: E402
    GoldMathlibVerifier, TrustedMathlibVerifier,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("verify_v27_mathlib_expanded_corpus")
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--verified", default=str(ROOT / "data" / "traces" / "v27_mathlib_expanded_verified.jsonl"))
    ap.add_argument("--failed", default=str(ROOT / "data" / "traces" / "v27_mathlib_expanded_failed.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v27_corpus_integrity" / "report.json"))
    ap.add_argument("--gold-sample", type=int, default=24)
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    verified = _read(Path(args.verified))
    failed = _read(Path(args.failed))
    logger.info("re-verifying %d verified + %d failed rows", len(verified), len(failed))

    trusted = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=300)
    trusted.warmup()

    v_items = [(r["theorem_name"], r["theorem_statement"], r["tactic"]) for r in verified]
    f_items = [(r["theorem_name"], r["theorem_statement"], r["tactic"]) for r in failed]

    vv = trusted.verify_many(v_items, confirm=True)
    fv = trusted.verify_many(f_items, confirm=True) if f_items else []

    verified_still_pass = sum(1 for x in vv if x.success)
    verified_regressions = [(x.theorem_name, x.tactic, x.error) for x in vv if not x.success]
    failed_now_pass = [(x.theorem_name, x.tactic) for x in fv if x.success]

    # gold spot-check on a sample of verified rows (strided)
    if v_items and args.gold_sample > 0:
        step = max(1, len(v_items) // args.gold_sample)
        sample = v_items[::step][:args.gold_sample]
        gold = GoldMathlibVerifier(scratch, lean_path=lean_path, timeout=300)
        gv = gold.verify_many(sample)
        gold_mismatches = [(x.theorem_name, x.tactic) for x in gv if not x.success]
    else:
        sample, gold_mismatches = [], []

    report = {
        "config": "v27_corpus_integrity",
        "n_verified": len(verified), "n_failed": len(failed),
        "verified_still_pass": verified_still_pass,
        "n_verified_regressions": len(verified_regressions),
        "verified_regressions": verified_regressions[:20],
        "n_failed_now_pass": len(failed_now_pass),
        "failed_now_pass": failed_now_pass[:20],
        "gold_sample_size": len(sample),
        "n_gold_mismatches": len(gold_mismatches),
        "gold_mismatches": gold_mismatches,
        "integrity_ok": len(verified_regressions) == 0 and len(gold_mismatches) == 0,
        "uses_state_after": False, "uses_manual_oracle": False,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("INTEGRITY: verified_pass=%d/%d regressions=%d failed_now_pass=%d gold_mismatch=%d ok=%s -> %s",
                verified_still_pass, len(verified), len(verified_regressions),
                len(failed_now_pass), len(gold_mismatches), report["integrity_ok"], out)
    return 0 if report["integrity_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
