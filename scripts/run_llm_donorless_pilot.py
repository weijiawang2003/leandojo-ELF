"""Mini-ELF v8 Part 5 — LLM donorless pilot.

Picks 20–40 donorless rows from the v8 donorless target set (family_holdout +
operation_holdout test theorems), asks the LLM proposer for 10 core-Lean tactic
candidates each, and verifies them with lean-cli. If no API key is configured,
skips cleanly and writes ``docs/V8_LLM_DONORLESS_PILOT_SKIPPED.md`` instead of
faking a result.

Outputs (only when a key is present)::

    data/baselines/v8_llm_donorless/metrics.json
    data/baselines/v8_llm_donorless/predictions.jsonl
    data/baselines/v8_llm_donorless/verified_candidates.jsonl
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
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import (  # noqa: E402
    VerificationCache, make_lean_cli_verifier,
)
from mini_elf_lean.llm_proposer import LLMProposer  # noqa: E402
from mini_elf_lean.proof_block_cleaner import clean_candidates  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("v8_llm_donorless")


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    out = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            out.append(json.loads(s))
    return out


def _select_pilot_rows(family_targets, op_targets, *, n_per_set: int = 20) -> List[Dict[str, Any]]:
    """Pick ``n_per_set`` distinct theorems from each donorless set,
    grouped to cover diverse families. Deterministic by theorem-name sort."""
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    # family_holdout first — these are the true donorless rows
    by_group = defaultdict(list)
    for t in family_targets:
        by_group[t["group"]].append(t)
    # round-robin across groups
    groups = sorted(by_group.keys())
    while len(out) < n_per_set and any(by_group[g] for g in groups):
        for g in groups:
            if not by_group[g]:
                continue
            t = by_group[g].pop(0)
            if t["theorem_name"] in seen:
                continue
            seen.add(t["theorem_name"])
            out.append({**t, "pilot_set": "family_holdout"})
            if len(out) >= n_per_set:
                break
    return out


def emit_skipped_doc() -> Path:
    p = ROOT / "docs" / "V8_LLM_DONORLESS_PILOT_SKIPPED.md"
    p.write_text(
        "# Mini-ELF v8 — LLM donorless pilot — SKIPPED (no API key)\n\n"
        "**Why skipped.** Neither `ANTHROPIC_API_KEY` nor `OPENAI_API_KEY` was "
        "set in the v8 evaluation environment. The pilot would have called a "
        "real LLM endpoint, and the v8 brief explicitly forbids faking a "
        "result. The pilot is therefore reported as `skipped` rather than as "
        "a zero — fabricating `pass@k=0.00` would conflate "
        "*not-tested* with *tested-and-failed*, which the project has been "
        "careful to avoid since v5.\n\n"
        "**What would have run if a key were present.**\n\n"
        "- `scripts/run_llm_donorless_pilot.py` picks a pilot set of 20 donorless "
        "  theorems sampled across all v8 donorless groups "
        "  (negation/contradiction, contrapositive, exists_elim, forall_inst, "
        "  rewrite, exists_reconstruct), one per group when possible.\n"
        "- It asks `LLMProposer` (the same v5 wrapper, source label "
        "  `llm_proposer`) for 10 core-Lean candidates per theorem, system "
        "  prompt requiring JSON list, no Mathlib, no prose.\n"
        "- Each candidate is cleaned by `proof_block_cleaner.clean_candidates` "
        "  and verified by `make_lean_cli_verifier` with a shared cache.\n"
        "- Metrics: `pass@1`, `pass@5`, `pass@10`, per-group, `novel_verified`, "
        "  `donorless_verified`, `cross_family_verified`, "
        "  `cross_operation_verified`.\n\n"
        "**How to run when a key is available.**\n\n"
        "```bash\n"
        "export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY\n"
        "./.venv/bin/python scripts/run_llm_donorless_pilot.py --n-per-set 20\n"
        "```\n\n"
        "**Honesty caveats** the brief mandates and the pilot script enforces:\n\n"
        "- The pilot is API-billed and intentionally tiny (20 theorems); "
        "  the result is a pilot signal, not a production number.\n"
        "- LLM-emitted multi-line `state_after`-shaped strings are rejected by "
        "  the cleaner before they reach Lean (no state_after, even by accident).\n"
        "- The pilot never reads the `shortest_verified_tactic` field from "
        "  `docs/V8_DONORLESS_TARGETS.md`. That tactic is documented for "
        "  human analysis of the proof shape; it is **not** in the LLM prompt.\n"
        "- The pilot does not count manual oracle candidates as LLM results.\n",
        encoding="utf-8")
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--targets-dir", default=str(ROOT / "data" / "baselines" / "v8_donorless"))
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "baselines" / "v8_llm_donorless"))
    ap.add_argument("--n-per-set", type=int, default=20)
    ap.add_argument("--num-request", type=int, default=10)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--cache", default=str(ROOT / "data" / "lean_cache" / "v8_llm_cache.json"))
    args = ap.parse_args()

    # Gate on key availability
    proposer = LLMProposer(temperature=args.temperature, num_request=args.num_request)
    status = proposer.status()
    if not proposer.available():
        logger.warning("LLM not available: %s", status)
        p = emit_skipped_doc()
        logger.warning("wrote %s — pilot SKIPPED", p)
        # success-exit so callers can chain; the SKIPPED doc is the result
        return 0

    targets_dir = Path(args.targets_dir)
    fam = _read_jsonl(targets_dir / "family_holdout_targets.jsonl")
    op  = _read_jsonl(targets_dir / "operation_holdout_targets.jsonl")
    pilot = _select_pilot_rows(fam, op, n_per_set=args.n_per_set)
    logger.info("LLM available: %s; running pilot on %d donorless theorems",
                status, len(pilot))

    cache = VerificationCache.load(Path(args.cache), enabled=True)
    verifier = make_lean_cli_verifier(timeout=60.0)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_pass = {1: 0, 5: 0, 10: 0}
    n_verified = 0
    novel_verified = 0
    cross_family_verified = 0
    cross_op_verified = 0
    predictions: List[Dict[str, Any]] = []
    verified_rows: List[Dict[str, Any]] = []

    # train-pool tactic set for novelty (use the donorless_eval train rows)
    train_rows = _read_jsonl(ROOT / "data" / "processed"
                             / "proof_blocks_donorless_eval" / "train.jsonl")
    train_tactic_set = {r["tactic"].strip() for r in train_rows if r.get("tactic")}
    train_fam_set = {r.get("family") for r in train_rows if r.get("family")}
    train_op_set = {r.get("required_operation") or "unknown" for r in train_rows}

    for i, t in enumerate(pilot):
        cands = proposer.propose(t["theorem_statement"], t["state_before"],
                                  theorem_name=t["theorem_name"],
                                  pattern_family=t["family"],
                                  max_candidates=args.num_request)
        raw = [c.tactic for c in cands]
        clean, _stats = clean_candidates(raw)
        clean = clean[: args.num_request]

        verifications: List[Dict[str, Any]] = []
        for tac in clean:
            hit = cache.get(t["theorem_name"], tac)
            if hit is not None:
                verifications.append(hit); continue
            try:
                res = verifier(t["theorem_name"], t["theorem_statement"], tac)
            except Exception as exc:  # noqa: BLE001
                res = {"success": False, "error": f"verifier_exception:{exc}"}
            cache.put(t["theorem_name"], tac, res)
            verifications.append(res)

        succ = [bool(v.get("success")) for v in verifications]
        p1 = any(succ[:1]); p5 = any(succ[:5]); p10 = any(succ[:10])
        metrics_pass[1] += int(p1); metrics_pass[5] += int(p5); metrics_pass[10] += int(p10)

        for j, (tac, v) in enumerate(zip(clean, verifications)):
            if v.get("success"):
                n_verified += 1
                if tac.strip() not in train_tactic_set: novel_verified += 1
                if t["family"] not in train_fam_set: cross_family_verified += 1
                if t["required_operation"] not in train_op_set: cross_op_verified += 1
                verified_rows.append({
                    "theorem_name": t["theorem_name"], "rank": j,
                    "family": t["family"], "required_operation": t["required_operation"],
                    "tactic": tac, "group": t["group"],
                })

        predictions.append({
            "theorem_name": t["theorem_name"],
            "family": t["family"], "group": t["group"],
            "required_operation": t["required_operation"],
            "candidates": clean,
            "pass@1": p1, "pass@5": p5, "pass@10": p10,
        })
        if (i + 1) % 5 == 0:
            cache.save()
            logger.info("  %d/%d", i + 1, len(pilot))

    cache.save()
    n = len(pilot)
    metrics = {
        "llm_status": status,
        "n_pilot": n,
        "pass@1": metrics_pass[1] / n if n else 0.0,
        "pass@5": metrics_pass[5] / n if n else 0.0,
        "pass@10": metrics_pass[10] / n if n else 0.0,
        "total_verified_candidates": n_verified,
        "novel_verified": novel_verified,
        "cross_family_verified": cross_family_verified,
        "cross_operation_verified": cross_op_verified,
    }
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    with (out_dir / "predictions.jsonl").open("w", encoding="utf-8") as f:
        for p in predictions:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with (out_dir / "verified_candidates.jsonl").open("w", encoding="utf-8") as f:
        for v in verified_rows:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
    logger.info("wrote %s   %s", out_dir, metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
