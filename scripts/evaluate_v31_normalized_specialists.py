"""Mini-ELF v31 — Part 6: evaluate normalized specialists on token-diversity + standard
holdouts, with the TRUSTED verifier.

Models & modes:
  * raw         — generate candidates from the raw (statement, state) [v30 baseline; B]
  * canonical   — canonicalize the input, decode with the canonical model, then
                  `concretize_or_reject` each candidate and **union with the raw v30
                  pool** (raw fallback). Rejected (unresolved canonical) candidates are
                  counted and dropped before verification.
  * mixture     — raw candidates from the mixture model PLUS concretized candidates from
                  feeding it the canonical input; union.

This guarantees the canonical/mixture pools can only **add** coverage over raw v30
(the v19 failure mode — replacing raw with un-resolvable abstractions — cannot occur).
One global TrustedMathlibVerifier pass. Tracks unresolved-canonical / concretization-
failure / raw-fallback-usage counts. Per-family + per-category pass@k. Real
`import Mathlib`; no `state_after`; no manual oracle; v24 untouched.
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
from mini_elf_lean.v31_identifier_normalization import build_canonical_map, canonicalize_text, concretize_or_reject  # noqa: E402
from evaluate_v26_specialist import build_pool  # noqa: E402
from evaluate_v25_tierc import (  # noqa: E402
    CONFIGS, _first_rank, _order_abstract, _order_learned, _order_policy,
    _order_policy_abstract, _order_raw, _order_rule, _pass_at, _rows, v25_taxonomy,
)
from audit_v29_family_density import name_stem  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v31_normalized_specialists")
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"
MODELS = ROOT / "data" / "models"
P = ROOT / "data" / "processed"


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _family(seed):
    fam = (seed.get("theorem_family") or "").strip()
    cat = seed.get("category", "?")
    return f"{cat}::{fam}" if fam else f"{cat}::{name_stem(seed.get('theorem_name',''))}"


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


def models_present() -> List[Tuple[str, str, str]]:
    """(label, dir, mode)."""
    cands = [
        ("v30_general_targeted", MODELS / "token_seq2seq_v30_general_targeted", "raw"),
        ("v31_raw_plus_projection_aug", MODELS / "token_seq2seq_v31_raw_plus_projection_aug", "raw"),
        ("v31_canonical_general", MODELS / "token_seq2seq_v31_canonical_general", "canonical"),
        ("v31_raw_canonical_mixture", MODELS / "token_seq2seq_v31_raw_canonical_mixture", "mixture"),
    ]
    return [(lbl, str(d), mode) for lbl, d, mode in cands if d.exists()]


def benches() -> List[Tuple[str, str]]:
    cands = [
        ("v25_heldout", ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"),
        ("v26_holdout", P / "v26_mathlib_specialist_splits" / "theorem_holdout" / "test_seeds.jsonl"),
        ("v27_holdout", P / "v27_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"),
        ("v28_holdout", P / "v28_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"),
        ("v29_holdout", P / "v29_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"),
        ("v30_targeted_family", P / "v30_mathlib_specialist" / "targeted_family_holdout" / "test_seeds.jsonl"),
        ("token_diversity", P / "v31_canonical_mathlib" / "token_diversity_holdout" / "test_seeds.jsonl"),
    ]
    return [(lbl, str(p)) for lbl, p in cands if p.exists()]


def build_pool_for(mode, model_tuple, raw_fallback, stmt, state, k):
    """Return (pool, stats). pool is a list of (candidate, source). stats tracks
    unresolved-canonical rejections, concretization usage and raw fallback usage."""
    model, vocab, mcfg = model_tuple
    stats = {"n_canonical_generated": 0, "n_unresolved_rejected": 0,
             "n_from_canonical": 0, "n_from_raw_fallback": 0}
    seen = set()
    pool: List[Tuple[str, str]] = []

    def add(cand, src):
        c = cand.strip()
        if not c or c in seen:
            return
        seen.add(c); pool.append((c, src))

    if mode in ("canonical", "mixture"):
        cmap = build_canonical_map(stmt, state)
        if cmap.ok:
            cpool = build_pool(model, vocab, mcfg, canonicalize_text(stmt, cmap), canonicalize_text(state, cmap), k)
            for cand, _src in cpool:
                stats["n_canonical_generated"] += 1
                real = concretize_or_reject(cand, cmap)
                if real is None:
                    stats["n_unresolved_rejected"] += 1
                    continue
                if real.strip() not in seen:
                    stats["n_from_canonical"] += 1
                add(real, "canonical")
    if mode in ("raw", "mixture"):
        rp = build_pool(model, vocab, mcfg, stmt, state, k)
        for cand, _src in rp:
            add(cand, "raw_model")
    # raw v30 fallback always unioned for canonical/mixture (guarantees >= v30 coverage)
    if mode in ("canonical", "mixture") and raw_fallback is not None:
        rm, rv, rc = raw_fallback
        for cand, _src in build_pool(rm, rv, rc, stmt, state, k):
            before = len(seen)
            add(cand, "raw_fallback")
            if len(seen) > before:
                stats["n_from_raw_fallback"] += 1
    return pool[:max(k, len(pool))], stats


def score_cell(seeds_pools, k_max, vmap, rr, learned):
    n = len(seeds_pools)
    per_pass = {c: {1: 0, 5: 0, 10: 0} for c in CONFIGS}
    per_first = {c: [] for c in CONFIGS}
    per_cat = {c: {} for c in CONFIGS}
    per_fam = {c: {} for c in CONFIGS}
    no_verify = {c: {} for c in CONFIGS}
    records = {c: [] for c in CONFIGS}
    for nm, (seed, pool, _stats) in seeds_pools.items():
        stmt, state = seed["theorem_statement"], seed["state_before"]
        cat = seed.get("category", "unknown")
        fam = _family(seed)
        op = seed.get("required_operation", seed.get("expected_skill", "unknown"))
        rows = _rows(pool, nm=nm, stmt=stmt, state=state, op=op)
        for cfg in CONFIGS:
            order = _order_for(cfg, rows, rr, learned, cat)
            reordered = [rows[j] for j in order][:k_max]
            verifs = [{"success": vmap.get((nm, r.candidate), {}).get("success", False),
                       "error": vmap.get((nm, r.candidate), {}).get("error")} for r in reordered]
            p1, p5, p10 = _pass_at(verifs, 1), _pass_at(verifs, 5), _pass_at(verifs, 10)
            per_pass[cfg][1] += int(p1); per_pass[cfg][5] += int(p5); per_pass[cfg][10] += int(p10)
            fr = _first_rank(verifs); per_first[cfg].append(fr)
            if fr is None:
                cls = [v25_taxonomy(v.get("error")) for v in verifs] or ["no_schema"]
                no_verify[cfg][nm] = max(set(cls), key=cls.count)
            for store, key in ((per_cat, cat), (per_fam, fam)):
                cc = store[cfg].setdefault(key, {"n": 0, "p1": 0, "p5": 0, "p10": 0})
                cc["n"] += 1; cc["p1"] += int(p1); cc["p5"] += int(p5); cc["p10"] += int(p10)
            records[cfg].append({"theorem_name": nm, "category": cat, "family": fam, "config": cfg,
                                 "ordering": [r.candidate for r in reordered], "verifications": verifs,
                                 "pass@1": p1, "pass@5": p5, "pass@10": p10, "first_verified_rank": fr})
    cfg_metrics, detail = {}, {}
    for cfg in CONFIGS:
        frs = [r for r in per_first[cfg] if r is not None]
        m = {"config": cfg, "n_test_theorems": n,
             "pass@1": per_pass[cfg][1] / n, "pass@5": per_pass[cfg][5] / n, "pass@10": per_pass[cfg][10] / n,
             "MRR": sum(1.0 / (r + 1) for r in frs) / n if n else 0.0,
             "n_no_candidate_verified": sum(1 for r in per_first[cfg] if r is None),
             "no_verify_reason": no_verify[cfg],
             "per_category": {c: {"n": v["n"], "pass@10": v["p10"] / v["n"]} for c, v in per_cat[cfg].items()},
             "per_family": {c: {"n": v["n"], "pass@10": v["p10"] / v["n"]} for c, v in per_fam[cfg].items()}}
        detail[cfg] = (m, records[cfg])
        cfg_metrics[cfg] = {k: m[k] for k in ("pass@1", "pass@5", "pass@10", "MRR", "n_no_candidate_verified")}
    best = max(CONFIGS, key=lambda c: (cfg_metrics[c]["pass@5"], cfg_metrics[c]["pass@1"]))
    return cfg_metrics, best, detail, n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--pattern-bag-rows", default=str(ROOT / "data" / "processed" / "v24_broad_plus_residual" / "train_rows.jsonl"))
    ap.add_argument("--learned-reranker", default=str(ROOT / "data" / "models" / "v15_reranker" / "neg_imp_exfalso"))
    ap.add_argument("--out-root", default=str(ROOT / "data" / "baselines" / "v31_normalized_eval"))
    ap.add_argument("--k-max", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=300.0)
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    rr = AbstractPatternReranker(bag=build_pattern_bag(_read(Path(args.pattern_bag_rows))))
    learned = LearnedReranker.load(Path(args.learned_reranker))

    ms = models_present()
    bs = benches()
    logger.info("v31 eval: %d models x %d benches", len(ms), len(bs))
    loaded = {lbl: load_token_model(Path(d)) for lbl, d, _m in ms}
    raw_fallback = loaded.get("v30_general_targeted")  # the always-present raw floor
    bench_seeds = {bl: _read(Path(bp)) for bl, bp in bs}

    cells, work = [], {}
    cell_stats: Dict[str, Dict[str, int]] = {}
    for lbl, _d, mode in ms:
        for bl, _bp in bs:
            d = {}
            agg = {"n_canonical_generated": 0, "n_unresolved_rejected": 0, "n_from_canonical": 0, "n_from_raw_fallback": 0}
            for seed in bench_seeds[bl]:
                nm = seed["theorem_name"]
                pool, stats = build_pool_for(mode, loaded[lbl], raw_fallback, seed["theorem_statement"], seed["state_before"], args.k_max)
                d[nm] = (seed, pool, stats)
                for kk in agg:
                    agg[kk] += stats[kk]
                for cand, _src in pool:
                    work[(nm, cand)] = (seed["theorem_statement"], cand)
            cells.append((lbl, bl, d))
            cell_stats[f"{lbl}__{bl}"] = agg

    verifier = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=args.timeout)
    if not verifier.warmup():
        logger.error("warmup failed"); return 2
    items = [(nm, stmt, cand) for (nm, cand), (stmt, _c) in work.items()]
    logger.info("verifying %d unique pairs ...", len(items))
    verdicts = verifier.verify_many(items, confirm=True)
    vmap = {(v.theorem_name, v.tactic): {"success": v.success, "error": v.error} for v in verdicts}
    logger.info("verified %d pairs in %d invocations (%.1fs)", len(vmap), verifier.n_invocations, verifier.total_lean_seconds)

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    comparison = {"verifier": "TrustedMathlibVerifier", "results": {}, "pool_stats": cell_stats,
                  "not_v19_placeholders": True}
    for lbl, bl, seeds_pools in cells:
        cfg_metrics, best, detail, n = score_cell(seeds_pools, args.k_max, vmap, rr, learned)
        run_dir = out_root / f"{lbl}__{bl}"
        for cfg in CONFIGS:
            dd = run_dir / cfg
            dd.mkdir(parents=True, exist_ok=True)
            m, records = detail[cfg]
            (dd / "metrics.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
            with (dd / "predictions.jsonl").open("w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        comparison["results"][f"{lbl}__{bl}"] = {"n_test_theorems": n, "best_config": best,
                                                 "best": cfg_metrics[best], "by_config": cfg_metrics,
                                                 "pool_stats": cell_stats[f"{lbl}__{bl}"]}
        st = cell_stats[f"{lbl}__{bl}"]
        logger.info("  %-30s @ %-18s best p@10=%.3f noverify=%d  canon_gen=%d rejected=%d from_canon=%d",
                    lbl, bl, cfg_metrics[best]["pass@10"], cfg_metrics[best]["n_no_candidate_verified"],
                    st["n_canonical_generated"], st["n_unresolved_rejected"], st["n_from_canonical"])
    (out_root / "comparison.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("V31 normalized eval DONE -> %s", out_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
