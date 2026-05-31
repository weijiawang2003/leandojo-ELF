"""Mini-ELF v27 — Part 7a: evaluate Mathlib specialists (v24/v25/v26/v27) on the
tier-C benchmarks with the TRUSTED verifier.

Same candidate-pool + rerank machinery as the v25/v26 eval (token-seq2seq beams +
literal-adapt compose + raw/rule/learned/policy/abstract/policy_abstract orderings,
failure taxonomy), but every candidate is verified with
`mini_elf_lean.mathlib_batched_verifier.TrustedMathlibVerifier` (sentinel + confirm
+ rescue — sound and complete, see V27 Part 1). One global verification pass shared
across all (model, bench) cells, then per-config pass@k / MRR / per-category
breakdown.

Honesty: real `import Mathlib` typecheck, no state_after, manual targets never fed
to a model as predictions, v24 model untouched.
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
from mini_elf_lean.mathlib_batched_verifier import TrustedMathlibVerifier  # noqa: E402
from mini_elf_lean.token_seq2seq import load_token_model  # noqa: E402
from evaluate_v26_specialist import build_pool  # noqa: E402
from evaluate_v25_tierc import (  # noqa: E402
    CONFIGS, _first_rank, _order_abstract, _order_learned, _order_policy,
    _order_policy_abstract, _order_raw, _order_rule, _pass_at, _rows, v25_taxonomy,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v27_mathlib_specialists")
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--model", action="append", required=True, help="label=dir")
    ap.add_argument("--bench", action="append", required=True, help="label=seeds.jsonl")
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--pattern-bag-rows", default=str(ROOT / "data" / "processed" / "v24_broad_plus_residual" / "train_rows.jsonl"))
    ap.add_argument("--learned-reranker", default=str(ROOT / "data" / "models" / "v15_reranker" / "neg_imp_exfalso"))
    ap.add_argument("--out-root", default=str(ROOT / "data" / "baselines" / "v27_specialist_eval"))
    ap.add_argument("--k-max", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=300.0)
    args = ap.parse_args(argv)

    models = [_kv(m) for m in args.model]
    benches = [_kv(b) for b in args.bench]
    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None

    rr = AbstractPatternReranker(bag=build_pattern_bag(_read(Path(args.pattern_bag_rows))))
    learned = LearnedReranker.load(Path(args.learned_reranker))
    loaded = {label: load_token_model(Path(d)) for label, d in models}
    bench_seeds = {bl: _read(Path(bp)) for bl, bp in benches}
    logger.info("loaded %d models, %d benchmarks", len(loaded), len(benches))

    # Phase 1: pools
    pools: Dict[Tuple[str, str], Dict[str, Tuple[Dict, List]]] = {}
    work: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for ml, _d in models:
        model, vocab, mcfg = loaded[ml]
        for bl, _bp in benches:
            d: Dict[str, Tuple[Dict, List]] = {}
            for seed in bench_seeds[bl]:
                nm = seed["theorem_name"]
                pool = build_pool(model, vocab, mcfg, seed["theorem_statement"], seed["state_before"], args.k_max)
                d[nm] = (seed, pool)
                for cand, _src in pool:
                    work[(nm, cand)] = (seed["theorem_statement"], cand)
            pools[(ml, bl)] = d
    logger.info("unique (theorem, candidate) pairs: %d", len(work))

    # Phase 2: one global TRUSTED verification pass
    verifier = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=args.timeout)
    if not verifier.warmup():
        logger.error("Mathlib warmup failed"); return 2
    items = [(nm, stmt, cand) for (nm, cand), (stmt, _c) in work.items()]
    verdicts = verifier.verify_many(items, confirm=True)
    vmap = {(v.theorem_name, v.tactic): {"success": v.success, "error": v.error} for v in verdicts}
    logger.info("verified %d pairs in %d lean invocations (%.1fs)",
                len(vmap), verifier.n_invocations, verifier.total_lean_seconds)

    # Phase 3: score
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    comparison: Dict[str, Any] = {"models": dict(models), "benchmarks": dict(benches),
                                  "verifier": "TrustedMathlibVerifier", "results": {}}
    for ml, _d in models:
        for bl, _bp in benches:
            seeds_pools = pools[(ml, bl)]
            n = len(seeds_pools)
            per_pass = {c: {1: 0, 5: 0, 10: 0} for c in CONFIGS}
            per_first = {c: [] for c in CONFIGS}
            per_cat = {c: {} for c in CONFIGS}
            per_tax = {c: {} for c in CONFIGS}
            no_verify = {c: {} for c in CONFIGS}
            records = {c: [] for c in CONFIGS}
            for nm, (seed, pool) in seeds_pools.items():
                stmt, state = seed["theorem_statement"], seed["state_before"]
                cat = seed.get("category", "unknown")
                op = seed.get("required_operation", seed.get("expected_skill", "unknown"))
                rows = _rows(pool, nm=nm, stmt=stmt, state=state, op=op)
                for cfg in CONFIGS:
                    order = _order_for(cfg, rows, rr, learned, cat)
                    reordered = [rows[j] for j in order][:args.k_max]
                    verifs = [{"success": vmap.get((nm, r.candidate), {}).get("success", False),
                               "error": vmap.get((nm, r.candidate), {}).get("error")} for r in reordered]
                    for v in verifs:
                        if not v["success"]:
                            ec = v25_taxonomy(v.get("error"))
                            per_tax[cfg][ec] = per_tax[cfg].get(ec, 0) + 1
                    p1, p5, p10 = _pass_at(verifs, 1), _pass_at(verifs, 5), _pass_at(verifs, 10)
                    per_pass[cfg][1] += int(p1); per_pass[cfg][5] += int(p5); per_pass[cfg][10] += int(p10)
                    fr = _first_rank(verifs); per_first[cfg].append(fr)
                    if fr is None:
                        classes = [v25_taxonomy(v.get("error")) for v in verifs] or ["no_schema_in_beam"]
                        no_verify[cfg][nm] = max(set(classes), key=classes.count)
                    cc = per_cat[cfg].setdefault(cat, {"n": 0, "p1": 0, "p5": 0, "p10": 0})
                    cc["n"] += 1; cc["p1"] += int(p1); cc["p5"] += int(p5); cc["p10"] += int(p10)
                    records[cfg].append({"theorem_name": nm, "category": cat, "config": cfg,
                                         "ordering": [r.candidate for r in reordered], "verifications": verifs,
                                         "pass@1": p1, "pass@5": p5, "pass@10": p10, "first_verified_rank": fr})
            run_dir = out_root / f"{ml}__{bl}"
            run_dir.mkdir(parents=True, exist_ok=True)
            cfg_metrics = {}
            for cfg in CONFIGS:
                d = run_dir / cfg
                d.mkdir(parents=True, exist_ok=True)
                frs = [r for r in per_first[cfg] if r is not None]
                pc = {c: {"n": v["n"], "pass@1": v["p1"] / v["n"], "pass@5": v["p5"] / v["n"],
                          "pass@10": v["p10"] / v["n"]} for c, v in per_cat[cfg].items()}
                m = {"model": ml, "benchmark": bl, "config": cfg, "n_test_theorems": n,
                     "pass@1": per_pass[cfg][1] / n, "pass@5": per_pass[cfg][5] / n, "pass@10": per_pass[cfg][10] / n,
                     "MRR": sum(1.0 / (r + 1) for r in frs) / n if n else 0.0,
                     "n_no_candidate_verified": sum(1 for r in per_first[cfg] if r is None),
                     "no_verify_reason": no_verify[cfg], "failure_taxonomy": per_tax[cfg], "per_category": pc,
                     "mathlib": True, "uses_state_after": False, "uses_manual_oracle": False}
                (d / "metrics.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
                with (d / "predictions.jsonl").open("w", encoding="utf-8") as f:
                    for r in records[cfg]:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                cfg_metrics[cfg] = {k: m[k] for k in ("pass@1", "pass@5", "pass@10", "MRR", "n_no_candidate_verified")}
            best_cfg = max(CONFIGS, key=lambda c: (cfg_metrics[c]["pass@5"], cfg_metrics[c]["pass@1"]))
            comparison["results"][f"{ml}__{bl}"] = {"n_test_theorems": n, "best_config": best_cfg,
                                                    "best": cfg_metrics[best_cfg], "raw": cfg_metrics["raw"],
                                                    "by_config": cfg_metrics}
            logger.info("  %-22s @ %-20s best=%-15s p@1/5/10=%.3f/%.3f/%.3f noverify=%d",
                        ml, bl, best_cfg, cfg_metrics[best_cfg]["pass@1"], cfg_metrics[best_cfg]["pass@5"],
                        cfg_metrics[best_cfg]["pass@10"], cfg_metrics[best_cfg]["n_no_candidate_verified"])
    (out_root / "comparison.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("V27 specialist eval DONE -> %s", out_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
