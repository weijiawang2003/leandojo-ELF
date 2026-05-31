"""Mini-ELF v8 Part 6 — fusion eval matrix.

For one ``regime`` × one ``config`` combination, build the right set of
proposers, run :func:`v8_fusion.fuse` on every test row, verify with lean-cli,
and write per-config metrics to ``<out-dir>/<regime>/<config>/metrics.json``.

Supported configs (CLI ``--config``):

  * ``retrieval_only``  — v7 abstraction retrieval only (baseline)
  * ``seq2seq_only``    — seq2seq proposer only
  * ``llm_only``        — LLM proposer only (skip if no key)
  * ``retrieval_seq2seq``  — fusion (retrieval + seq2seq)
  * ``retrieval_llm``     — fusion (retrieval + LLM) [requires key]
  * ``full_fusion``     — fusion (retrieval + seq2seq + LLM + planner +
                          witness); donor-availability hint is set per row

Regimes (CLI ``--regime``):

  * ``current``         — planner_blind_split_lean_cli (v6/v7's interpolation)
  * ``family_holdout/<fam>``     — proof_blocks_family_holdout/<fam>
  * ``operation_holdout/<op>``   — proof_blocks_operation_holdout/<op>
  * ``donorless_eval``           — proof_blocks_donorless_eval
  * ``kshot_<k>``       — planner_blind_kshot_<k>
  * ``literal_holdout`` — planner_blind_literal_holdout

The script does the heavy lifting per call; ``run_mini_elf_v8_eval.sh``
sweeps the matrix.
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
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import (  # noqa: E402
    VerificationCache, make_lean_cli_verifier,
)
from mini_elf_lean.baselines import Example  # noqa: E402
from mini_elf_lean.llm_proposer import LLMProposer  # noqa: E402
from mini_elf_lean.proof_block_seq2seq import (  # noqa: E402
    ProofBlockSeq2SeqProposer,
)
from mini_elf_lean.retrieval_abstraction_proposer import (  # noqa: E402
    AbstractionAwareRetrievalProposer,
)
from mini_elf_lean.v8_fusion import family_in_pool, fuse  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_mini_elf_v8")


# --------------------------------------------------------------------------- #
# Data loaders
# --------------------------------------------------------------------------- #

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


REGIME_DIRS = {
    "current":          ROOT / "data" / "processed" / "planner_blind_split_lean_cli",
    "literal_holdout":  ROOT / "data" / "processed" / "planner_blind_literal_holdout",
    "kshot_0":          ROOT / "data" / "processed" / "planner_blind_kshot_0",
    "kshot_1":          ROOT / "data" / "processed" / "planner_blind_kshot_1",
    "kshot_2":          ROOT / "data" / "processed" / "planner_blind_kshot_2",
}


def _regime_dir(regime: str) -> Path:
    if regime in REGIME_DIRS:
        return REGIME_DIRS[regime]
    if regime.startswith("family_holdout/"):
        fam = regime.split("/", 1)[1]
        return ROOT / "data" / "processed" / "proof_blocks_family_holdout" / fam
    if regime.startswith("operation_holdout/"):
        op = regime.split("/", 1)[1]
        return ROOT / "data" / "processed" / "proof_blocks_operation_holdout" / op
    if regime == "donorless_eval":
        return ROOT / "data" / "processed" / "proof_blocks_donorless_eval"
    raise ValueError(f"unknown regime {regime!r}")


def _seq2seq_dir_for(regime: str) -> Path:
    """Map a regime to the matching seq2seq model directory."""
    if regime == "current" or regime.startswith("kshot_") or regime == "literal_holdout":
        return ROOT / "data" / "models" / "proof_block_seq2seq_interpolation"
    if regime.startswith("family_holdout/"):
        fam = regime.split("/", 1)[1]
        return ROOT / "data" / "models" / f"proof_block_seq2seq_family_holdout_{fam}"
    if regime.startswith("operation_holdout/"):
        op = regime.split("/", 1)[1]
        return ROOT / "data" / "models" / f"proof_block_seq2seq_operation_holdout_{op}"
    if regime == "donorless_eval":
        return ROOT / "data" / "models" / "proof_block_seq2seq_donorless_eval"
    return ROOT / "data" / "models" / "proof_block_seq2seq_interpolation"


def _dedup_test_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for r in rows:
        if r.get("split") != "test":
            continue
        k = (r["theorem_name"], r["state_before"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


# --------------------------------------------------------------------------- #
# Proposer construction per config
# --------------------------------------------------------------------------- #

def _train_examples_for(regime: str, regime_dir: Path) -> List[Any]:
    """Train rows for *retrieval* — needs whatever the regime considers train."""
    if regime_dir.is_dir() and (regime_dir / "train.jsonl").exists():
        # v8 proof_blocks_*: train+val are train for retrieval purposes
        rows = _read_jsonl(regime_dir / "train.jsonl") + _read_jsonl(regime_dir / "val.jsonl")
    else:
        # v6/v7 splits store a single next_tactic.jsonl with split tags
        rows = [r for r in _read_jsonl(regime_dir / "next_tactic.jsonl")
                if r.get("split") in ("train", "val")]
    out = []
    for r in rows:
        out.append(Example(
            theorem_name=r["theorem_name"],
            theorem_statement=r["theorem_statement"],
            state_before=r["state_before"],
            tactic=r["tactic"],
            split=r.get("split", "train"),
        ))
    return out


def _build_proposers(config: str, regime: str, regime_dir: Path):
    train_ex = _train_examples_for(regime, regime_dir)
    proposers = []
    if config in ("retrieval_only", "retrieval_seq2seq", "retrieval_llm", "full_fusion"):
        retr = AbstractionAwareRetrievalProposer(neighbors=24)
        retr.fit(train_ex)
        proposers.append(retr)
    if config in ("seq2seq_only", "retrieval_seq2seq", "full_fusion"):
        m_dir = _seq2seq_dir_for(regime)
        s2s = ProofBlockSeq2SeqProposer(m_dir)
        if s2s.available():
            proposers.append(s2s)
        else:
            logger.warning("seq2seq model not available at %s (skipping)", m_dir)
    if config in ("llm_only", "retrieval_llm", "full_fusion"):
        llm = LLMProposer()
        if llm.available():
            proposers.append(llm)
        else:
            logger.info("LLM not available; skipping LLM in config=%s", config)
    return proposers, train_ex


def _row_family(r: Dict[str, Any]) -> Optional[str]:
    fam = r.get("family")
    if fam is not None:
        return fam
    return (r.get("metadata") or {}).get("pattern_family")


def _row_op(r: Dict[str, Any]) -> str:
    return r.get("required_operation") or "unknown"


# --------------------------------------------------------------------------- #
# Eval driver
# --------------------------------------------------------------------------- #

def _evaluate_one(*, regime: str, config: str, top_k: int,
                  out_root: Path, cache: VerificationCache,
                  verifier) -> Dict[str, Any]:
    regime_dir = _regime_dir(regime)
    if regime_dir.is_dir() and (regime_dir / "test.jsonl").exists():
        all_rows = _read_jsonl(regime_dir / "test.jsonl")
        all_rows = [{**r, "split": "test"} for r in all_rows]
    else:
        all_rows = _read_jsonl(regime_dir / "next_tactic.jsonl")
    test_rows = _dedup_test_rows(all_rows)

    proposers, train_ex = _build_proposers(config, regime, regime_dir)
    # Recover families/operations from the train pool. Reads dataset-specific
    # files (v8 proof_blocks_* has train.jsonl; v6/v7 splits have a single
    # next_tactic.jsonl with a split tag).
    pool_families: set = set()
    pool_op: set = set()
    if (regime_dir / "train.jsonl").exists():
        for r in _read_jsonl(regime_dir / "train.jsonl"):
            f = _row_family(r)
            if f:
                pool_families.add(f)
            pool_op.add(_row_op(r))
    else:
        for r in _read_jsonl(regime_dir / "next_tactic.jsonl"):
            if r.get("split") == "train":
                f = _row_family(r)
                if f:
                    pool_families.add(f)
                pool_op.add(_row_op(r))
    train_tactic_set = {e.tactic.strip() for e in train_ex if e.tactic}

    pass_k = {1: 0, 5: 0, 10: 0}
    by_fam = defaultdict(lambda: {"n": 0, "p5": 0, "p10": 0})
    by_op = defaultdict(lambda: {"n": 0, "p5": 0, "p10": 0})
    by_source = Counter()
    n_verified = novel_v = donorless_v = cross_fam_v = cross_op_v = 0
    rows_out: List[Dict[str, Any]] = []
    verified_rows: List[Dict[str, Any]] = []

    t0 = time.perf_counter()
    for i, row in enumerate(test_rows):
        fam = _row_family(row)
        op = _row_op(row)
        donor_avail = family_in_pool(fam, pool_families)
        op_avail = op in pool_op

        res = fuse(proposers, row["theorem_statement"], row["state_before"],
                   theorem_name=row["theorem_name"],
                   donor_available=donor_avail, top_k=top_k,
                   per_source_k=top_k)
        for c in res.candidates:
            by_source[c.source] += 1

        cand_tacs = [c.tactic for c in res.candidates]
        verifs: List[Dict[str, Any]] = []
        for tac in cand_tacs:
            hit = cache.get(row["theorem_name"], tac)
            if hit is not None:
                verifs.append(hit); continue
            if verifier is None:
                verifs.append({"success": False, "error": "no_verifier"})
                continue
            try:
                v = verifier(row["theorem_name"], row["theorem_statement"], tac)
            except Exception as exc:  # noqa: BLE001
                v = {"success": False, "error": f"verifier_exception:{exc}"}
            cache.put(row["theorem_name"], tac, v)
            verifs.append(v)

        succ = [bool(v.get("success")) for v in verifs]
        p1, p5, p10 = any(succ[:1]), any(succ[:5]), any(succ[:10])
        pass_k[1] += int(p1); pass_k[5] += int(p5); pass_k[10] += int(p10)
        if fam:
            by_fam[fam]["n"] += 1; by_fam[fam]["p5"] += int(p5); by_fam[fam]["p10"] += int(p10)
        by_op[op]["n"] += 1; by_op[op]["p5"] += int(p5); by_op[op]["p10"] += int(p10)

        for j, (tac, v) in enumerate(zip(cand_tacs, verifs)):
            if v.get("success"):
                n_verified += 1
                if tac.strip() not in train_tactic_set: novel_v += 1
                if not donor_avail: donorless_v += 1; cross_fam_v += 1
                if not op_avail: cross_op_v += 1
                verified_rows.append({
                    "theorem_name": row["theorem_name"], "rank": j,
                    "family": fam, "required_operation": op,
                    "tactic": tac,
                    "source": res.candidates[j].source if j < len(res.candidates) else "?",
                    "donor_available": donor_avail, "op_available": op_avail,
                })

        rows_out.append({
            "theorem_name": row["theorem_name"], "family": fam,
            "required_operation": op, "donor_available": donor_avail,
            "candidates": cand_tacs,
            "sources": [c.source for c in res.candidates],
            "verifications": [
                {"success": bool(v.get("success")), "error": v.get("error")}
                for v in verifs
            ],
            "pass@1": p1, "pass@5": p5, "pass@10": p10,
        })

        if (i + 1) % 10 == 0:
            cache.save()
            logger.info("  [%s/%s] %d/%d  pass@5=%.3f", regime, config,
                        i + 1, len(test_rows), pass_k[5] / (i + 1))

    cache.save()
    n = len(test_rows)
    metrics = {
        "regime": regime, "config": config,
        "n_test_theorems": n, "top_k": top_k,
        "pass@1": pass_k[1] / n if n else 0.0,
        "pass@5": pass_k[5] / n if n else 0.0,
        "pass@10": pass_k[10] / n if n else 0.0,
        "total_verified_candidates": n_verified,
        "novel_verified": novel_v,
        "donorless_verified": donorless_v,
        "cross_family_verified": cross_fam_v,
        "cross_operation_verified": cross_op_v,
        "candidates_by_source": dict(by_source),
        "per_family": {f: {"n": d["n"],
                           "pass@5": d["p5"] / d["n"] if d["n"] else 0.0,
                           "pass@10": d["p10"] / d["n"] if d["n"] else 0.0}
                       for f, d in sorted(by_fam.items())},
        "per_operation": {o: {"n": d["n"],
                              "pass@5": d["p5"] / d["n"] if d["n"] else 0.0,
                              "pass@10": d["p10"] / d["n"] if d["n"] else 0.0}
                          for o, d in sorted(by_op.items())},
        "elapsed_seconds": time.perf_counter() - t0,
    }

    out_dir = out_root / regime / config
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    with (out_dir / "predictions.jsonl").open("w", encoding="utf-8") as f:
        for p in rows_out:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with (out_dir / "verified_candidates.jsonl").open("w", encoding="utf-8") as f:
        for v in verified_rows:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
    logger.info("wrote %s   pass@1=%.3f pass@5=%.3f pass@10=%.3f",
                out_dir, metrics["pass@1"], metrics["pass@5"], metrics["pass@10"])
    return metrics


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--regime", required=True)
    ap.add_argument("--config", required=True,
                    choices=["retrieval_only", "seq2seq_only", "llm_only",
                             "retrieval_seq2seq", "retrieval_llm", "full_fusion"])
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--out-root", default=str(ROOT / "data" / "baselines" / "v8_eval"))
    ap.add_argument("--cache", default=str(ROOT / "data" / "lean_cache" / "v8_fusion_cache.json"))
    ap.add_argument("--no-verify", dest="verify", action="store_false")
    ap.set_defaults(verify=True)
    args = ap.parse_args()

    cache = VerificationCache.load(Path(args.cache), enabled=True) \
        if args.verify else VerificationCache(enabled=False)
    verifier = make_lean_cli_verifier(timeout=60.0) if args.verify else None

    _evaluate_one(regime=args.regime, config=args.config, top_k=args.top_k,
                  out_root=Path(args.out_root), cache=cache, verifier=verifier)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
