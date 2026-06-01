"""Mini-ELF v33 — Part 6: evaluate v31/v32/v33 canonical specialists.

Reuses the v31 canonical-aware pool builder (canonicalize → decode → concretize-or-reject
→ union raw v30 fallback). Benches: prior held-outs + v32 identifier-stress + v33 fresh
robustness (which contain the 11 v32 residuals). One global TrustedMathlibVerifier pass.
Tracks pass@k, residual count, unresolved/concretization, per-family/category.
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
from evaluate_v31_normalized_specialists import build_pool_for, score_cell  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v33_mathlib_specialists")
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"
MODELS = ROOT / "data" / "models"
P = ROOT / "data" / "processed"


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def models_present() -> List[Tuple[str, str, str]]:
    cands = [
        ("v31_canonical_general", MODELS / "token_seq2seq_v31_canonical_general", "canonical"),
        ("v32_canonical_repaired", MODELS / "token_seq2seq_v32_canonical_repaired", "canonical"),
        ("v33_general_residual", MODELS / "token_seq2seq_v33_general_residual", "canonical"),
        ("v33_general_residual_stress", MODELS / "token_seq2seq_v33_general_residual_stress", "canonical"),
        ("v33_residual_only", MODELS / "token_seq2seq_v33_residual_only", "canonical"),
    ]
    return [(lbl, str(d), mode) for lbl, d, mode in cands if d.exists()]


def benches() -> List[Tuple[str, str]]:
    cands = [
        ("v25_heldout", ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"),
        ("v28_holdout", P / "v28_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"),
        ("v29_holdout", P / "v29_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"),
        ("token_diversity", P / "v31_canonical_mathlib" / "token_diversity_holdout" / "test_seeds.jsonl"),
        ("identifier_stress", ROOT / "data" / "seeds" / "v32_identifier_stress_seeds.jsonl"),
        ("fresh_robustness", ROOT / "data" / "seeds" / "v33_fresh_robustness_holdout_seeds.jsonl"),
    ]
    return [(lbl, str(p)) for lbl, p in cands if p.exists()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--pattern-bag-rows", default=str(ROOT / "data" / "processed" / "v24_broad_plus_residual" / "train_rows.jsonl"))
    ap.add_argument("--learned-reranker", default=str(ROOT / "data" / "models" / "v15_reranker" / "neg_imp_exfalso"))
    ap.add_argument("--out-root", default=str(ROOT / "data" / "baselines" / "v33_specialist_eval"))
    ap.add_argument("--k-max", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=300.0)
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    rr = AbstractPatternReranker(bag=build_pattern_bag(_read(Path(args.pattern_bag_rows))))
    learned = LearnedReranker.load(Path(args.learned_reranker))
    ms = models_present()
    bs = benches()
    logger.info("v33 eval: %d models x %d benches", len(ms), len(bs))
    loaded = {lbl: load_token_model(Path(d)) for lbl, d, _m in ms}
    raw_fallback = load_token_model(MODELS / "token_seq2seq_v30_general_targeted")
    bench_seeds = {bl: _read(Path(bp)) for bl, bp in bs}

    cells, work, cell_stats = [], {}, {}
    for lbl, _d, mode in ms:
        for bl, _bp in bs:
            d, agg = {}, {"n_canonical_generated": 0, "n_unresolved_rejected": 0, "n_from_canonical": 0, "n_from_raw_fallback": 0}
            for seed in bench_seeds[bl]:
                nm = seed["theorem_name"]
                pool, stats = build_pool_for(mode, loaded[lbl], raw_fallback, seed["theorem_statement"], seed["state_before"], args.k_max)
                d[nm] = (seed, pool, stats)
                for kk in agg:
                    agg[kk] += stats[kk]
                for cand, _src in pool:
                    work[(nm, cand)] = (seed["theorem_statement"], cand)
            cells.append((lbl, bl, d)); cell_stats[f"{lbl}__{bl}"] = agg

    verifier = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=args.timeout)
    if not verifier.warmup():
        logger.error("warmup failed"); return 2
    items = [(nm, stmt, cand) for (nm, cand), (stmt, _c) in work.items()]
    logger.info("verifying %d unique pairs ...", len(items))
    verdicts = verifier.verify_many(items, confirm=True)
    vmap = {(v.theorem_name, v.tactic): {"success": v.success, "error": v.error} for v in verdicts}
    logger.info("verified %d pairs (%.1fs)", len(vmap), verifier.total_lean_seconds)

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    comparison = {"verifier": "TrustedMathlibVerifier", "results": {}, "pool_stats": cell_stats, "not_v19_placeholders": True}
    for lbl, bl, seeds_pools in cells:
        cfg_metrics, best, detail, n = score_cell(seeds_pools, args.k_max, vmap, rr, learned)
        run_dir = out_root / f"{lbl}__{bl}"
        for cfg in ("raw", "abstract", "policy_abstract", "learned"):
            if cfg in detail:
                dd = run_dir / cfg
                dd.mkdir(parents=True, exist_ok=True)
                m, records = detail[cfg]
                (dd / "metrics.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
                with (dd / "predictions.jsonl").open("w", encoding="utf-8") as f:
                    for r in records:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
        comparison["results"][f"{lbl}__{bl}"] = {"n": n, "best_config": best, "best": cfg_metrics[best],
                                                 "by_config": cfg_metrics, "pool_stats": cell_stats[f"{lbl}__{bl}"]}
        st = cell_stats[f"{lbl}__{bl}"]
        logger.info("  %-30s @ %-18s best p@10=%.3f noverify=%d rejected=%d",
                    lbl, bl, cfg_metrics[best]["pass@10"], cfg_metrics[best]["n_no_candidate_verified"], st["n_unresolved_rejected"])
    (out_root / "comparison.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("V33 specialist eval DONE -> %s", out_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
