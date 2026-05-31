"""Mini-ELF v27 — Part 7b: evaluate the v27 routed system + broad-core preservation.

Routing (the v26 `MathlibRouter`, an engineering switch — no theorem-specific
cheating):

    Mathlib-env theorem (import Mathlib / mathlib flag) -> best v27 specialist + Mathlib verifier
    core-env theorem    (no Mathlib import)             -> v24 broad-core      + core verifier

Verifies broad-core with the TRUSTED core verifier and tier-C with the TRUSTED
Mathlib verifier, then checks that **routed broad-core == v24 broad-core** (no
v25-style cannibalization, since the v24 model is untouched) and reports the
routed tier-C numbers. Builds a comparison vs v24/v25_aug everywhere.

Honesty: real Lean (core + import Mathlib), no state_after, no manual oracle, v24
model untouched, router is a generator switch.
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
from mini_elf_lean.v26_mathlib_router import BROAD_CORE, MATHLIB_SPECIALIST, MathlibRouter  # noqa: E402
from evaluate_v26_specialist import build_pool  # noqa: E402
from evaluate_v25_tierc import (  # noqa: E402
    CONFIGS, _first_rank, _order_abstract, _order_learned, _order_policy,
    _order_policy_abstract, _order_raw, _order_rule, _pass_at, _rows, v25_taxonomy,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v27_routed_system")
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"


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
    per_tax = {c: {} for c in CONFIGS}
    no_verify = {c: {} for c in CONFIGS}
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
            for v in verifs:
                if not v["success"]:
                    ec = v25_taxonomy(v.get("error"))
                    per_tax[cfg][ec] = per_tax[cfg].get(ec, 0) + 1
            p1, p5, p10 = _pass_at(verifs, 1), _pass_at(verifs, 5), _pass_at(verifs, 10)
            per_pass[cfg][1] += int(p1); per_pass[cfg][5] += int(p5); per_pass[cfg][10] += int(p10)
            fr = _first_rank(verifs); per_first[cfg].append(fr)
            if fr is None:
                cls = [v25_taxonomy(v.get("error")) for v in verifs] or ["no_schema"]
                no_verify[cfg][nm] = max(set(cls), key=cls.count)
            cc = per_cat[cfg].setdefault(cat, {"n": 0, "p1": 0, "p5": 0, "p10": 0})
            cc["n"] += 1; cc["p1"] += int(p1); cc["p5"] += int(p5); cc["p10"] += int(p10)
    out = {}
    for cfg in CONFIGS:
        frs = [r for r in per_first[cfg] if r is not None]
        out[cfg] = {"pass@1": per_pass[cfg][1] / n, "pass@5": per_pass[cfg][5] / n, "pass@10": per_pass[cfg][10] / n,
                    "MRR": sum(1.0 / (r + 1) for r in frs) / n if n else 0.0,
                    "n_no_candidate_verified": sum(1 for r in per_first[cfg] if r is None),
                    "per_category": {c: {"n": v["n"], "pass@1": v["p1"] / v["n"], "pass@5": v["p5"] / v["n"],
                                         "pass@10": v["p10"] / v["n"]} for c, v in per_cat[cfg].items()},
                    "failure_taxonomy": per_tax[cfg], "no_verify_reason": no_verify[cfg]}
    return out, n


def best_cfg(metrics):
    return max(CONFIGS, key=lambda c: (metrics[c]["pass@5"], metrics[c]["pass@1"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--broad-seeds", default=str(ROOT / "data" / "seeds" / "v18_broad_core_seeds.jsonl"))
    ap.add_argument("--tierc-seeds", action="append", default=None)
    ap.add_argument("--broad-model", default=str(ROOT / "data" / "models" / "token_seq2seq_v24_broad_residual"))
    ap.add_argument("--specialist-model", default=str(ROOT / "data" / "models" / "token_seq2seq_v27_widened"))
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--pattern-bag-rows", default=str(ROOT / "data" / "processed" / "v24_broad_plus_residual" / "train_rows.jsonl"))
    ap.add_argument("--learned-reranker", default=str(ROOT / "data" / "models" / "v15_reranker" / "neg_imp_exfalso"))
    ap.add_argument("--out-root", default=str(ROOT / "data" / "baselines" / "v27_routed_system"))
    ap.add_argument("--k-max", type=int, default=10)
    args = ap.parse_args(argv)

    tierc_paths = args.tierc_seeds or [
        str(ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"),
        str(ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout" / "test_seeds.jsonl"),
        str(ROOT / "data" / "processed" / "v27_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"),
    ]
    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    rr = AbstractPatternReranker(bag=build_pattern_bag(_read(Path(args.pattern_bag_rows))))
    learned = LearnedReranker.load(Path(args.learned_reranker))
    broad = load_token_model(Path(args.broad_model))
    specialist = load_token_model(Path(args.specialist_model))
    router = MathlibRouter(available={BROAD_CORE, MATHLIB_SPECIALIST})

    broad_seeds = _read(Path(args.broad_seeds))
    tierc_seeds: List[Dict[str, Any]] = []
    for tp in tierc_paths:
        tierc_seeds += _read(Path(tp))

    routing_log = []
    broad_pools, tierc_pools = [], []
    for seed in broad_seeds:
        key = router.route_seed(seed); routing_log.append({**router.explain(seed), "tier": "broad_core"})
        m = broad if key == BROAD_CORE else specialist
        broad_pools.append((seed, build_pool(*m, seed["theorem_statement"], seed["state_before"], args.k_max)))
    for seed in tierc_seeds:
        key = router.route_seed(seed); routing_log.append({**router.explain(seed), "tier": "tierc"})
        m = specialist if key == MATHLIB_SPECIALIST else broad
        tierc_pools.append((seed, build_pool(*m, seed["theorem_statement"], seed["state_before"], args.k_max)))
    n_broad_to_core = sum(1 for r in routing_log if r["tier"] == "broad_core" and r["chosen_model"] == BROAD_CORE)
    n_tierc_to_spec = sum(1 for r in routing_log if r["tier"] == "tierc" and r["chosen_model"] == MATHLIB_SPECIALIST)
    logger.info("routing: %d/%d broad->v24, %d/%d tierc->specialist",
                n_broad_to_core, len(broad_seeds), n_tierc_to_spec, len(tierc_seeds))

    # verify each tier with the trusted verifier (core vs import Mathlib)
    core_v = TrustedMathlibVerifier(scratch, core=True, timeout=120)
    items_b = list({(s["theorem_name"], c): (s["theorem_statement"], c)
                    for s, pool in broad_pools for c, _src in pool}.items())
    vb = core_v.verify_many([(nm, stmt, c) for (nm, c), (stmt, _c) in items_b], confirm=True)
    vmap_b = {(x.theorem_name, x.tactic): {"success": x.success, "error": x.error} for x in vb}

    mathlib_v = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=300)
    if not mathlib_v.warmup():
        logger.error("Mathlib warmup failed"); return 2
    items_t = list({(s["theorem_name"], c): (s["theorem_statement"], c)
                    for s, pool in tierc_pools for c, _src in pool}.items())
    vt = mathlib_v.verify_many([(nm, stmt, c) for (nm, c), (stmt, _c) in items_t], confirm=True)
    vmap_t = {(x.theorem_name, x.tactic): {"success": x.success, "error": x.error} for x in vt}
    logger.info("verified broad=%d (core %.1fs) tierc=%d (mathlib %.1fs)",
                len(vmap_b), core_v.total_lean_seconds, len(vmap_t), mathlib_v.total_lean_seconds)

    broad_metrics, n_b = score_tier(broad_pools, vmap_b, rr, learned, args.k_max)
    tierc_metrics, n_t = score_tier(tierc_pools, vmap_t, rr, learned, args.k_max)
    bc, tc = best_cfg(broad_metrics), best_cfg(tierc_metrics)

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "broad_core_metrics.json").write_text(
        json.dumps({"n": n_b, "best_config": bc, "by_config": broad_metrics}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_root / "tierc_metrics.json").write_text(
        json.dumps({"n": n_t, "best_config": tc, "by_config": tierc_metrics}, indent=2, ensure_ascii=False), encoding="utf-8")
    with (out_root / "routing_log.jsonl").open("w", encoding="utf-8") as f:
        for r in routing_log:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def load_metric(path, *keys):
        p = Path(path)
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        for k in keys:
            d = d.get(k, {}) if isinstance(d, dict) else {}
        return d or None

    v24_broad = load_metric(ROOT / "data" / "baselines" / "v24_broad_residual_eval" / "policy_abstract" / "metrics.json")
    v26_broad = load_metric(ROOT / "data" / "baselines" / "v26_routed_system" / "broad_core_metrics.json", "by_config", "policy_abstract")
    comparison = {
        "router": "MathlibRouter (imports/mathlib-flag -> v27 specialist; else v24 broad-core)",
        "specialist_model": args.specialist_model,
        "routing": {"broad_to_core": f"{n_broad_to_core}/{len(broad_seeds)}",
                    "tierc_to_specialist": f"{n_tierc_to_spec}/{len(tierc_seeds)}"},
        "routed": {
            "broad_core": {"n": n_b, "best_config": bc, **{k: broad_metrics[bc][k] for k in ("pass@1", "pass@5", "pass@10")}},
            "tierc": {"n": n_t, "best_config": tc, **{k: tierc_metrics[tc][k] for k in ("pass@1", "pass@5", "pass@10")}}},
    }
    if v24_broad:
        comparison["broad_core_preserved"] = {
            "routed_pass@5": broad_metrics[bc]["pass@5"], "v24_pass@5": v24_broad.get("pass@5"),
            "routed_pass@10": broad_metrics[bc]["pass@10"], "v24_pass@10": v24_broad.get("pass@10"),
            "no_regression": broad_metrics[bc]["pass@10"] >= v24_broad.get("pass@10", 0) - 1e-9
                             and broad_metrics[bc]["pass@5"] >= v24_broad.get("pass@5", 0) - 1e-9}
    if v26_broad:
        comparison["vs_v26_routed_broad"] = {"v26_pass@5": v26_broad.get("pass@5"), "v26_pass@10": v26_broad.get("pass@10")}
    (out_root / "comparison.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("ROUTED broad-core [%s]: p@1/5/10=%.3f/%.3f/%.3f", bc,
                broad_metrics[bc]["pass@1"], broad_metrics[bc]["pass@5"], broad_metrics[bc]["pass@10"])
    logger.info("ROUTED tier-C   [%s]: p@1/5/10=%.3f/%.3f/%.3f", tc,
                tierc_metrics[tc]["pass@1"], tierc_metrics[tc]["pass@5"], tierc_metrics[tc]["pass@10"])
    if "broad_core_preserved" in comparison:
        logger.info("BROAD-CORE PRESERVED: %s", comparison["broad_core_preserved"]["no_regression"])
    logger.info("V27 routed-system eval DONE -> %s", out_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
