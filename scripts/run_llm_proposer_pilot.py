"""V5 Part 3 — LLM proof-block proposer pilot on planner-blind targets.

Runs **only** if an API key is configured (``ANTHROPIC_API_KEY`` /
``OPENAI_API_KEY``). With no key it **skips honestly** — writes
``docs/V5_LLM_PILOT_SKIPPED.md`` and produces no faked metrics.

With a key it targets a small set of planner-blind theorems (default: the
template-less `forall_inst` / `rewrite_succ` first, then the rest), asks the LLM
for JSON tactic blocks, verifies every candidate with lean-cli, and saves:

  * data/proposals/planner_blind_llm_candidates.jsonl
  * data/traces/planner_blind_llm_{verified,failed}.jsonl
  * data/baselines/planner_blind_llm_pilot/metrics.json
  * docs/V5_LLM_PILOT_REPORT.md

Few-shot examples are drawn from the train split, **never** from the test
theorem itself. Theorem-level verification only; no ``state_after`` is read.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_elf_lean.baselines import load_dataset_split  # noqa: E402
from mini_elf_lean.baseline_eval import VerificationCache, make_lean_cli_verifier, _verify_tactic  # noqa: E402
from mini_elf_lean.llm_proposer import LLMProposer  # noqa: E402
from mini_elf_lean.splits import load_theorem_metadata  # noqa: E402

PRIORITY_FAMILIES = ("forall_inst", "rewrite_succ")


def _write_skipped(status: Dict[str, Any]) -> None:
    doc = ROOT / "docs" / "V5_LLM_PILOT_SKIPPED.md"
    doc.write_text(
        "# Mini-ELF v5 — LLM proposer pilot (SKIPPED)\n\n"
        "The LLM proof-block proposer pilot was **not run**: no API key is "
        "configured in this environment.\n\n"
        f"- `available`: {status.get('available')}\n"
        f"- `backend`: {status.get('backend')}\n"
        f"- reason: {status.get('reason')}\n\n"
        "No output was faked. The proposer (`src/mini_elf_lean/llm_proposer.py`) "
        "and this runner (`scripts/run_llm_proposer_pilot.py`) are implemented and "
        "unit-tested for the skip path; set `ANTHROPIC_API_KEY` (or "
        "`OPENAI_API_KEY`) and re-run:\n\n"
        "```\n"
        "wsl -d Ubuntu -- bash -lc 'cd ~/code/ELFMath && \\\n"
        "  ANTHROPIC_API_KEY=... MINI_ELF_LEAN_COMMAND=<lean> \\\n"
        "  ./.venv/bin/python scripts/run_llm_proposer_pilot.py \\\n"
        "    --dataset data/processed/planner_blind_split_lean_cli/next_tactic.jsonl \\\n"
        "    --seeds data/seeds/planner_blind_seeds.jsonl --verify-with-lean-cli'\n"
        "```\n\n"
        "Expected result if run: the LLM is the only source that could solve the "
        "template-less families with **no** same-shape donor; the pilot would "
        "measure candidates/theorem, unique/verified, pass@1/5, per-family pass@5, "
        "`novel_verified`, and an error taxonomy. See `docs/V5_TARGET_FAMILIES.md`.\n",
        encoding="utf-8",
    )
    print(f"LLM pilot skipped (no key). Wrote {doc}")


def _fewshot(train, theorem_name: str, family: Optional[str], k: int = 4) -> List[Tuple[str, str]]:
    """Up to k (state_before, tactic) examples from OTHER theorems, same family
    first. Never includes the test theorem itself."""
    same, other = [], []
    for e in train:
        if e.theorem_name == theorem_name:
            continue
        (same if family and family in e.theorem_name else other).append((e.state_before, e.tactic))
    picked = (same + other)[:k]
    return picked


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--seeds", type=Path, default=None)
    ap.add_argument("--output-dir", type=Path, default=ROOT / "data" / "baselines" / "planner_blind_llm_pilot")
    ap.add_argument("--proposals-dir", type=Path, default=ROOT / "data" / "proposals")
    ap.add_argument("--traces-dir", type=Path, default=ROOT / "data" / "traces")
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int, default=16)
    ap.add_argument("--num-request", type=int, default=8)
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--llm-model", default=None)
    ap.add_argument("--verify-with-lean-cli", dest="verify", action="store_true")
    ap.add_argument("--lean-timeout", type=float, default=30.0)
    args = ap.parse_args(argv)

    proposer = LLMProposer(backend=args.backend, model=args.llm_model, num_request=args.num_request)
    status = proposer.status()
    if not proposer.available():
        _write_skipped(status)
        return 0

    train, eval_examples = load_dataset_split(args.dataset, args.split)
    meta = load_theorem_metadata(args.seeds) if args.seeds else {}

    def fam_of(name: str) -> Optional[str]:
        return (meta.get(name) or {}).get("pattern_family")

    # Prioritise the template-less targets, then the rest; one row per theorem.
    seen_thm: set = set()
    ordered: List[Any] = []
    for want_priority in (True, False):
        for e in eval_examples:
            if e.theorem_name in seen_thm:
                continue
            is_pri = fam_of(e.theorem_name) in PRIORITY_FAMILIES
            if is_pri == want_priority:
                ordered.append(e)
                seen_thm.add(e.theorem_name)
    targets = ordered[: args.limit]

    cache = VerificationCache.load(args.output_dir / "verification_cache.json", enabled=True)
    verifier = make_lean_cli_verifier(timeout=args.lean_timeout) if args.verify else None

    args.proposals_dir.mkdir(parents=True, exist_ok=True)
    args.traces_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    prop_rows: List[Dict[str, Any]] = []
    verified_rows: List[Dict[str, Any]] = []
    failed_rows: List[Dict[str, Any]] = []
    by_family: Dict[str, Dict[str, int]] = defaultdict(lambda: {"n": 0, "passed": 0})
    error_tax: Dict[str, int] = defaultdict(int)
    total_cands = unique_cands = verified_cands = 0
    pass1 = pass5 = novel_verified = 0
    train_tactics = {e.tactic for e in train}

    for e in targets:
        fam = fam_of(e.theorem_name)
        proposer.examples = _fewshot(train, e.theorem_name, fam)
        cands = proposer.propose(e.theorem_statement, e.state_before,
                                 theorem_name=e.theorem_name, pattern_family=fam,
                                 max_candidates=args.num_request)
        tacs = [c.tactic for c in cands]
        prop_rows.append({"theorem_name": e.theorem_name, "theorem_statement": e.theorem_statement,
                          "state_before": e.state_before, "candidates": tacs,
                          "pattern_family": fam, "source": "llm_proposer"})
        total_cands += len(tacs)
        unique_cands += len(set(tacs))
        by_family[fam or "?"]["n"] += 1
        any_ok = False
        for rank, tac in enumerate(tacs):
            if verifier is None:
                continue
            res = _verify_tactic(theorem_name=e.theorem_name, theorem_statement=e.theorem_statement,
                                 tactic=tac, verifier=verifier, cache=cache)
            rec = {"theorem_name": e.theorem_name, "theorem_statement": e.theorem_statement,
                   "state_before": e.state_before, "tactic": tac, "source": "planner-blind-llm-pilot",
                   "backend": proposer.backend, "model": proposer.model, "success": bool(res.get("success"))}
            if res.get("success"):
                verified_cands += 1
                verified_rows.append(rec)
                if tac not in train_tactics:
                    novel_verified += 1
                if rank == 0:
                    pass1 += 1
                if rank < 5:
                    any_ok = True
            else:
                rec["error"] = res.get("error")
                failed_rows.append(rec)
                err = (res.get("error") or "").split("error:")[-1].strip()[:48] or "unknown"
                error_tax[err] += 1
        if any_ok:
            pass5 += 1
            by_family[fam or "?"]["passed"] += 1

    cache.save()
    n = len(targets)
    metrics = {
        "baseline": "llm_proposer_pilot", "backend": proposer.backend, "model": proposer.model,
        "n_theorems": n, "candidates_per_theorem": (total_cands / n) if n else 0.0,
        "unique_candidates": unique_cands, "verified_candidates": verified_cands,
        "pass_at_1": (pass1 / n) if n else 0.0, "pass_at_5": (pass5 / n) if n else 0.0,
        "novel_verified": novel_verified,
        "per_family_pass_at_5": {f: {"n": d["n"], "rate": (d["passed"] / d["n"]) if d["n"] else 0.0}
                                 for f, d in sorted(by_family.items())},
        "error_taxonomy": dict(sorted(error_tax.items(), key=lambda kv: -kv[1])),
    }
    (args.proposals_dir / "planner_blind_llm_candidates.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in prop_rows), encoding="utf-8")
    (args.traces_dir / "planner_blind_llm_verified.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in verified_rows), encoding="utf-8")
    (args.traces_dir / "planner_blind_llm_failed.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in failed_rows), encoding="utf-8")
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2, sort_keys=True))
    print(f"\nwrote proposals + traces + metrics under {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
