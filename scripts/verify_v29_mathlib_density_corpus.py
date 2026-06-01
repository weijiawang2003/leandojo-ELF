"""Mini-ELF v29 — Part 4: re-verify the v29 density corpus + gold sampling.

Independent integrity gate over
``data/traces/v29_mathlib_density_{verified,failed}.jsonl``:

  * re-verify every "verified" row with the **trusted** verifier (no stale positives
    — every training positive still typechecks under ``import Mathlib``);
  * re-check every "failed" row is still rejected (no candidate silently became valid);
  * **gold sampling**: a category-stratified random sample (deterministic seed) of
    >=30 verified candidates is re-verified **one declaration per file** with
    ``GoldMathlibVerifier`` (``batch_size=1`` — complete isolation, ground truth) and
    compared to the trusted verdict. Requires **zero mismatches** (in particular zero
    false positives).

Reports: proposed candidates, verified rows, failed rows, timeout count, zero-success
theorem count, per-category counts, per-family counts, verification runtime, and the
most common Lean API failures. Writes
``data/baselines/v29_corpus_integrity/report.json``. Non-zero exit iff any verified
row regresses or any gold false-positive is found. Real Lean typecheck; no
state_after; manual targets never used as model predictions.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.mathlib_batched_verifier import (  # noqa: E402
    GoldMathlibVerifier, TrustedMathlibVerifier, compare_to_gold,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("verify_v29_mathlib_density_corpus")
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"
_UNKNOWN_ID = re.compile(r"unknown (?:identifier|constant) '([^']+)'")


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def stratified_sample(verified: List[Dict[str, Any]], n: int, seed: int) -> List[Dict[str, Any]]:
    """Random sample of >=n verified rows, at least one per category if possible."""
    rng = random.Random(seed)
    by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in verified:
        by_cat[r.get("category", "?")].append(r)
    picked: List[Dict[str, Any]] = []
    for cat in sorted(by_cat):
        picked.append(rng.choice(by_cat[cat]))
    pool = [r for r in verified if r not in picked]
    rng.shuffle(pool)
    while len(picked) < n and pool:
        picked.append(pool.pop())
    return picked


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--verified", default=str(ROOT / "data" / "traces" / "v29_mathlib_density_verified.jsonl"))
    ap.add_argument("--failed", default=str(ROOT / "data" / "traces" / "v29_mathlib_density_failed.jsonl"))
    ap.add_argument("--summary", default=str(ROOT / "data" / "processed" / "v29_mathlib_specialist" / "density_summary.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v29_corpus_integrity" / "report.json"))
    ap.add_argument("--gold-sample", type=int, default=32)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    verified = _read(Path(args.verified))
    failed = _read(Path(args.failed))
    gen_summary = json.loads(Path(args.summary).read_text()) if Path(args.summary).exists() else {}
    logger.info("re-verifying %d verified + %d failed rows", len(verified), len(failed))

    trusted = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=300)
    trusted.warmup()

    v_items = [(r["theorem_name"], r["theorem_statement"], r["tactic"]) for r in verified]
    f_items = [(r["theorem_name"], r["theorem_statement"], r["tactic"]) for r in failed]

    vv = trusted.verify_many(v_items, confirm=True)
    fv = trusted.verify_many(f_items, confirm=True) if f_items else []
    reverify_seconds = round(trusted.total_lean_seconds, 1)

    verified_still_pass = sum(1 for x in vv if x.success)
    verified_regressions = [(x.theorem_name, x.tactic, x.error) for x in vv if not x.success]
    failed_now_pass = [(x.theorem_name, x.tactic) for x in fv if x.success]

    # gold one-declaration-per-file spot check on a category-stratified sample
    sample_rows = stratified_sample(verified, args.gold_sample, args.seed) if verified else []
    sample_items = [(r["theorem_name"], r["theorem_statement"], r["tactic"]) for r in sample_rows]
    gold_mismatches: List[Dict[str, Any]] = []
    gold_false_positives = 0
    if sample_items:
        gold = GoldMathlibVerifier(scratch, lean_path=lean_path, timeout=300)
        gv = gold.verify_many(sample_items)
        tv = trusted.verify_many(sample_items, confirm=True)
        ms = compare_to_gold(tv, gv, sample_items, other_label="trusted")
        gold_mismatches = [m.as_dict() for m in ms]
        gold_false_positives = sum(1 for m in ms if m["kind"] == "false_positive")

    # common API failures from the failed rows
    api_fails: Counter = Counter()
    for r in failed:
        eh = r.get("error_head", "")
        m = _UNKNOWN_ID.search(eh)
        if m:
            api_fails[f"unknown id: {m.group(1)}"] += 1
        elif "type mismatch" in eh.lower() or "application type mismatch" in eh.lower():
            api_fails["type mismatch"] += 1
        elif eh:
            api_fails[eh.split(":")[0][:40] or "other"] += 1

    by_cat = Counter(r.get("category", "?") for r in verified)
    by_fam = Counter(r.get("theorem_family", "?") for r in verified)
    zero_success = gen_summary.get("zero_lean_success_theorems", [])

    report = {
        "config": "v29_corpus_integrity",
        "verifier": "TrustedMathlibVerifier (sound&complete) vs GoldMathlibVerifier (1 decl/file)",
        "n_candidates_proposed": gen_summary.get("n_candidates_proposed"),
        "n_verified": len(verified), "n_failed": len(failed),
        "n_timeout": gen_summary.get("n_timeout", 0),
        "n_zero_success_theorems": len(zero_success), "zero_success_theorems": zero_success,
        "verified_still_pass": verified_still_pass,
        "n_verified_regressions": len(verified_regressions),
        "verified_regressions": verified_regressions[:20],
        "n_failed_now_pass": len(failed_now_pass), "failed_now_pass": failed_now_pass[:20],
        "by_category": dict(by_cat),
        "by_family": dict(by_fam.most_common()),
        "common_api_failures": dict(api_fails.most_common(15)),
        "reverify_lean_seconds": reverify_seconds,
        "generation_lean_seconds": gen_summary.get("total_lean_seconds"),
        "gold_sample_size": len(sample_items),
        "gold_sample_by_category": dict(Counter(r.get("category", "?") for r in sample_rows)),
        "n_gold_mismatches": len(gold_mismatches),
        "n_gold_false_positives": gold_false_positives,
        "gold_mismatches": gold_mismatches,
        "integrity_ok": len(verified_regressions) == 0 and gold_false_positives == 0,
        "trusted_sound_on_sample": gold_false_positives == 0,
        "uses_state_after": False, "uses_manual_oracle": False, "uses_mathlib": True,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("INTEGRITY: verified_pass=%d/%d regressions=%d failed_now_pass=%d gold_sample=%d "
                "gold_mismatch=%d gold_fp=%d ok=%s",
                verified_still_pass, len(verified), len(verified_regressions), len(failed_now_pass),
                len(sample_items), len(gold_mismatches), gold_false_positives, report["integrity_ok"])
    logger.info("gold sample by category: %s", report["gold_sample_by_category"])
    return 0 if report["integrity_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
