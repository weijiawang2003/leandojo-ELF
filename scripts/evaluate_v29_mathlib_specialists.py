"""Mini-ELF v29 — Part 7: evaluate Mathlib specialists (v27/v28/v29) on the tier-C
benchmarks + the v29 density-contrast holdouts, with the TRUSTED verifier.

Same candidate-pool + rerank machinery as the v25..v28 eval (token-seq2seq beams +
literal-adapt compose + raw/rule/learned/policy/abstract/policy_abstract orderings,
failure taxonomy); every candidate verified with
`mini_elf_lean.mathlib_batched_verifier.TrustedMathlibVerifier` (sound & complete),
one global verification pass shared across all (model, bench) cells.

Cell sets:
  * **main matrix** — v27/v28/v29 configs on
    v25 / v26 / v27 / v28 theorem-holdouts + v29 theorem-holdout +
    **family_density_holdout** (dense families) + **low_density_holdout** (sparse) —
    the same v29_general model on the last two is the density-law contrast;
  * **category transfer** — each v29 category-holdout model on ITS held-out category
    (set/finset/order), leak-free.

Adds per-FAMILY pass@k (from the seed's theorem_family) on top of per-category, so
Part 9 can read the density law per family. Real `import Mathlib` typecheck, no
state_after, manual targets never fed to a model as predictions, v24 untouched.
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
from audit_v29_family_density import name_stem  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v29_mathlib_specialists")
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"
MODELS = ROOT / "data" / "models"
V29 = ROOT / "data" / "processed" / "v29_mathlib_specialist"
V28 = ROOT / "data" / "processed" / "v28_mathlib_specialist"
V27 = ROOT / "data" / "processed" / "v27_mathlib_specialist"
V26TH = ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout"


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _family(seed: Dict[str, Any]) -> str:
    fam = (seed.get("theorem_family") or "").strip()
    cat = seed.get("category", "?")
    if fam:
        return f"{cat}::{fam}"
    return f"{cat}::{name_stem(seed.get('theorem_name',''))}"


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


def default_main_models() -> List[Tuple[str, str]]:
    cands = [
        ("v27_widened", MODELS / "token_seq2seq_v27_widened"),
        ("v28_general", MODELS / "token_seq2seq_v28_general"),
        ("v28_finset_specialist", MODELS / "token_seq2seq_v28_finset_specialist"),
        ("v29_general", MODELS / "token_seq2seq_v29_general"),
        ("v29_v28best_plus", MODELS / "token_seq2seq_v29_v28best_plus"),
        ("v29_set_finset_order_heavy", MODELS / "token_seq2seq_v29_set_finset_order_heavy"),
        ("v29_category_balanced", MODELS / "token_seq2seq_v29_category_balanced"),
        ("v29_function_order", MODELS / "token_seq2seq_v29_function_order"),
        ("v29_large", MODELS / "token_seq2seq_v29_large"),
    ]
    return [(lbl, str(d)) for lbl, d in cands if d.exists()]


def default_main_benches() -> List[Tuple[str, str]]:
    cands = [
        ("v25_heldout", ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"),
        ("v26_holdout", V26TH / "test_seeds.jsonl"),
        ("v27_holdout", V27 / "theorem_holdout" / "test_seeds.jsonl"),
        ("v28_holdout", V28 / "theorem_holdout" / "test_seeds.jsonl"),
        ("v29_holdout", V29 / "theorem_holdout" / "test_seeds.jsonl"),
        ("family_density_holdout", V29 / "family_density_holdout" / "test_seeds.jsonl"),
        ("low_density_holdout", V29 / "low_density_holdout" / "test_seeds.jsonl"),
    ]
    return [(lbl, str(p)) for lbl, p in cands if p.exists()]


def default_transfer_cells() -> List[Tuple[str, str, str]]:
    cands = [
        ("v29_set_holdout", MODELS / "token_seq2seq_v29_set_holdout", V29 / "category_holdout_set" / "test_seeds.jsonl"),
        ("v29_finset_holdout", MODELS / "token_seq2seq_v29_finset_holdout", V29 / "category_holdout_finset" / "test_seeds.jsonl"),
        ("v29_order_holdout", MODELS / "token_seq2seq_v29_order_holdout", V29 / "category_holdout_order" / "test_seeds.jsonl"),
    ]
    return [(lbl, str(d), str(s)) for lbl, d, s in cands if d.exists() and s.exists()]


def score_cell(seeds, model, rr, learned, k_max, vmap):
    n = len(seeds)
    per_pass = {c: {1: 0, 5: 0, 10: 0} for c in CONFIGS}
    per_first = {c: [] for c in CONFIGS}
    per_cat = {c: {} for c in CONFIGS}
    per_fam = {c: {} for c in CONFIGS}
    per_tax = {c: {} for c in CONFIGS}
    no_verify = {c: {} for c in CONFIGS}
    records = {c: [] for c in CONFIGS}
    for nm, (seed, pool) in seeds.items():
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
            fc = per_fam[cfg].setdefault(fam, {"n": 0, "p1": 0, "p5": 0, "p10": 0})
            fc["n"] += 1; fc["p1"] += int(p1); fc["p5"] += int(p5); fc["p10"] += int(p10)
            records[cfg].append({"theorem_name": nm, "category": cat, "family": fam, "config": cfg,
                                 "ordering": [r.candidate for r in reordered], "verifications": verifs,
                                 "pass@1": p1, "pass@5": p5, "pass@10": p10, "first_verified_rank": fr})
    cfg_metrics = {}
    detail = {}
    for cfg in CONFIGS:
        frs = [r for r in per_first[cfg] if r is not None]
        pc = {c: {"n": v["n"], "pass@1": v["p1"] / v["n"], "pass@5": v["p5"] / v["n"],
                  "pass@10": v["p10"] / v["n"]} for c, v in per_cat[cfg].items()}
        pf = {c: {"n": v["n"], "pass@1": v["p1"] / v["n"], "pass@5": v["p5"] / v["n"],
                  "pass@10": v["p10"] / v["n"]} for c, v in per_fam[cfg].items()}
        m = {"config": cfg, "n_test_theorems": n,
             "pass@1": per_pass[cfg][1] / n, "pass@5": per_pass[cfg][5] / n, "pass@10": per_pass[cfg][10] / n,
             "MRR": sum(1.0 / (r + 1) for r in frs) / n if n else 0.0,
             "n_no_candidate_verified": sum(1 for r in per_first[cfg] if r is None),
             "no_verify_reason": no_verify[cfg], "failure_taxonomy": per_tax[cfg],
             "per_category": pc, "per_family": pf,
             "mathlib": True, "uses_state_after": False, "uses_manual_oracle": False}
        detail[cfg] = (m, records[cfg])
        cfg_metrics[cfg] = {k: m[k] for k in ("pass@1", "pass@5", "pass@10", "MRR", "n_no_candidate_verified")}
    best_cfg = max(CONFIGS, key=lambda c: (cfg_metrics[c]["pass@5"], cfg_metrics[c]["pass@1"]))
    return cfg_metrics, best_cfg, detail, n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--pattern-bag-rows", default=str(ROOT / "data" / "processed" / "v24_broad_plus_residual" / "train_rows.jsonl"))
    ap.add_argument("--learned-reranker", default=str(ROOT / "data" / "models" / "v15_reranker" / "neg_imp_exfalso"))
    ap.add_argument("--out-root", default=str(ROOT / "data" / "baselines" / "v29_specialist_eval"))
    ap.add_argument("--k-max", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=300.0)
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    rr = AbstractPatternReranker(bag=build_pattern_bag(_read(Path(args.pattern_bag_rows))))
    learned = LearnedReranker.load(Path(args.learned_reranker))

    main_models = default_main_models()
    main_benches = default_main_benches()
    transfer = default_transfer_cells()
    logger.info("main: %d models x %d benches; transfer: %d cells",
                len(main_models), len(main_benches), len(transfer))

    loaded = {lbl: load_token_model(Path(d)) for lbl, d in main_models}
    for lbl, d, _s in transfer:
        loaded[lbl] = load_token_model(Path(d))
    bench_seeds = {bl: _read(Path(bp)) for bl, bp in main_benches}
    for _lbl, _d, sp in transfer:
        bench_seeds[sp] = _read(Path(sp))

    cells: List[Tuple[str, str, Dict[str, Any]]] = []
    work: Dict[Tuple[str, str], Tuple[str, str]] = {}

    def add_cell(ml, bl, seeds):
        model, vocab, mcfg = loaded[ml]
        d: Dict[str, Any] = {}
        for seed in seeds:
            nm = seed["theorem_name"]
            pool = build_pool(model, vocab, mcfg, seed["theorem_statement"], seed["state_before"], args.k_max)
            d[nm] = (seed, pool)
            for cand, _src in pool:
                work[(nm, cand)] = (seed["theorem_statement"], cand)
        cells.append((ml, bl, d))

    for ml, _d in main_models:
        for bl, _bp in main_benches:
            add_cell(ml, bl, bench_seeds[bl])
    for ml, _d, sp in transfer:
        add_cell(ml, Path(sp).parent.name, bench_seeds[sp])

    verifier = TrustedMathlibVerifier(scratch, lean_path=lean_path, timeout=args.timeout)
    if not verifier.warmup():
        logger.error("Mathlib warmup failed"); return 2
    items = [(nm, stmt, cand) for (nm, cand), (stmt, _c) in work.items()]
    logger.info("verifying %d unique (theorem,candidate) pairs ...", len(items))
    verdicts = verifier.verify_many(items, confirm=True)
    vmap = {(v.theorem_name, v.tactic): {"success": v.success, "error": v.error} for v in verdicts}
    logger.info("verified %d pairs in %d lean invocations (%.1fs)",
                len(vmap), verifier.n_invocations, verifier.total_lean_seconds)

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    comparison: Dict[str, Any] = {"verifier": "TrustedMathlibVerifier", "results": {}, "transfer": {}}
    for ml, bl, seeds_pools in cells:
        cfg_metrics, best_cfg, detail, n = score_cell(seeds_pools, loaded[ml], rr, learned, args.k_max, vmap)
        run_dir = out_root / f"{ml}__{bl}"
        for cfg in CONFIGS:
            d = run_dir / cfg
            d.mkdir(parents=True, exist_ok=True)
            m, records = detail[cfg]
            (d / "metrics.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
            with (d / "predictions.jsonl").open("w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        entry = {"n_test_theorems": n, "best_config": best_cfg, "best": cfg_metrics[best_cfg],
                 "raw": cfg_metrics["raw"], "by_config": cfg_metrics}
        bucket = comparison["transfer"] if ml.endswith("_holdout") else comparison["results"]
        bucket[f"{ml}__{bl}"] = entry
        logger.info("  %-28s @ %-22s best=%-15s p@1/5/10=%.3f/%.3f/%.3f noverify=%d",
                    ml, bl, best_cfg, cfg_metrics[best_cfg]["pass@1"], cfg_metrics[best_cfg]["pass@5"],
                    cfg_metrics[best_cfg]["pass@10"], cfg_metrics[best_cfg]["n_no_candidate_verified"])
    (out_root / "comparison.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("V29 specialist eval DONE -> %s", out_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
