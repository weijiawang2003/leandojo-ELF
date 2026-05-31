"""Mini-ELF v26 — Part 6: evaluate Mathlib specialists vs v24/v25 on tier-C.

Compares any set of token-seq2seq models on any set of Mathlib-tier benchmarks.
Candidate pools come ONLY from each model's beam search (+ literal-adapt
compose) — the manual reference candidates are never fed to a model. Every
candidate is verified by the **batched** `import Mathlib` verifier
(`mini_elf_lean.mathlib_verifier`); a verdict for (theorem, candidate) is
model-independent, so the whole comparison shares one global verification pass.

The rerank configs (raw / rule / learned / policy / abstract / policy_abstract)
and the failure taxonomy are imported from the v25 eval so the methodology is
identical — only the verifier is faster.

Usage:
  evaluate_v26_specialist.py \
     --model v24=data/models/token_seq2seq_v24_broad_residual \
     --model v26_base=data/models/token_seq2seq_v26_mathlib_specialist_base \
     --bench v25_heldout=data/seeds/v25_mathlib_tierc_test_seeds.jsonl \
     --bench v26_holdout=data/processed/.../theorem_holdout/test_seeds.jsonl \
     --lean-path "<LEAN_PATH>"

Honesty: real Mathlib typecheck, no state_after, no manual oracle as
predictions, v24 model untouched.
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
from mini_elf_lean.literal_aware_decode import compose_candidates  # noqa: E402
from mini_elf_lean.mathlib_verifier import BatchMathlibVerifier  # noqa: E402
from mini_elf_lean.token_seq2seq import load_token_model, predict_beams  # noqa: E402

# reuse v25 ordering machinery + taxonomy (identical methodology)
from evaluate_v25_tierc import (  # noqa: E402
    CONFIGS, _first_rank, _order_abstract, _order_learned, _order_policy,
    _order_policy_abstract, _order_raw, _order_rule, _pass_at, _rows, v25_taxonomy,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v26_specialist")

DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _kv(s: str) -> Tuple[str, str]:
    k, v = s.split("=", 1)
    return k, v


def build_pool(model, vocab, mcfg, stmt, state, k_max):
    beams = predict_beams(model, vocab, mcfg, stmt, state, beam_width=k_max, length_penalty=0.7)
    seen: Dict[str, str] = {}
    for t, _s in beams:
        t = t.strip()
        if t and t not in seen:
            seen[t] = "token_seq2seq:v26"
    for t, src, _m in compose_candidates(list(seen.keys()), state_before=state, theorem_statement=stmt):
        if t not in seen:
            seen[t] = src
    return list(seen.items())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--model", action="append", required=True, help="label=dir (repeatable)")
    ap.add_argument("--bench", action="append", required=True, help="label=seeds.jsonl (repeatable)")
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path", default=None)
    ap.add_argument("--pattern-bag-rows", default=str(ROOT / "data" / "processed" / "v24_broad_plus_residual" / "train_rows.jsonl"))
    ap.add_argument("--learned-reranker", default=str(ROOT / "data" / "models" / "v15_reranker" / "neg_imp_exfalso"))
    ap.add_argument("--out-root", default=str(ROOT / "data" / "baselines" / "v26_specialist_eval"))
    ap.add_argument("--k-max", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=300.0)
    args = ap.parse_args(argv)

    models = [_kv(m) for m in args.model]
    benches = [_kv(b) for b in args.bench]
    scratch = Path(args.scratch_dir).resolve()

    bag = build_pattern_bag(_read(Path(args.pattern_bag_rows)))
    rr = AbstractPatternReranker(bag=bag)
    learned = LearnedReranker.load(Path(args.learned_reranker))

    loaded = {label: load_token_model(Path(d)) for label, d in models}
    logger.info("loaded %d models, %d benchmarks", len(loaded), len(benches))

    # ---- Phase 1: build pools, collect unique (theorem, statement, candidate) ----
    # pools[(model_label, bench_label)][theorem_name] = (seed, pool_list)
    pools: Dict[Tuple[str, str], Dict[str, Tuple[Dict, List]]] = {}
    work: Dict[Tuple[str, str], Tuple[str, str]] = {}  # (thm, cand) -> (stmt, cand)
    bench_seeds = {bl: _read(Path(bp)) for bl, bp in benches}
    for ml, _d in models:
        model, vocab, mcfg = loaded[ml]
        for bl, _bp in benches:
            d: Dict[str, Tuple[Dict, List]] = {}
            for seed in bench_seeds[bl]:
                nm, stmt, state = seed["theorem_name"], seed["theorem_statement"], seed["state_before"]
                pool = build_pool(model, vocab, mcfg, stmt, state, args.k_max)
                d[nm] = (seed, pool)
                for cand, _src in pool:
                    work[(nm, cand)] = (stmt, cand)
            pools[(ml, bl)] = d
    logger.info("unique (theorem, candidate) pairs to verify: %d", len(work))

    # ---- Phase 2: one global batched verification pass ----
    verifier = BatchMathlibVerifier(scratch, lean_path=args.lean_path, timeout=args.timeout)
    if not verifier.warmup():
        logger.error("Mathlib warmup failed"); return 2
    items = [(nm, stmt, cand) for (nm, cand), (stmt, _c) in work.items()]
    verdicts = verifier.verify_many(items)
    vmap: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for vd in verdicts:
        vmap[(vd.theorem_name, vd.tactic)] = {"success": vd.success, "error": vd.error}
    logger.info("verified %d pairs in %d lean invocations (%.1fs)",
                len(vmap), verifier.n_invocations, verifier.total_lean_seconds)

    # ---- Phase 3: score every (model, bench, config) ----
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    comparison: Dict[str, Any] = {"models": dict(models), "benchmarks": dict(benches),
                                  "k_max": args.k_max, "results": {}}

    for ml, _d in models:
        for bl, _bp in benches:
            seeds_pools = pools[(ml, bl)]
            n = len(seeds_pools)
            per_pass = {c: {1: 0, 5: 0, 10: 0} for c in CONFIGS}
            per_first = {c: [] for c in CONFIGS}
            per_tax = {c: {} for c in CONFIGS}
            per_cat = {c: {} for c in CONFIGS}
            per_transfer = {c: {} for c in CONFIGS}
            no_verify = {c: {} for c in CONFIGS}
            records = {c: [] for c in CONFIGS}

            for nm, (seed, pool) in seeds_pools.items():
                stmt, state = seed["theorem_statement"], seed["state_before"]
                cat = seed.get("category", "unknown")
                transfer = seed.get("transfer", "unknown")
                op = seed.get("required_operation", "unknown")
                rows = _rows(pool, nm=nm, stmt=stmt, state=state, op=op)
                for cfg in CONFIGS:
                    if cfg == "raw":
                        order = _order_raw(rows)
                    elif cfg == "rule":
                        order = _order_rule(rows)
                    elif cfg == "learned":
                        order = _order_learned(learned, rows)
                    elif cfg == "policy":
                        order = _order_policy(learned, rows)
                    elif cfg == "abstract":
                        order = _order_abstract(rr, rows, category=cat)
                    else:
                        order = _order_policy_abstract(rr, learned, rows, category=cat)
                    reordered = [rows[j] for j in order][:args.k_max]
                    verifs = [{"success": vmap.get((nm, r.candidate), {}).get("success", False),
                               "error": vmap.get((nm, r.candidate), {}).get("error")}
                              for r in reordered]
                    for v in verifs:
                        if not v["success"]:
                            ec = v25_taxonomy(v.get("error"))
                            per_tax[cfg][ec] = per_tax[cfg].get(ec, 0) + 1
                    p1, p5, p10 = _pass_at(verifs, 1), _pass_at(verifs, 5), _pass_at(verifs, 10)
                    per_pass[cfg][1] += int(p1); per_pass[cfg][5] += int(p5); per_pass[cfg][10] += int(p10)
                    fr = _first_rank(verifs)
                    per_first[cfg].append(fr)
                    if fr is None:
                        classes = [v25_taxonomy(v.get("error")) for v in verifs] or ["no_schema_in_beam"]
                        no_verify[cfg][nm] = max(set(classes), key=classes.count)
                    cc = per_cat[cfg].setdefault(cat, {"n": 0, "p1": 0, "p5": 0, "p10": 0})
                    cc["n"] += 1; cc["p1"] += int(p1); cc["p5"] += int(p5); cc["p10"] += int(p10)
                    tt = per_transfer[cfg].setdefault(transfer, {"n": 0, "p1": 0, "p5": 0, "p10": 0})
                    tt["n"] += 1; tt["p1"] += int(p1); tt["p5"] += int(p5); tt["p10"] += int(p10)
                    records[cfg].append({"theorem_name": nm, "category": cat, "transfer": transfer,
                                         "config": cfg, "n_union_candidates": len(pool),
                                         "ordering": [r.candidate for r in reordered],
                                         "verifications": verifs, "pass@1": p1, "pass@5": p5,
                                         "pass@10": p10, "first_verified_rank": fr})

            run_dir = out_root / f"{ml}__{bl}"
            run_dir.mkdir(parents=True, exist_ok=True)
            cfg_metrics = {}
            for cfg in CONFIGS:
                d = run_dir / cfg
                d.mkdir(parents=True, exist_ok=True)
                frs = [r for r in per_first[cfg] if r is not None]
                pc = {c: {"n": v["n"], "pass@1": v["p1"] / v["n"], "pass@5": v["p5"] / v["n"],
                          "pass@10": v["p10"] / v["n"]} for c, v in per_cat[cfg].items()}
                pt = {t: {"n": v["n"], "pass@1": v["p1"] / v["n"], "pass@5": v["p5"] / v["n"],
                          "pass@10": v["p10"] / v["n"]} for t, v in per_transfer[cfg].items()}
                m = {"model": ml, "benchmark": bl, "config": cfg, "n_test_theorems": n,
                     "pass@1": per_pass[cfg][1] / n, "pass@5": per_pass[cfg][5] / n,
                     "pass@10": per_pass[cfg][10] / n,
                     "MRR": sum(1.0 / (r + 1) for r in frs) / n if n else 0.0,
                     "n_no_candidate_verified": sum(1 for r in per_first[cfg] if r is None),
                     "no_verify_reason": no_verify[cfg], "failure_taxonomy": per_tax[cfg],
                     "per_category": pc, "per_transfer": pt,
                     "mathlib": True, "uses_state_after": False, "uses_manual_oracle": False}
                (d / "metrics.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
                with (d / "predictions.jsonl").open("w", encoding="utf-8") as f:
                    for r in records[cfg]:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                cfg_metrics[cfg] = {k: m[k] for k in ("pass@1", "pass@5", "pass@10", "MRR", "n_no_candidate_verified")}
            # best config by pass@5 then pass@1
            best_cfg = max(CONFIGS, key=lambda c: (cfg_metrics[c]["pass@5"], cfg_metrics[c]["pass@1"]))
            comparison["results"][f"{ml}__{bl}"] = {
                "n_test_theorems": n, "best_config": best_cfg,
                "best": cfg_metrics[best_cfg], "raw": cfg_metrics["raw"], "by_config": cfg_metrics}
            logger.info("  %-16s @ %-14s best=%-15s p@1=%.3f p@5=%.3f p@10=%.3f (raw p@10=%.3f) noverify=%d",
                        ml, bl, best_cfg, cfg_metrics[best_cfg]["pass@1"], cfg_metrics[best_cfg]["pass@5"],
                        cfg_metrics[best_cfg]["pass@10"], cfg_metrics["raw"]["pass@10"],
                        cfg_metrics[best_cfg]["n_no_candidate_verified"])

    (out_root / "comparison.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("V26 specialist eval DONE -> %s", out_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
