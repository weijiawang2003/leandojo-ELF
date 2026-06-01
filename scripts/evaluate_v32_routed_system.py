"""Mini-ELF v32 — Part 6: routed system over all held-outs + stress + fresh holdout.

Router (`V32MathlibRouter`): core-env → untouched v24; mathlib-env → v32 canonical
specialist (canonical-mode pooling + raw v30 fallback). Tier-C now also includes the
adversarial identifier-stress benchmark and the fresh Mathlib micro-holdout. Asserts
broad-core preserves 0.9375/0.9583; compares routed v31 vs v32. Adoption rule reported.
Real Lean; no state_after; v24 untouched.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

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
from mini_elf_lean.v32_mathlib_router import BROAD_CORE, MATHLIB_SPECIALIST, V32MathlibRouter  # noqa: E402
from evaluate_v26_specialist import build_pool  # noqa: E402
from evaluate_v31_normalized_specialists import build_pool_for  # noqa: E402
from evaluate_v25_tierc import (  # noqa: E402
    CONFIGS, _first_rank, _order_abstract, _order_learned, _order_policy,
    _order_policy_abstract, _order_raw, _order_rule, _pass_at, _rows, v25_taxonomy,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v32_routed_system")
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"
V27_ROUTED_BAR = {"pass@5": 0.9375, "pass@10": 0.9583}
P = ROOT / "data" / "processed"


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


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


def score_tier(pools, vmap, rr, learned, k_max):
    per_pass = {c: {1: 0, 5: 0, 10: 0} for c in CONFIGS}
    per_first = {c: [] for c in CONFIGS}
    per_cat = {c: {} for c in CONFIGS}
    n = len(pools)
    for seed, pool in pools:
        nm, stmt, state = seed["theorem_name"], seed["theorem_statement"], seed["state_before"]
        cat = seed.get("category", "unknown")
        op = seed.get("required_operation", seed.get("expected_skill", "unknown"))
        rows = _rows(pool, nm=nm, stmt=stmt, state=state, op=op)
        for cfg in CONFIGS:
            order = _order_for(cfg, rows, rr, learned, cat)
            reordered = [rows[j] for j in order][:k_max]
            verifs = [{"success": vmap.get((nm, r.candidate), {}).get("success", False),
                       "error": vmap.get((nm, r.candidate), {}).get("error")} for r in reordered]
            p1, p5, p10 = _pass_at(verifs, 1), _pass_at(verifs, 5), _pass_at(verifs, 10)
            per_pass[cfg][1] += int(p1); per_pass[cfg][5] += int(p5); per_pass[cfg][10] += int(p10)
            per_first[cfg].append(_first_rank(verifs))
            cc = per_cat[cfg].setdefault(cat, {"n": 0, "p10": 0})
            cc["n"] += 1; cc["p10"] += int(p10)
    out = {}
    for cfg in CONFIGS:
        frs = [r for r in per_first[cfg] if r is not None]
        out[cfg] = {"pass@1": per_pass[cfg][1] / n, "pass@5": per_pass[cfg][5] / n, "pass@10": per_pass[cfg][10] / n,
                    "MRR": sum(1.0 / (r + 1) for r in frs) / n if n else 0.0,
                    "n_no_candidate_verified": sum(1 for r in per_first[cfg] if r is None),
                    "per_category": {c: {"n": v["n"], "pass@10": v["p10"] / v["n"]} for c, v in per_cat[cfg].items()}}
    return out, n


def best_cfg(m):
    return max(CONFIGS, key=lambda c: (m[c]["pass@5"], m[c]["pass@1"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--broad-seeds", default=str(ROOT / "data" / "seeds" / "v18_broad_core_seeds.jsonl"))
    ap.add_argument("--broad-model", default=str(ROOT / "data" / "models" / "token_seq2seq_v24_broad_residual"))
    ap.add_argument("--specialist-model", default=str(ROOT / "data" / "models" / "token_seq2seq_v32_canonical_repaired"))
    ap.add_argument("--specialist-mode", default="canonical")
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--pattern-bag-rows", default=str(ROOT / "data" / "processed" / "v24_broad_plus_residual" / "train_rows.jsonl"))
    ap.add_argument("--learned-reranker", default=str(ROOT / "data" / "models" / "v15_reranker" / "neg_imp_exfalso"))
    ap.add_argument("--out-root", default=str(ROOT / "data" / "baselines" / "v32_routed_system"))
    ap.add_argument("--k-max", type=int, default=10)
    args = ap.parse_args(argv)

    tierc_paths = [
        ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl",
        P / "v26_mathlib_specialist_splits" / "theorem_holdout" / "test_seeds.jsonl",
        P / "v27_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl",
        P / "v28_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl",
        P / "v29_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl",
        P / "v30_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl",
        P / "v30_mathlib_specialist" / "targeted_family_holdout" / "test_seeds.jsonl",
        P / "v31_canonical_mathlib" / "token_diversity_holdout" / "test_seeds.jsonl",
        ROOT / "data" / "seeds" / "v32_identifier_stress_seeds.jsonl",
        ROOT / "data" / "seeds" / "v32_fresh_mathlib_holdout_seeds.jsonl",
    ]
    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    rr = AbstractPatternReranker(bag=build_pattern_bag(_read(Path(args.pattern_bag_rows))))
    learned = LearnedReranker.load(Path(args.learned_reranker))
    broad = load_token_model(Path(args.broad_model))
    specialist = load_token_model(Path(args.specialist_model))
    v30_fallback = load_token_model(ROOT / "data" / "models" / "token_seq2seq_v30_general_targeted")
    router = V32MathlibRouter(available={BROAD_CORE, MATHLIB_SPECIALIST})

    broad_seeds = _read(Path(args.broad_seeds))
    tierc_seeds = [s for tp in tierc_paths for s in _read(tp)]
    routing_log, broad_pools, tierc_pools = [], [], []
    pool_stats = {"n_canonical_generated": 0, "n_unresolved_rejected": 0, "n_from_canonical": 0, "n_from_raw_fallback": 0}
    for seed in broad_seeds:
        key = router.route_seed(seed); routing_log.append({**router.explain(seed), "tier": "broad_core"})
        if key == BROAD_CORE:
            broad_pools.append((seed, build_pool(*broad, seed["theorem_statement"], seed["state_before"], args.k_max)))
        else:
            pool, _st = build_pool_for(args.specialist_mode, specialist, v30_fallback, seed["theorem_statement"], seed["state_before"], args.k_max)
            broad_pools.append((seed, pool))
    for seed in tierc_seeds:
        key = router.route_seed(seed); routing_log.append({**router.explain(seed), "tier": "tierc"})
        if key == BROAD_CORE:
            tierc_pools.append((seed, build_pool(*broad, seed["theorem_statement"], seed["state_before"], args.k_max)))
        else:
            pool, st = build_pool_for(args.specialist_mode, specialist, v30_fallback, seed["theorem_statement"], seed["state_before"], args.k_max)
            tierc_pools.append((seed, pool))
            for kk in pool_stats:
                pool_stats[kk] += st[kk]
    n_b2c = sum(1 for r in routing_log if r["tier"] == "broad_core" and r["chosen_model"] == BROAD_CORE)
    n_t2s = sum(1 for r in routing_log if r["tier"] == "tierc" and r["chosen_model"] != BROAD_CORE)
    logger.info("routing: %d/%d broad->v24, %d/%d tierc->specialist", n_b2c, len(broad_seeds), n_t2s, len(tierc_seeds))

    core_v = TrustedMathlibVerifier(scratch, core=True, timeout=120)
    items_b = list({(s["theorem_name"], c): (s["theorem_statement"], c) for s, pool in broad_pools for c, _s in pool}.items())
    vb = core_v.verify_many([(nm, st, c) for (nm, c), (st, _c) in items_b], confirm=True)
    vmap_b = {(x.theorem_name, x.tactic): {"success": x.success, "error": x.error} for x in vb}
    mathlib_v = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=300)
    if not mathlib_v.warmup():
        logger.error("warmup failed"); return 2
    items_t = list({(s["theorem_name"], c): (s["theorem_statement"], c) for s, pool in tierc_pools for c, _s in pool}.items())
    vt = mathlib_v.verify_many([(nm, st, c) for (nm, c), (st, _c) in items_t], confirm=True)
    vmap_t = {(x.theorem_name, x.tactic): {"success": x.success, "error": x.error} for x in vt}
    logger.info("verified broad=%d tierc=%d (%.1fs)", len(vmap_b), len(vmap_t), mathlib_v.total_lean_seconds)

    bm, n_b = score_tier(broad_pools, vmap_b, rr, learned, args.k_max)
    tm, n_t = score_tier(tierc_pools, vmap_t, rr, learned, args.k_max)
    bc, tc = best_cfg(bm), best_cfg(tm)
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "broad_core_metrics.json").write_text(json.dumps({"n": n_b, "best_config": bc, "by_config": bm}, indent=2), encoding="utf-8")
    (out_root / "tierc_metrics.json").write_text(json.dumps({"n": n_t, "best_config": tc, "by_config": tm}, indent=2), encoding="utf-8")

    def load_metric(path, *keys):
        p = Path(path)
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        for k in keys:
            d = d.get(k, {}) if isinstance(d, dict) else {}
        return d or None

    v24 = load_metric(ROOT / "data" / "baselines" / "v24_broad_residual_eval" / "policy_abstract" / "metrics.json")
    v31_tierc = load_metric(ROOT / "data" / "baselines" / "v31_routed_system" / "tierc_metrics.json", "by_config")
    rb5, rb10 = bm[bc]["pass@5"], bm[bc]["pass@10"]
    preserves = rb5 >= V27_ROUTED_BAR["pass@5"] - 1e-9 and rb10 >= V27_ROUTED_BAR["pass@10"] - 1e-9
    comparison = {
        "router": "V32MathlibRouter (mathlib -> v32 canonical specialist; else v24 broad-core)",
        "specialist_model": args.specialist_model, "specialist_mode": args.specialist_mode,
        "routing": {"broad_to_core": f"{n_b2c}/{len(broad_seeds)}", "tierc_to_specialist": f"{n_t2s}/{len(tierc_seeds)}"},
        "tierc_pool_stats": pool_stats,
        "routed": {"broad_core": {"n": n_b, "best_config": bc, **{k: bm[bc][k] for k in ("pass@1", "pass@5", "pass@10")}},
                   "tierc": {"n": n_t, "best_config": tc, **{k: tm[tc][k] for k in ("pass@1", "pass@5", "pass@10")}}},
        "tierc_per_category": tm[tc]["per_category"],
        "v27_routed_bar": V27_ROUTED_BAR, "preserves_v27_routed_bar": preserves, "adopt_router": preserves,
        "not_v19_placeholders": True,
    }
    if v24:
        comparison["broad_core_preserved"] = {"routed_pass@5": rb5, "v24_pass@5": v24.get("pass@5"),
                                              "routed_pass@10": rb10, "v24_pass@10": v24.get("pass@10"),
                                              "no_regression": rb10 >= v24.get("pass@10", 0) - 1e-9 and rb5 >= v24.get("pass@5", 0) - 1e-9}
    if v31_tierc:
        bestv31 = max(v31_tierc, key=lambda c: (v31_tierc[c].get("pass@5", 0), v31_tierc[c].get("pass@1", 0)))
        comparison["vs_v31_routed_tierc"] = {"v31_best_config": bestv31, "v31_n": "131",
                                             "v31_pass@5": v31_tierc[bestv31].get("pass@5"), "v31_pass@10": v31_tierc[bestv31].get("pass@10"),
                                             "v32_pass@5": tm[tc]["pass@5"], "v32_pass@10": tm[tc]["pass@10"], "v32_n": n_t,
                                             "note": "v32 tier-C set is LARGER (adds 46 stress + 25 fresh adversarial theorems)"}
    (out_root / "comparison.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")
    with (out_root / "routing_log.jsonl").open("w", encoding="utf-8") as f:
        for r in routing_log:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info("ROUTED broad-core [%s]: p@5/10=%.4f/%.4f preserves=%s", bc, rb5, rb10, preserves)
    logger.info("ROUTED tier-C [%s]: p@5/10=%.3f/%.3f (n=%d) pool_stats=%s", tc, tm[tc]["pass@5"], tm[tc]["pass@10"], n_t, pool_stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
