"""Mini-ELF v8 Part 3 — evaluate a trained proof-block seq2seq on a regime.

For every ``test`` row in the chosen regime directory, ask the model for top-k
beam candidates, verify each one with lean-cli (cache-backed), and report:

  * pass@1 / pass@5 / pass@10  (lean-cli verified)
  * per-family / per-operation pass@5
  * novel_verified         — verified candidates whose tactic string never
                             appeared as the gold tactic for ANY theorem in the
                             v8 train pool
  * donorless_verified     — verified candidates for rows whose family has no
                             same-family donor in train (only meaningful for
                             family_holdout and donorless_eval)
  * cross_family_verified  — verified candidates whose gold theorem family is
                             absent from train but model still succeeded
  * cross_operation_verified — same for required_operation

The model is loaded via :class:`ProofBlockSeq2SeqProposer` so the same wrapper
the v8 fusion uses is exercised end-to-end.

Outputs::

    <out-dir>/metrics.json
    <out-dir>/predictions.jsonl          (one row per eval theorem)
    <out-dir>/verified_candidates.jsonl  (one row per Lean-verified prediction)
    <out-dir>/cache.json                 (verification cache, shared)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import (  # noqa: E402
    VerificationCache, make_lean_cli_verifier,
)
from mini_elf_lean.proof_block_seq2seq import (  # noqa: E402
    ProofBlockSeq2SeqProposer, load_proof_block_regime,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_proof_block_seq2seq")


# --------------------------------------------------------------------------- #
# Per-row eval
# --------------------------------------------------------------------------- #

def _gold_tactic_strings(rows: Sequence[Any]) -> Set[str]:
    out: Set[str] = set()
    for r in rows:
        t = getattr(r, "tactic", None) or (r.get("tactic") if isinstance(r, dict) else None)
        if t:
            out.add(t.strip())
    return out


def _row_family(row: Dict[str, Any]) -> Optional[str]:
    return row.get("family")


def _row_operation(row: Dict[str, Any]) -> str:
    return row.get("required_operation") or "unknown"


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    out = []
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            out.append(json.loads(s))
    return out


def _dedup_test_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per theorem (the dataset stores up to multiple verified tactics
    per theorem; for prediction we only need each (theorem, state_before) once)."""
    seen: Set[Tuple[str, str]] = set()
    out: List[Dict[str, Any]] = []
    for r in rows:
        k = (r["theorem_name"], r["state_before"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--regime-dir", required=True,
                    help="proof_blocks_* directory with test.jsonl")
    ap.add_argument("--model-dir", required=True,
                    help="trained model dir containing model.pt + vocab.json + config.json")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--beam-width", type=int, default=10)
    ap.add_argument("--length-penalty", type=float, default=0.7)
    ap.add_argument("--max-output-len", type=int, default=80)
    ap.add_argument("--cache", default=str(ROOT / "data" / "lean_cache" / "v8_seq2seq_cache.json"))
    ap.add_argument("--verifier-timeout", type=float, default=60.0,
                    help="per-candidate lean-cli timeout (s)")
    ap.add_argument("--no-verify", dest="verify", action="store_false")
    ap.set_defaults(verify=True)
    ap.add_argument("--lean-bin",
                    default=os.environ.get("LEAN_BIN",
                        os.path.expanduser("~/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean")))
    args = ap.parse_args()

    regime_dir = Path(args.regime_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Train pool: the train.jsonl of THIS regime — used to compute novelty
    # (a verified candidate is "novel" if its tactic string never appears in
    # the train pool's gold tactics).
    train_rows = _read_jsonl(regime_dir / "train.jsonl")
    test_rows = _read_jsonl(regime_dir / "test.jsonl")
    if not test_rows:
        # interpolation has val too; fall back to that
        test_rows = _read_jsonl(regime_dir / "val.jsonl")
        logger.warning("no test.jsonl; using val.jsonl (%d rows)", len(test_rows))
    if not test_rows:
        logger.error("no test rows in %s", regime_dir)
        return 1

    train_tactic_set = {r["tactic"].strip() for r in train_rows if r.get("tactic")}
    train_family_set = {r.get("family") for r in train_rows if r.get("family")}
    train_op_set = {r.get("required_operation") or "unknown" for r in train_rows}

    test_unique = _dedup_test_rows(test_rows)
    logger.info("eval rows: %d unique theorems (%d total rows in test.jsonl)",
                len(test_unique), len(test_rows))

    proposer = ProofBlockSeq2SeqProposer(
        Path(args.model_dir),
        beam_width=args.beam_width,
        length_penalty=args.length_penalty,
        max_output_len=args.max_output_len,
    )
    if not proposer.available():
        logger.error("seq2seq model not loadable at %s", args.model_dir)
        return 1

    cache = VerificationCache.load(Path(args.cache), enabled=True) \
        if args.verify else VerificationCache(enabled=False)
    verifier = make_lean_cli_verifier(timeout=args.verifier_timeout) \
        if args.verify else None

    predictions: List[Dict[str, Any]] = []
    verified_rows: List[Dict[str, Any]] = []
    pass_k = {1: 0, 5: 0, 10: 0}
    by_fam = defaultdict(lambda: {"n": 0, "pass5": 0, "pass10": 0})
    by_op = defaultdict(lambda: {"n": 0, "pass5": 0, "pass10": 0})
    novel_verified = 0
    donorless_verified = 0
    cross_family_verified = 0
    cross_operation_verified = 0
    total_verified_cands = 0

    t0 = time.perf_counter()
    for i, row in enumerate(test_unique):
        cands = proposer.propose(
            row["theorem_statement"], row["state_before"], top_k=args.top_k,
            theorem_name=row["theorem_name"],
        )
        cand_tacs = [c.tactic for c in cands]
        verifications: List[Dict[str, Any]] = []
        for tac in cand_tacs:
            hit = cache.get(row["theorem_name"], tac) if args.verify else None
            if hit is not None:
                verifications.append(hit)
                continue
            if verifier is None:
                verifications.append({"success": False, "error": "no_verifier", "elapsed_ms": 0.0})
                continue
            try:
                res = verifier(row["theorem_name"], row["theorem_statement"], tac)
            except Exception as exc:  # noqa: BLE001
                res = {"success": False, "error": f"verifier_exception:{exc}", "elapsed_ms": 0.0}
            cache.put(row["theorem_name"], tac, res)
            verifications.append(res)

        # pass@k
        succ_flags = [bool(v.get("success")) for v in verifications]
        passed1 = any(succ_flags[:1])
        passed5 = any(succ_flags[:5])
        passed10 = any(succ_flags[:10])
        pass_k[1] += int(passed1)
        pass_k[5] += int(passed5)
        pass_k[10] += int(passed10)

        fam = _row_family(row)
        op = _row_operation(row)
        if fam:
            by_fam[fam]["n"] += 1
            by_fam[fam]["pass5"] += int(passed5)
            by_fam[fam]["pass10"] += int(passed10)
        by_op[op]["n"] += 1
        by_op[op]["pass5"] += int(passed5)
        by_op[op]["pass10"] += int(passed10)

        family_absent = (fam is not None) and (fam not in train_family_set)
        op_absent = (op not in train_op_set)

        # Aggregate per-candidate stats
        for j, (tac, v) in enumerate(zip(cand_tacs, verifications)):
            if v.get("success"):
                total_verified_cands += 1
                novel = tac.strip() not in train_tactic_set
                if novel:
                    novel_verified += 1
                if family_absent:
                    donorless_verified += 1
                    cross_family_verified += 1
                if op_absent:
                    cross_operation_verified += 1
                verified_rows.append({
                    "theorem_name": row["theorem_name"],
                    "family": fam,
                    "required_operation": op,
                    "rank": j,
                    "tactic": tac,
                    "family_absent_from_train": family_absent,
                    "operation_absent_from_train": op_absent,
                    "novel": novel,
                })

        predictions.append({
            "theorem_name": row["theorem_name"],
            "family": fam,
            "required_operation": op,
            "family_absent_from_train": family_absent,
            "operation_absent_from_train": op_absent,
            "candidates": cand_tacs,
            "verifications": [
                {"success": bool(v.get("success")), "error": v.get("error")}
                for v in verifications
            ],
            "pass@1": passed1,
            "pass@5": passed5,
            "pass@10": passed10,
        })

        if (i + 1) % 10 == 0:
            cache.save()
            logger.info("  %d/%d  pass@1=%.3f pass@5=%.3f pass@10=%.3f",
                        i + 1, len(test_unique),
                        pass_k[1] / (i + 1), pass_k[5] / (i + 1), pass_k[10] / (i + 1))

    cache.save()
    elapsed = time.perf_counter() - t0
    n = len(test_unique)

    metrics: Dict[str, Any] = {
        "regime_dir": str(regime_dir),
        "model_dir": args.model_dir,
        "n_test_theorems": n,
        "n_train_rows": len(train_rows),
        "n_train_theorems": len({r["theorem_name"] for r in train_rows}),
        "top_k": args.top_k,
        "verified": args.verify,
        "pass@1": pass_k[1] / n if n else 0.0,
        "pass@5": pass_k[5] / n if n else 0.0,
        "pass@10": pass_k[10] / n if n else 0.0,
        "total_verified_candidates": total_verified_cands,
        "novel_verified": novel_verified,
        "donorless_verified": donorless_verified,
        "cross_family_verified": cross_family_verified,
        "cross_operation_verified": cross_operation_verified,
        "per_family": {
            f: {"n": d["n"],
                "pass@5": d["pass5"] / d["n"] if d["n"] else 0.0,
                "pass@10": d["pass10"] / d["n"] if d["n"] else 0.0}
            for f, d in sorted(by_fam.items())
        },
        "per_operation": {
            o: {"n": d["n"],
                "pass@5": d["pass5"] / d["n"] if d["n"] else 0.0,
                "pass@10": d["pass10"] / d["n"] if d["n"] else 0.0}
            for o, d in sorted(by_op.items())
        },
        "elapsed_seconds": elapsed,
    }
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    with (out_dir / "predictions.jsonl").open("w", encoding="utf-8") as f:
        for p in predictions:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with (out_dir / "verified_candidates.jsonl").open("w", encoding="utf-8") as f:
        for v in verified_rows:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
    logger.info("wrote %s   pass@1=%.3f pass@5=%.3f pass@10=%.3f  novel=%d  donorless=%d",
                out_dir, metrics["pass@1"], metrics["pass@5"], metrics["pass@10"],
                novel_verified, donorless_verified)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
