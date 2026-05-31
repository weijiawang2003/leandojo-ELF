"""Mini-ELF v9 Step 2 — donorless LLM pilot, focused on the v8 hard cases.

This is the v9 variant of `scripts/run_llm_donorless_pilot.py` (the v8 script).
The differences:

  * The target set is **focused on the v8 zeroes**, not a round-robin across
    groups. The pilot deliberately attacks the regimes where the v8 seq2seq
    produced `pass@5 = 0.000`:
      - `family_holdout/forall_inst`
      - `operation_holdout/instantiate_forall`
      - `family_holdout/rewrite_succ`
      - `family_holdout/neg_imp_exfalso`
      - `donorless_eval` strict rows (basic+hard only in train)

  * Prompt mentions explicitly that hand-written templates are out of scope —
    the LLM should *generate* core-Lean tactic blocks, not reach for Mathlib.

If no `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` is configured, the script writes
`docs/V9_LLM_DONORLESS_REPORT.md` as a SKIPPED record (with the exact pilot
parameters that *would* run) and exits successfully. The result is never
faked as `pass@k = 0.00`.

Outputs (only when a key is present)::

    data/baselines/v9_llm_donorless/<target>/metrics.json
    data/baselines/v9_llm_donorless/<target>/predictions.jsonl
    data/baselines/v9_llm_donorless/<target>/verified_candidates.jsonl
    data/baselines/v9_llm_donorless/v9_llm_summary.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import (  # noqa: E402
    VerificationCache, make_lean_cli_verifier,
)
from mini_elf_lean.llm_proposer import LLMProposer  # noqa: E402
from mini_elf_lean.proof_block_cleaner import clean_candidates  # noqa: E402


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("v9_llm_donorless")


# --------------------------------------------------------------------------- #
# Target sets — keyed by the v9 brief
# --------------------------------------------------------------------------- #

V9_TARGETS = [
    # (label, regime_path)
    ("family_holdout_forall_inst",
     ROOT / "data" / "processed" / "proof_blocks_family_holdout" / "forall_inst"),
    ("operation_holdout_instantiate_forall",
     ROOT / "data" / "processed" / "proof_blocks_operation_holdout" / "instantiate_forall"),
    ("family_holdout_rewrite_succ",
     ROOT / "data" / "processed" / "proof_blocks_family_holdout" / "rewrite_succ"),
    ("family_holdout_neg_imp_exfalso",
     ROOT / "data" / "processed" / "proof_blocks_family_holdout" / "neg_imp_exfalso"),
    ("donorless_eval",
     ROOT / "data" / "processed" / "proof_blocks_donorless_eval"),
]


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #

def _iter_jsonl(p: Path):
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            yield json.loads(s)


def _read_test(regime_dir: Path) -> List[Dict[str, Any]]:
    f = regime_dir / "test.jsonl"
    if not f.exists():
        return []
    rows = []
    seen = set()
    for r in _iter_jsonl(f):
        k = (r["theorem_name"], r["state_before"])
        if k in seen:
            continue
        seen.add(k)
        rows.append(r)
    return rows


def _train_tactic_set(regime_dir: Path) -> set:
    out: set = set()
    for r in _iter_jsonl(regime_dir / "train.jsonl"):
        t = (r.get("tactic") or "").strip()
        if t:
            out.add(t)
    return out


def _train_family_set(regime_dir: Path) -> set:
    out: set = set()
    for r in _iter_jsonl(regime_dir / "train.jsonl"):
        f = r.get("family")
        if f:
            out.add(f)
    return out


def _train_operation_set(regime_dir: Path) -> set:
    out: set = set()
    for r in _iter_jsonl(regime_dir / "train.jsonl"):
        out.add(r.get("required_operation") or "unknown")
    return out


# --------------------------------------------------------------------------- #
# Skipped doc
# --------------------------------------------------------------------------- #

SKIPPED_DOC = """# Mini-ELF v9 — LLM donorless pilot — SKIPPED (no API key)

**Why skipped.** Neither `ANTHROPIC_API_KEY` nor `OPENAI_API_KEY` was set in
the v9 environment. The pilot would have called a real LLM endpoint, and the
v8/v9 briefs explicitly forbid faking a result. The pilot is therefore
reported as `skipped` rather than as `pass@k = 0.00` — fabricating a zero
would conflate *not-tested* with *tested-and-failed*, which the project has
been careful to avoid since v5.

## What would have run if a key were present

Targets (the v9 brief's focus list — every regime where the v8 seq2seq scored
`pass@5 = 0.000`):

1. `family_holdout/forall_inst` (7 unique theorems)
2. `operation_holdout/instantiate_forall` (7 unique theorems)
3. `family_holdout/rewrite_succ`
4. `family_holdout/neg_imp_exfalso` (5 unique theorems)
5. `donorless_eval` strict rows (61 unique theorems; train pool excludes every
   planner-blind family)

Per theorem: 10 candidates from `LLMProposer` (the v5/v8 wrapper, source label
`llm_proposer`). Each candidate is cleaned by
`proof_block_cleaner.clean_candidates` and verified by
`make_lean_cli_verifier` against a shared cache.

Metrics: `pass@1`, `pass@5`, `pass@10`, per-group, `novel_verified`,
`donorless_verified`, `cross_family_verified`, `cross_operation_verified`.

## How to run when a key is available

```bash
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY
./.venv/bin/python scripts/run_v9_llm_donorless_pilot.py
```

## Honesty caveats the brief mandates (and the script enforces)

