"""Mini-ELF v27 — Part 2: re-audit v25/v26 Mathlib metrics under the corrected
verifier vs an old naive batched verifier.

The v26 evaluation already verified with the corrected method (`confirm=True`), so
the *corrected* numbers here reproduce the established v26 metrics. The point of
this audit is to quantify whether the **old naive batched verifier** (no sentinel,
no confirm — the path that could be fooled by the parser/lexer recovery skip) would
have *inflated* any of those metrics. For each (model, benchmark) cell we:

  1. build the candidate pool from live beam search (same machinery as the v26
     eval) — identical pools for both verifiers;
  2. verify the union of (theorem, candidate) pairs with BOTH the naive verifier
     and the trusted (corrected) verifier;
  3. recompute pass@1/5/10 under every rerank config with each verdict map and
     report the best-config pass@k for each;
  4. flag any cell where naive > corrected (a metric the old path would inflate).

Mathlib benches use `import Mathlib`; the broad-core bench uses the core verifier.

Honesty: real Lean typecheck, no state_after, no manual oracle as predictions, v24
model untouched.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mini_elf_lean.abstract_pattern_reranker import AbstractPatternReranker, build_pattern_bag  # noqa: E402
from mini_elf_lean.learned_reranker import LearnedReranker  # noqa: E402
from mini_elf_lean.mathlib_batched_verifier import (  # noqa: E402
    NaiveBatchMathlibVerifier, TrustedMathlibVerifier,
)
from mini_elf_lean.token_seq2seq import load_token_model  # noqa: E402
from evaluate_v26_specialist import build_pool  # noqa: E402
from evaluate_v25_tierc import (  # noqa: E402
    CONFIGS, _first_rank, _order_abstract, _order_learned, _order_policy,
    _order_policy_abstract, _order_raw, _order_rule, _pass_at, _rows,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("recompute_v27_mathlib_metrics_corrected")
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _kv(s: str) -> Tuple[str, str]:
    k, v = s.split("=", 1)
    return k, v


def _order_for(cfg, rows, rr, learned, cat):
    if cfg == "raw":
        return _order_raw(rows)
    if cfg == "rule":
        return _order_rule(rows)
    if cfg == "learned":
        return _order_learned(learned, rows)
    if cfg == "policy":
        return _order_policy(learned, rows)
    if cfg == "abstract":
        return _order_abstract(rr, rows, category=cat)
    return _order_policy_abstract(rr, learned, rows, category=cat)


def score(seeds_pools, vmap, rr, learned, k_max):
    """Best-config pass@k under a given verdict map."""
    per = {c: {1: 0, 5: 0, 10: 0} for c in CONFIGS}
    per_first = {c: [] for c in CONFIGS}
    n = len(seeds_pools)
    for nm, (seed, pool) in seeds_pools.items():
        stmt, state = seed["theorem_statement"], seed["state_before"]
        cat = seed.get("category", "unknown")
        op = seed.get("required_operation", "unknown")
        rows = _rows(pool, nm=nm, stmt=stmt, state=state, op=op)
        for cfg in CONFIGS:
            order = _order_for(cfg, rows, rr, learned, cat)
            reordered = [rows[j] for j in order][:k_max]
            verifs = [{"success": vmap.get((nm, r.candidate), False)} for r in reordered]
            per[cfg][1] += int(_pass_at(verifs, 1))
            per[cfg][5] += int(_pass_at(verifs, 5))
            per[cfg][10] += int(_pass_at(verifs, 10))
            per_first[cfg].append(_first_rank(verifs))
    out = {}
    for cfg in CONFIGS:
        out[cfg] = {"pass@1": per[cfg][1] / n, "pass@5": per[cfg][5] / n, "pass@10": per[cfg][10] / n}
    best = max(CONFIGS, key=lambda c: (out[c]["pass@5"], out[c]["pass@1"]))
    return {"n": n, "best_config": best, "best": out[best], "by_config": out}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--model", action="append", required=True, help="label=dir")
    ap.add_argument("--mathlib-bench", action="append", default=[], help="label=seeds.jsonl (import Mathlib)")
    ap.add_argument("--core-bench", action="append", default=[], help="label=seeds.jsonl (core verifier)")
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--pattern-bag-rows", default=str(ROOT / "data" / "processed" / "v24_broad_plus_residual" / "train_rows.jsonl"))
    ap.add_argument("--learned-reranker", default=str(ROOT / "data" / "models" / "v15_reranker" / "neg_imp_exfalso"))
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v27_corrected_metrics" / "report.json"))
    ap.add_argument("--k-max", type=int, default=10)
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    models = [_kv(m) for m in args.model]
    mbench = [_kv(b) for b in args.mathlib_bench]
    cbench = [_kv(b) for b in args.core_bench]

    rr = AbstractPatternReranker(bag=build_pattern_bag(_read(Path(args.pattern_bag_rows))))
    learned = LearnedReranker.load(Path(args.learned_reranker))
    loaded = {label: load_token_model(Path(d)) for label, d in models}

    report: Dict[str, Any] = {"config": "v27_corrected_metrics", "cells": {}, "k_max": args.k_max}

    def run_group(benches, core: bool):
        for ml, _md in models:
            model, vocab, mcfg = loaded[ml]
            for bl, bp in benches:
                seeds = _read(Path(bp))
                if not seeds:
                    continue
                seeds_pools = {}
                work = {}
                for s in seeds:
                    nm = s["theorem_name"]
                    pool = build_pool(model, vocab, mcfg, s["theorem_statement"], s["state_before"], args.k_max)
                    seeds_pools[nm] = (s, pool)
                    for cand, _src in pool:
                        work[(nm, cand)] = (s["theorem_statement"], cand)
                items = [(nm, stmt, cand) for (nm, cand), (stmt, _c) in work.items()]
                common = dict(core=core, lean_path=(None if core else lean_path),
                              timeout=(120.0 if core else 300.0))
                trusted = TrustedMathlibVerifier(scratch, **common)
                if not core:
                    trusted.warmup()
                tv = trusted.verify_many(items, confirm=True)
                tmap = {(v.theorem_name, v.tactic): v.success for v in tv}
                naive = NaiveBatchMathlibVerifier(scratch, **common)
                nv = naive.verify_many(items)
                nmap = {(v.theorem_name, v.tactic): v.success for v in nv}

                corr = score(seeds_pools, tmap, rr, learned, args.k_max)
                naiv = score(seeds_pools, nmap, rr, learned, args.k_max)
                # per-candidate false positives the naive path would introduce
                fp = sum(1 for k in tmap if nmap.get(k) and not tmap[k])
                cell = f"{ml}__{bl}"
                report["cells"][cell] = {
                    "tier": "core" if core else "mathlib", "n": corr["n"],
                    "n_candidates": len(items),
                    "corrected": {"best_config": corr["best_config"], **corr["best"]},
                    "naive": {"best_config": naiv["best_config"], **naiv["best"]},
                    "delta_pass@10": round(naiv["best"]["pass@10"] - corr["best"]["pass@10"], 4),
                    "naive_candidate_false_positives": fp,
                    "naive_inflates": naiv["best"]["pass@10"] > corr["best"]["pass@10"] + 1e-9
                                      or naiv["best"]["pass@5"] > corr["best"]["pass@5"] + 1e-9,
                }
                logger.info("  %-26s corrected p@1/5/10=%.3f/%.3f/%.3f | naive=%.3f/%.3f/%.3f | naiveFP=%d inflates=%s",
                            cell, corr["best"]["pass@1"], corr["best"]["pass@5"], corr["best"]["pass@10"],
                            naiv["best"]["pass@1"], naiv["best"]["pass@5"], naiv["best"]["pass@10"], fp,
                            report["cells"][cell]["naive_inflates"])

    run_group(mbench, core=False)
    run_group(cbench, core=True)

    any_inflate = any(c["naive_inflates"] for c in report["cells"].values())
    total_fp = sum(c["naive_candidate_false_positives"] for c in report["cells"].values())
    report["summary"] = {
        "n_cells": len(report["cells"]),
        "any_naive_inflation": any_inflate,
        "total_naive_candidate_false_positives": total_fp,
        "conclusion": ("naive path would inflate >=1 metric — corrected verifier materially changes results"
                       if any_inflate else
                       "naive == corrected on all real candidates — no previously reported Mathlib metric was inflated"),
        "uses_state_after": False, "uses_manual_oracle": False,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("RECOMPUTE DONE: cells=%d any_inflation=%s total_naive_FP=%d -> %s",
                len(report["cells"]), any_inflate, total_fp, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
