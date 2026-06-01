"""Mini-ELF v30 — Part 4: re-verify the v30 targeted corpus + gold sampling.

Independent integrity gate over `data/traces/v30_targeted_density_{verified,failed}.jsonl`:
re-verify every "verified" row (trusted), re-check failures stay rejected, and gold
spot-check (>=20, every targeted family) with `GoldMathlibVerifier` (1 decl/file).
Requires 0 gold false positives. Reports per-family added density, runtime, common API
failures. Trusted verifier only; no state_after; manual targets never predictions.
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
logger = logging.getLogger("verify_v30_targeted_density_corpus")
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"
_UNKNOWN_ID = re.compile(r"unknown (?:identifier|constant) '([^']+)'")


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def stratified_sample(verified, n, seed):
    """>=n verified rows, at least one per *family* (the targeted unit)."""
    rng = random.Random(seed)
    by_fam: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in verified:
        by_fam[f"{r.get('category')}::{r.get('theorem_family')}"].append(r)
    picked = [rng.choice(rows) for _f, rows in sorted(by_fam.items())]
    pool = [r for r in verified if r not in picked]
    rng.shuffle(pool)
    while len(picked) < n and pool:
        picked.append(pool.pop())
    return picked


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--verified", default=str(ROOT / "data" / "traces" / "v30_targeted_density_verified.jsonl"))
    ap.add_argument("--failed", default=str(ROOT / "data" / "traces" / "v30_targeted_density_failed.jsonl"))
    ap.add_argument("--summary", default=str(ROOT / "data" / "processed" / "v30_mathlib_specialist" / "targeted_summary.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v30_corpus_integrity" / "report.json"))
    ap.add_argument("--gold-sample", type=int, default=24)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    verified = _read(Path(args.verified))
    failed = _read(Path(args.failed))
    gen = json.loads(Path(args.summary).read_text()) if Path(args.summary).exists() else {}
    logger.info("re-verifying %d verified + %d failed rows", len(verified), len(failed))

    trusted = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=300)
    trusted.warmup()
    vv = trusted.verify_many([(r["theorem_name"], r["theorem_statement"], r["tactic"]) for r in verified], confirm=True)
    fv = trusted.verify_many([(r["theorem_name"], r["theorem_statement"], r["tactic"]) for r in failed], confirm=True) if failed else []
    reverify_s = round(trusted.total_lean_seconds, 1)
    verified_still_pass = sum(1 for x in vv if x.success)
    regressions = [(x.theorem_name, x.tactic, x.error) for x in vv if not x.success]
    failed_now_pass = [(x.theorem_name, x.tactic) for x in fv if x.success]

    sample_rows = stratified_sample(verified, args.gold_sample, args.seed) if verified else []
    sample_items = [(r["theorem_name"], r["theorem_statement"], r["tactic"]) for r in sample_rows]
    gold_mismatches: List[Dict[str, Any]] = []
    gold_fp = 0
    if sample_items:
        gold = GoldMathlibVerifier(scratch, lean_path=lean_path, timeout=300)
        gv = gold.verify_many(sample_items)
        tv = trusted.verify_many(sample_items, confirm=True)
        ms = compare_to_gold(tv, gv, sample_items, other_label="trusted")
        gold_mismatches = [m.as_dict() for m in ms]
        gold_fp = sum(1 for m in ms if m["kind"] == "false_positive")

    api_fails: Counter = Counter()
    for r in failed:
        eh = r.get("error_head", "")
        m = _UNKNOWN_ID.search(eh)
        if m:
            api_fails[f"unknown id: {m.group(1)}"] += 1
        elif eh:
            api_fails[eh.split(":")[0][:40] or "other"] += 1

    report = {
        "config": "v30_corpus_integrity",
        "verifier": "TrustedMathlibVerifier (sound&complete) vs GoldMathlibVerifier (1 decl/file)",
        "n_candidates_proposed": gen.get("n_candidates_proposed"),
        "n_verified": len(verified), "n_failed": len(failed), "n_timeout": gen.get("n_timeout", 0),
        "n_zero_success_theorems": gen.get("n_zero_lean_success_theorems", 0),
        "verified_still_pass": verified_still_pass, "n_verified_regressions": len(regressions),
        "verified_regressions": regressions[:20], "n_failed_now_pass": len(failed_now_pass),
        "by_family_theorems_added": gen.get("family_theorems_added", {}),
        "previous_density": gen.get("previous_density", {}),
        "common_api_failures": dict(api_fails.most_common(15)),
        "reverify_lean_seconds": reverify_s, "generation_lean_seconds": gen.get("total_lean_seconds"),
        "gold_sample_size": len(sample_items),
        "gold_sample_by_family": dict(Counter(f"{r.get('category')}::{r.get('theorem_family')}" for r in sample_rows)),
        "n_gold_mismatches": len(gold_mismatches), "n_gold_false_positives": gold_fp,
        "gold_mismatches": gold_mismatches,
        "integrity_ok": len(regressions) == 0 and gold_fp == 0,
        "trusted_sound_on_sample": gold_fp == 0,
        "uses_state_after": False, "uses_manual_oracle": False, "uses_mathlib": True,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("INTEGRITY: verified_pass=%d/%d regressions=%d failed_now_pass=%d gold=%d mismatch=%d fp=%d ok=%s",
                verified_still_pass, len(verified), len(regressions), len(failed_now_pass),
                len(sample_items), len(gold_mismatches), gold_fp, report["integrity_ok"])
    return 0 if report["integrity_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