- The pilot is API-billed and intentionally focused (≤80 theorems total).
- The LLM never sees the `shortest_verified_tactic` field from
  `docs/V8_DONORLESS_TARGETS.md` — that field is for human analysis only.
- LLM-emitted multi-line `state_after`-shaped strings are rejected by the
  cleaner before they reach Lean.
- The pilot does not count manual oracle candidates as LLM results.
- The script's empty SKIPPED path is preserved; running it without a key
  re-emits this document rather than progressing silently.
"""


def emit_skipped_doc() -> Path:
    p = ROOT / "docs" / "V9_LLM_DONORLESS_REPORT.md"
    p.write_text(SKIPPED_DOC, encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-root", default=str(ROOT / "data" / "baselines" / "v9_llm_donorless"))
    ap.add_argument("--num-request", type=int, default=10)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-theorems-per-target", type=int, default=20,
                    help="cap per target to keep API spend bounded")
    ap.add_argument("--cache", default=str(ROOT / "data" / "lean_cache" / "v9_llm_cache.json"))
    args = ap.parse_args()

    proposer = LLMProposer(temperature=args.temperature, num_request=args.num_request)
    status = proposer.status()
    if not proposer.available():
        logger.warning("LLM not available: %s", status)
        p = emit_skipped_doc()
        logger.warning("wrote %s — pilot SKIPPED", p)
        return 0

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    cache = VerificationCache.load(Path(args.cache), enabled=True)
    verifier = make_lean_cli_verifier(timeout=60.0)

    summary: Dict[str, Any] = {"llm_status": status, "targets": {}}

    for label, regime_dir in V9_TARGETS:
        rows = _read_test(regime_dir)
        if not rows:
            logger.warning("no test rows for %s — skip", label)
            continue
        rows = rows[: args.max_theorems_per_target]
        train_tactics = _train_tactic_set(regime_dir)
        train_fams = _train_family_set(regime_dir)
        train_ops = _train_operation_set(regime_dir)

        target_dir = out_root / label
        target_dir.mkdir(parents=True, exist_ok=True)
        predictions: List[Dict[str, Any]] = []
        verified_rows: List[Dict[str, Any]] = []
        pass_k = {1: 0, 5: 0, 10: 0}
        n_verified = novel = donorless_v = xfam = xop = 0

        t0 = time.perf_counter()
        for i, row in enumerate(rows):
            cands = proposer.propose(
                row["theorem_statement"], row["state_before"],
                theorem_name=row["theorem_name"],
                pattern_family=row.get("family"),
                max_candidates=args.num_request,
            )
            raw = [c.tactic for c in cands]
            clean, _stats = clean_candidates(raw)
            clean = clean[: args.num_request]

            verifs: List[Dict[str, Any]] = []
            for tac in clean:
                hit = cache.get(row["theorem_name"], tac)
                if hit is not None:
                    verifs.append(hit); continue
                try:
                    v = verifier(row["theorem_name"], row["theorem_statement"], tac)
                except Exception as exc:  # noqa: BLE001
                    v = {"success": False, "error": f"verifier_exception:{exc}"}
                cache.put(row["theorem_name"], tac, v)
                verifs.append(v)

            succ = [bool(v.get("success")) for v in verifs]
            p1, p5, p10 = any(succ[:1]), any(succ[:5]), any(succ[:10])
            pass_k[1] += int(p1); pass_k[5] += int(p5); pass_k[10] += int(p10)

            fam = row.get("family")
            op = row.get("required_operation") or "unknown"
            family_absent = (fam is not None) and (fam not in train_fams)
            op_absent = (op not in train_ops)

            for j, (tac, v) in enumerate(zip(clean, verifs)):
                if v.get("success"):
                    n_verified += 1
                    if tac.strip() not in train_tactics: novel += 1
                    if family_absent: donorless_v += 1; xfam += 1
                    if op_absent: xop += 1
                    verified_rows.append({
                        "theorem_name": row["theorem_name"], "rank": j,
                        "family": fam, "required_operation": op,
                        "tactic": tac,
                    })

            predictions.append({
                "theorem_name": row["theorem_name"],
                "family": fam, "required_operation": op,
                "candidates": clean,
                "verifications": [{"success": bool(v.get("success")), "error": v.get("error")} for v in verifs],
                "pass@1": p1, "pass@5": p5, "pass@10": p10,
            })

            if (i + 1) % 5 == 0:
                cache.save()
                logger.info("  [%s] %d/%d  pass@5=%.3f",
                            label, i + 1, len(rows), pass_k[5] / (i + 1))

        cache.save()
        n = len(rows)
        m = {
            "label": label,
            "n_theorems": n,
            "pass@1": pass_k[1] / n if n else 0.0,
            "pass@5": pass_k[5] / n if n else 0.0,
            "pass@10": pass_k[10] / n if n else 0.0,
            "total_verified_candidates": n_verified,
            "novel_verified": novel,
            "donorless_verified": donorless_v,
            "cross_family_verified": xfam,
            "cross_operation_verified": xop,
            "elapsed_seconds": time.perf_counter() - t0,
        }
        (target_dir / "metrics.json").write_text(
            json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
        with (target_dir / "predictions.jsonl").open("w", encoding="utf-8") as f:
            for p in predictions:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        with (target_dir / "verified_candidates.jsonl").open("w", encoding="utf-8") as f:
            for v in verified_rows:
                f.write(json.dumps(v, ensure_ascii=False) + "\n")
        summary["targets"][label] = m
        logger.info("wrote %s  %s", target_dir, m)

    (out_root / "v9_llm_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
