"""Mini-ELF v27 — Part 1: verifier soundness audit.

Establishes that every verifier path used for v25/v26/v27 Mathlib evaluation is
sound (no false positives vs a one-candidate-per-file gold reference), and that
the corrected iterative success-confirmation method catches the Lean parser/lexer
recovery skip that an old naive batched verifier would miss.

What it does
------------
1. Inventories which verifier each v25/v26/v27 script uses (static scan).
2. Reproduces the parser/lexer recovery skip on a tiny **core** batch and shows
   naive=false-positive, trusted=sound, gold=fail (fast, no Mathlib).
3. Audits a mixed batch of real candidates (valid + Lean-rejected, sampled from
   the v26 verified/failed traces) under both **core** and **import Mathlib**,
   comparing gold vs trusted vs naive and reporting every mismatch.
4. Reproduces the skip under **import Mathlib** too (the headline environment).

Outputs ``data/baselines/v27_verifier_soundness/report.json`` and prints a
summary. Exit code is non-zero iff the trusted verifier shows ANY false positive
(a real soundness regression).

Honesty: real Lean typecheck (core + import Mathlib), no state_after, no manual
oracle as model predictions.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.mathlib_batched_verifier import (  # noqa: E402
    audit_batch, make_skip_repro_batch,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("audit_v27_verifier_soundness")
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"

Item = Tuple[str, str, str]


def _read(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def inventory_verifier_paths() -> Dict[str, Any]:
    """Static scan of scripts/ for which verifier each evaluation path uses."""
    scripts = sorted((ROOT / "scripts").glob("*.py"))
    rows = []
    pat_batch = re.compile(r"BatchMathlibVerifier|mathlib_verifier")
    pat_trusted = re.compile(r"TrustedMathlibVerifier|mathlib_batched_verifier")
    pat_v25 = re.compile(r"make_mathlib_verifier|lake env lean")
    for p in scripts:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if not (pat_batch.search(txt) or pat_trusted.search(txt) or pat_v25.search(txt)):
            continue
        if pat_trusted.search(txt):
            kind = "trusted (corrected, confirm forced)"
        elif "verify_many" in txt and pat_batch.search(txt):
            kind = "batched corrected (confirm=True default)"
        elif pat_v25.search(txt):
            kind = "v25 one-candidate-per-file (lake env lean) — isolated, sound but slow"
        else:
            kind = "imports verifier module"
        rows.append({"script": p.name, "verifier": kind})
    return {"n_scripts": len(rows), "paths": rows}


def sample_real_items(n_ok: int, n_bad: int) -> List[Item]:
    """Mixed batch from v26 traces: verified (should pass) + Lean-rejected
    (should fail), to check gold/trusted/naive agree on real candidates."""
    ver = _read(ROOT / "data" / "traces" / "v26_mathlib_specialist_verified.jsonl")
    bad = _read(ROOT / "data" / "traces" / "v26_mathlib_specialist_failed.jsonl")
    items: List[Item] = []
    seen = set()
    for r in ver:
        key = (r["theorem_name"], r["tactic"])
        if key in seen:
            continue
        seen.add(key)
        items.append((r["theorem_name"], r["theorem_statement"], r["tactic"]))
        if sum(1 for _ in items) >= n_ok:
            break
    nb = 0
    for r in bad:
        key = (r["theorem_name"], r["tactic"])
        if key in seen:
            continue
        seen.add(key)
        items.append((r["theorem_name"], r["theorem_statement"], r["tactic"]))
        nb += 1
        if nb >= n_bad:
            break
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v27_verifier_soundness" / "report.json"))
    ap.add_argument("--n-ok", type=int, default=14)
    ap.add_argument("--n-bad", type=int, default=6)
    ap.add_argument("--skip-mathlib", action="store_true", help="core-only (fast)")
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = None
    lpf = Path(args.lean_path_file)
    if lpf.exists():
        lean_path = lpf.read_text().strip()

    report: Dict[str, Any] = {"config": "v27_verifier_soundness"}
    report["verifier_inventory"] = inventory_verifier_paths()

    # 1. core skip reproduction (fast)
    logger.info("[1/4] core skip reproduction ...")
    repro = make_skip_repro_batch()
    report["core_skip_repro"] = audit_batch(repro, scratch, core=True, timeout=60)

    # 2. core mixed real batch (fast; core verifier of broad-core-style candidates)
    #    use the repro plus a few trivially-core candidates
    logger.info("[2/4] core mixed batch ...")
    core_mixed: List[Item] = [
        ("v27_core_ok_rfl", "(n : Nat) : n + 0 = n", "rfl"),
        ("v27_core_ok_intro", "(p : Prop) (h : p) : p", "exact h"),
        ("v27_core_bad_rfl", "(n : Nat) : n + 1 = n", "rfl"),
        ("v27_core_bad_tac", "(p : Prop) : p", "exact trivial"),
        ("v27_core_parse_err", "(p : Prop) (h : p) : p", "exact h /- open"),
        ("v27_core_ok_after_err", "(p q : Prop) (h : p) : p", "exact h"),
    ]
    report["core_mixed"] = audit_batch(core_mixed, scratch, core=True, timeout=60)

    if not args.skip_mathlib:
        # 3. real Mathlib mixed batch (the v25/v26/v27 headline environment)
        logger.info("[3/4] Mathlib mixed real batch (gold one-per-file is slow) ...")
        items = sample_real_items(args.n_ok, args.n_bad)
        report["mathlib_mixed"] = {
            "n_items": len(items),
            **audit_batch(items, scratch, lean_path=lean_path, core=False, timeout=300),
        }
        # 4. Mathlib skip reproduction
        logger.info("[4/4] Mathlib skip reproduction ...")
        report["mathlib_skip_repro"] = audit_batch(repro, scratch, lean_path=lean_path,
                                                   core=False, timeout=300)
    else:
        report["mathlib_mixed"] = "skipped"
        report["mathlib_skip_repro"] = "skipped"

    # soundness verdict: trusted must have zero false positives everywhere
    sections = [k for k in ("core_skip_repro", "core_mixed", "mathlib_mixed", "mathlib_skip_repro")
                if isinstance(report.get(k), dict)]
    trusted_fps = sum(report[k].get("trusted_false_positives", 0) for k in sections)
    naive_fps = sum(report[k].get("naive_false_positives", 0) for k in sections)
    report["summary"] = {
        "sections": sections,
        "trusted_false_positives_total": trusted_fps,
        "naive_false_positives_total": naive_fps,
        "trusted_sound": trusted_fps == 0,
        "naive_demonstrated_unsound": naive_fps > 0,
        "uses_state_after": False, "uses_manual_oracle": False,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("VERIFIER SOUNDNESS: trusted_false_positives=%d (sound=%s) | "
                "naive_false_positives=%d (unsound demonstrated=%s)",
                trusted_fps, trusted_fps == 0, naive_fps, naive_fps > 0)
    for k in sections:
        s = report[k]
        logger.info("  %-20s gold_ok=%s trusted_ok=%s naive_ok=%s trusted_FP=%d naive_FP=%d",
                    k, s.get("gold_verified"), s.get("trusted_verified"),
                    s.get("naive_verified"), s.get("trusted_false_positives", 0),
                    s.get("naive_false_positives", 0))
    logger.info("report -> %s", out)
    return 0 if trusted_fps == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
