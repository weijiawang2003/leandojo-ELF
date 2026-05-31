"""Mini-ELF v23 — Parts 4/5/6: evaluate rerankers on the FIXED v22
plus_exists candidate pool (offline; no Lean — the pool's
``verifications`` are already recorded).

Rankers compared on the same 48-theorem pool:
  1. ``raw``              — v22 generator beam order (the bar).
  2. ``v22_abstract``     — v22 headline reranker (read from disk).
  3. ``v15_learned``      — old v15 reranker (read from disk).
  4. ``v23_plain``  (B)   — grounding + abstract-pattern LR, leave-one-
                            theorem-out (LOTO) so no held theorem leaks.
  5. ``v23_category`` (C) — B + category cues, LOTO.
  6. ``v23_hybrid`` (D)   — coarse-prob bucket of C with a raw beam-rank
                            tie-break: only reorders on a confident prob
                            gap, so it cannot demote a well-ranked raw
                            candidate on a near-tie.

Leakage control: when scoring theorem T, the LR is trained on every
pooled row whose ``theorem_name != T`` (across all source models) and
the pattern bag is rebuilt from those rows only.

Outputs ``data/baselines/v23_rerank_eval/metrics.json`` (+ per-ranker
per-category + demotion/promotion vs raw) and ``per_theorem.jsonl`` (for
the negation analysis and the generator-bound audit).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.abstract_pattern_reranker import PatternBag  # noqa: E402
from mini_elf_lean.learned_reranker import (  # noqa: E402
    FeatureIndex, TrainConfig, _sigmoid, vectorise,
)
from mini_elf_lean.v23_reranker_features import (  # noqa: E402
    _abstract_pattern, extract_v23_features,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v23_rerankers")

CATEGORIES = ["implication", "conjunction", "disjunction", "negation",
              "equality_rewrite", "exists", "forall", "nat_succ", "bool", "list"]


def _read(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def _set_bag_feats(feats: Dict[str, float], pattern: str, category: str,
                   bag: PatternBag) -> None:
    import math
    cnt = bag.lookup(pattern, category)
    cat_cnt = bag.by_category.get(category, {}).get(pattern, 0)
    feats["v23_abstract_pattern_logcount"] = math.log1p(cnt)
    feats["v23_abstract_pattern_seen"] = 1.0 if cnt > 0 else 0.0
    feats["v23_abstract_pattern_cat_match"] = 1.0 if cat_cnt > 0 else 0.0


def _train_sgd(vecs: List[Dict[int, float]], ys: List[float], n_feat: int,
               cfg: TrainConfig) -> List[float]:
    import random
    rng = random.Random(cfg.seed)
    w = [0.0] * n_feat
    idxs = list(range(len(vecs)))
    pos_w = cfg.class_weight_positive
    for _ in range(cfg.epochs):
        rng.shuffle(idxs)
        for i in idxs:
            xi, yi = vecs[i], ys[i]
            z = sum(w[j] * v for j, v in xi.items())
            p = _sigmoid(z)
            err = p - yi
            cw = pos_w if yi == 1.0 else 1.0
            scale = cfg.lr * cw
            for j, v in xi.items():
                w[j] -= scale * err * v + cfg.lr * cfg.l2 * w[j]
    return w


def _pass_at(order: List[int], verifs: List[Dict[str, Any]], k: int) -> bool:
    return any(verifs[i].get("success") for i in order[:k])


def _first_rank(order: List[int], verifs: List[Dict[str, Any]]) -> Optional[int]:
    for pos, i in enumerate(order):
        if verifs[i].get("success"):
            return pos
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--rows", default=str(ROOT / "data" / "processed"
                                          / "v23_reranker_data" / "rows.jsonl"))
    ap.add_argument("--pool-eval", default="v22_general_plus_exists_eval")
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--out-root", default=str(ROOT / "data" / "baselines"
                                              / "v23_rerank_eval"))
    args = ap.parse_args(argv)
    cfg = TrainConfig(epochs=args.epochs)

    rows = _read(Path(args.rows))
    seeds = {r["theorem_name"]: r for r in
             _read(ROOT / "data" / "seeds" / "v18_broad_core_seeds.jsonl")}
    pool = _read(ROOT / "data" / "baselines" / args.pool_eval / "raw"
                 / "predictions.jsonl")

    # ---- precompute static (no-bag) features + pattern for each pooled row,
    #      for both toggles, keyed by id ----
    t0 = time.perf_counter()
    static_plain: List[Dict[str, float]] = []
    static_cat: List[Dict[str, float]] = []
    patterns: List[str] = []
    ys = [1.0 if r.get("verified") else 0.0 for r in rows]
    cats = [r.get("category", "") for r in rows]
    thms = [r.get("theorem_name", "") for r in rows]
    for r in rows:
        static_plain.append(extract_v23_features(
            r, pattern_bag=None, category_features=False, hashed_dim=cfg.hashed_dim))
        static_cat.append(extract_v23_features(
            r, pattern_bag=None, category_features=True, hashed_dim=cfg.hashed_dim))
        patterns.append(_abstract_pattern(r.get("state_before", ""),
                                          r.get("candidate", "")))
    logger.info("precomputed features for %d rows in %.1fs", len(rows),
                time.perf_counter() - t0)

    # pool candidate static features (compute per theorem at scoring time;
    # small). Build per-theorem pool descriptors.
    pool_desc = []
    for p in pool:
        nm = p["theorem_name"]
        state = seeds.get(nm, {}).get("state_before", "")
        op = p.get("required_operation")
        cand_rows = []
        for i, cand in enumerate(p["ordering"]):
            d = {"candidate": cand, "state_before": state,
                 "category": p.get("category", ""), "beam_rank": i,
                 "required_operation": op,
                 "candidate_source": (p["sources"][i] if i < len(p["sources"]) else "unknown"),
                 "theorem_name": nm, "verified": bool(p["verifications"][i].get("success"))}
            cand_rows.append({
                "row": d,
                "plain": extract_v23_features(d, pattern_bag=None,
                                              category_features=False, hashed_dim=cfg.hashed_dim),
                "cat": extract_v23_features(d, pattern_bag=None,
                                            category_features=True, hashed_dim=cfg.hashed_dim),
                "pattern": _abstract_pattern(state, cand)})
        pool_desc.append({"theorem": nm, "category": p.get("category", ""),
                          "verifs": p["verifications"], "ordering": p["ordering"],
                          "sources": p["sources"], "cands": cand_rows})

    # ---- LOTO over the pool theorems, for toggles plain(B) and cat(C) ----
    orders: Dict[str, Dict[str, List[int]]] = {"v23_plain": {}, "v23_category": {},
                                               "v23_hybrid": {}}
    cat_probs: Dict[str, List[float]] = {}
    for toggle, static_all, key in (("B", static_plain, "v23_plain"),
                                    ("C", static_cat, "v23_category")):
        tt = time.perf_counter()
        for pd in pool_desc:
            T = pd["theorem"]
            # bag from verified train rows (theorem != T)
            bag = PatternBag()
            train_mask = [i for i in range(len(rows)) if thms[i] != T]
            for i in train_mask:
                if ys[i]:
                    bag.add(patterns[i], cats[i])
            # build fold index + vectors
            index = FeatureIndex()
            vecs, yy = [], []
            for i in train_mask:
                f = dict(static_all[i])
                _set_bag_feats(f, patterns[i], cats[i], bag)
                vecs.append(vectorise(f, index, extend=True))
                yy.append(ys[i])
            w = _train_sgd(vecs, yy, len(index), cfg)
            # score pool candidates
            scored = []
            for j, c in enumerate(pd["cands"]):
                f = dict(c["plain"] if toggle == "B" else c["cat"])
                _set_bag_feats(f, c["pattern"], pd["category"], bag)
                x = vectorise(f, index, extend=False)
                z = sum(w[k] * v for k, v in x.items())
                scored.append((j, _sigmoid(z), j))
            order = [t[0] for t in sorted(scored, key=lambda t: (-t[1], t[2]))]
            orders[key][T] = order
            if toggle == "C":
                cat_probs[T] = [s[1] for s in sorted(scored, key=lambda t: t[0])]
        logger.info("LOTO %s done in %.1fs", key, time.perf_counter() - tt)

    # ---- hybrid (D): coarse prob bucket of C + raw beam-rank tie-break ----
    for pd in pool_desc:
        T = pd["theorem"]
        probs = cat_probs[T]
        scored = [(j, round(probs[j], 1), j) for j in range(len(pd["cands"]))]
        orders["v23_hybrid"][T] = [t[0] for t in sorted(scored, key=lambda t: (-t[1], t[2]))]

    # ---- metrics for the computed rankers ----
    def metrics_for(order_fn) -> Dict[str, Any]:
        p1 = p5 = p10 = 0
        mrr = 0.0
        per = {c: {"n": 0, "p1": 0, "p5": 0, "p10": 0} for c in CATEGORIES}
        nverify = 0
        for pd in pool_desc:
            order = order_fn(pd)
            verifs = pd["verifs"]
            a1, a5, a10 = (_pass_at(order, verifs, 1), _pass_at(order, verifs, 5),
                           _pass_at(order, verifs, 10))
            p1 += a1; p5 += a5; p10 += a10
            fr = _first_rank(order, verifs)
            if fr is None:
                nverify += 1
            else:
                mrr += 1.0 / (fr + 1)
            c = pd["category"]
            per[c]["n"] += 1; per[c]["p1"] += a1; per[c]["p5"] += a5; per[c]["p10"] += a10
        n = len(pool_desc)
        return {"pass@1": p1 / n, "pass@5": p5 / n, "pass@10": p10 / n,
                "MRR": mrr / n, "n_no_candidate_verified": nverify,
                "per_category": {c: {"n": v["n"],
                                     "pass@1": v["p1"] / v["n"] if v["n"] else 0,
                                     "pass@5": v["p5"] / v["n"] if v["n"] else 0,
                                     "pass@10": v["p10"] / v["n"] if v["n"] else 0}
                                 for c, v in per.items()}}

    raw_order = lambda pd: list(range(len(pd["cands"])))
    computed = {
        "raw": metrics_for(raw_order),
        "v23_plain": metrics_for(lambda pd: orders["v23_plain"][pd["theorem"]]),
        "v23_category": metrics_for(lambda pd: orders["v23_category"][pd["theorem"]]),
        "v23_hybrid": metrics_for(lambda pd: orders["v23_hybrid"][pd["theorem"]]),
    }

    # ---- demotion / promotion vs raw (top5 and top1) ----
    def demote_promote(order_fn) -> Dict[str, int]:
        dem5 = pro5 = dem1 = pro1 = 0
        for pd in pool_desc:
            v = pd["verifs"]
            raw = raw_order(pd)
            rr = order_fn(pd)
            raw5 = _pass_at(raw, v, 5); new5 = _pass_at(rr, v, 5)
            raw1 = _pass_at(raw, v, 1); new1 = _pass_at(rr, v, 1)
            if raw5 and not new5:
                dem5 += 1
            if new5 and not raw5:
                pro5 += 1
            if raw1 and not new1:
                dem1 += 1
            if new1 and not raw1:
                pro1 += 1
        return {"demotion@5": dem5, "promotion@5": pro5,
                "demotion@1": dem1, "promotion@1": pro1}

    dp = {k: demote_promote(lambda pd, key=k: orders[key][pd["theorem"]])
          for k in ("v23_plain", "v23_category", "v23_hybrid")}

    # ---- read baseline metrics already on disk (raw/abstract/learned) ----
    disk = {}
    for cfgname, label in (("abstract", "v22_abstract"), ("learned", "v15_learned"),
                           ("raw", "raw_ondisk")):
        p = ROOT / "data" / "baselines" / args.pool_eval / cfgname / "metrics.json"
        if p.exists():
            m = json.loads(p.read_text(encoding="utf-8"))
            disk[label] = {"pass@1": m["pass@1"], "pass@5": m["pass@5"],
                           "pass@10": m["pass@10"], "MRR": m.get("MRR"),
                           "n_no_candidate_verified": m.get("n_no_candidate_verified"),
                           "negation@5": m["per_category"]["negation"]["pass@5"]}

    out = {
        "pool": args.pool_eval, "n_theorems": len(pool_desc),
        "computed_rankers": computed,
        "on_disk_baselines": disk,
        "demotion_promotion_vs_raw": dp,
        "uses_state_after": False, "uses_manual_oracle": False,
        "leakage_control": "leave-one-theorem-out (LR + pattern bag exclude "
                           "the scored theorem's rows)",
    }
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "metrics.json").write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                           encoding="utf-8")

    # ---- per-theorem dump (negation analysis + generator-bound audit) ----
    with (out_root / "per_theorem.jsonl").open("w", encoding="utf-8") as f:
        for pd in pool_desc:
            v = pd["verifs"]
            raw = raw_order(pd)
            rec = {"theorem": pd["theorem"], "category": pd["category"],
                   "raw_first_verified_rank": _first_rank(raw, v),
                   "v23_category_first_verified_rank":
                       _first_rank(orders["v23_category"][pd["theorem"]], v),
                   "v23_hybrid_first_verified_rank":
                       _first_rank(orders["v23_hybrid"][pd["theorem"]], v),
                   "raw_top3": [pd["ordering"][i] for i in raw[:3]],
                   "v23_category_top3": [pd["ordering"][i]
                                         for i in orders["v23_category"][pd["theorem"]][:3]],
                   "n_candidates": len(pd["cands"]),
                   "any_verified": any(x.get("success") for x in v)}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    logger.info("=== v23 reranker eval (pool=%s) ===", args.pool_eval)
    for k, m in computed.items():
        logger.info("  %-13s p@1=%.3f p@5=%.3f p@10=%.3f MRR=%.3f noverify=%d neg@5=%.3f",
                    k, m["pass@1"], m["pass@5"], m["pass@10"], m["MRR"],
                    m["n_no_candidate_verified"], m["per_category"]["negation"]["pass@5"])
    for k, v in dp.items():
        logger.info("  %-13s %s", k, v)
    logger.info("wrote %s", out_root / "metrics.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
