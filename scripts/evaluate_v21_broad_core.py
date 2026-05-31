"""Mini-ELF v21 — Part 4: evaluate a v21 config on v18 broad-core.

Supports two modes:

  * **single model** (`--model-root DIR`) — configs A / B / D. Beams
    come from one token seq2seq, exactly like
    ``evaluate_v20_broad_core.py``.
  * **routed** (`--broad-root DIR --forall-root DIR`) — config C. For
    each theorem the :class:`ModelRouter` picks the broad model or the
    forall specialist by category/operation; beams come from the
    chosen model. The router decision is recorded per prediction.

Both modes then apply the same rerank configs (raw / policy /
abstract / policy_abstract) and the warm lean-cli verifier (shared
cache). Outputs land under ``--out-root/<config>/``.

No state_after, no manual oracle, no Mathlib. The router is a
generator-selection switch, not proof-template injection.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.abstract_pattern_reranker import (  # noqa: E402
    AbstractPatternReranker, build_pattern_bag,
)
from mini_elf_lean.baseline_eval import (  # noqa: E402
    VerificationCache, make_lean_cli_verifier,
)
from mini_elf_lean.learned_reranker import LearnedReranker  # noqa: E402
from mini_elf_lean.literal_aware_decode import (  # noqa: E402
    SOURCE_LITERAL_ADAPT, compose_candidates,
)
from mini_elf_lean.proof_block_reranker import rerank as rule_rerank_fn  # noqa: E402
from mini_elf_lean.rerank_dataset import CandidateRow, classify_error  # noqa: E402
from mini_elf_lean import v15_rerank_policy  # noqa: E402
from mini_elf_lean.v21_model_router import (  # noqa: E402
    BROAD_PLUS, FORALL_SPECIALIST, ModelRouter,
)
from mini_elf_lean.token_seq2seq import (  # noqa: E402
    load_token_model, predict_beams,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v21_broad_core")


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    out = []
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def _pass_at(verifs, k):
    return any(v.get("success") for v in verifs[:k])


def _first_rank(verifs):
    for i, v in enumerate(verifs):
        if v.get("success"):
            return i
    return None


def _rows(pool, *, nm, stmt, state, op):
    out = []
    for i, (t, src) in enumerate(pool):
        out.append(CandidateRow(
            theorem_name=nm, family=op or "unknown", required_operation=op,
            theorem_statement=stmt, state_before=state, candidate=t,
            candidate_source=src, beam_rank=i, verified=False,
            error_class="ok", source_run="v21_eval"))
    return out


def _order_raw(rows):
    a, la, o = [], [], []
    for i, r in enumerate(rows):
        if r.candidate_source == SOURCE_LITERAL_ADAPT:
            la.append(i)
        elif r.candidate_source.startswith("token_seq2seq"):
            a.append(i)
        else:
            o.append(i)
    for g in (a, la, o):
        g.sort(key=lambda i: rows[i].beam_rank)
    return a + la + o


def _order_rule(rows):
    if not rows:
        return []
    items = [(r.candidate, r.candidate_source) for r in rows]
    rer = rule_rerank_fn(items, state_before=rows[0].state_before,
                         required_operation=rows[0].required_operation)
    idx: Dict[str, List[int]] = {}
    for j, r in enumerate(rows):
        idx.setdefault(r.candidate, []).append(j)
    order = []
    for c in rer:
        js = idx.get(c.tactic, [])
        if js:
            order.append(js.pop(0))
    seen = set(order)
    order += [j for j in range(len(rows)) if j not in seen]
    return order


def _order_learned(model, rows):
    sc = [(i, model.score_row(r), r.beam_rank) for i, r in enumerate(rows)]
    sc.sort(key=lambda t: (-t[1], t[2]))
    return [t[0] for t in sc]


def _order_policy(model, rows):
    if not rows:
        return []
    return v15_rerank_policy.reorder(rows, model=model,
                                     state_before=rows[0].state_before,
                                     required_operation=rows[0].required_operation)


def _order_abstract(rr, rows, *, category):
    if not rows:
        return []
    return rr.order([r.candidate for r in rows],
                    state_before=rows[0].state_before, category=category)


def _order_policy_abstract(rr, model, rows, *, category):
    pol = _order_policy(model, rows)
    if not rows:
        return pol
    cands = [rows[i].candidate for i in pol]
    rer = rr.rerank(cands, state_before=rows[0].state_before, category=category)
    out, pos = [], {}
    for s in rer:
        c = s.candidate
        start = pos.get(c, 0)
        for j in range(start, len(cands)):
            if cands[j] == c:
                out.append(pol[j])
                pos[c] = j + 1
                break
    used = set(out)
    out += [k for k in pol if k not in used]
    return out


_V18_CAT_TO_OP = {
    "implication": "implication", "conjunction": "unknown",
    "disjunction": "unknown", "negation": "intro_negation",
    "equality_rewrite": "rewrite", "exists": "unknown",
    "forall": "instantiate_forall", "nat_succ": "rewrite",
    "bool": "bool_cases", "list": "rewrite",
}

CONFIGS = ("raw", "rule", "learned", "policy", "abstract", "policy_abstract")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--seeds", default=str(ROOT / "data" / "seeds"
                                           / "v18_broad_core_seeds.jsonl"))
    ap.add_argument("--model-root", default=None,
                    help="single-model mode (configs A/B/D)")
    ap.add_argument("--broad-root", default=None,
                    help="routed mode: broad model dir (config C)")
    ap.add_argument("--forall-root", default=None,
                    help="routed mode: forall specialist dir (config C)")
    ap.add_argument("--pattern-bag-rows", default=None,
                    help="train_rows.jsonl to build the abstract pattern bag "
                         "(defaults to the single model's training pool / "
                         "the broad model's pool)")
    ap.add_argument("--learned-reranker",
                    default=str(ROOT / "data" / "models" / "v15_reranker"
                                / "neg_imp_exfalso"))
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--cache", default=str(ROOT / "data" / "lean_cache"
                                           / "v21_eval_cache.json"))
    ap.add_argument("--verifier-timeout", type=float, default=60.0)
    ap.add_argument("--k-max", type=int, default=10)
    args = ap.parse_args(argv)

    seeds = _read_jsonl(Path(args.seeds))
    routed = bool(args.broad_root and args.forall_root)
    models: Dict[str, Tuple[Any, Any, Any]] = {}
    if routed:
        models[BROAD_PLUS] = load_token_model(Path(args.broad_root))
        models[FORALL_SPECIALIST] = load_token_model(Path(args.forall_root))
        router = ModelRouter(available=set(models.keys()))
        logger.info("routed mode: broad=%s forall=%s",
                    args.broad_root, args.forall_root)
        pat_rows_path = args.pattern_bag_rows or str(
            Path(args.broad_root).parent.parent / "processed"
            / "v20_broad_synthetic_plus" / "train_rows.jsonl")
    else:
        assert args.model_root, "need --model-root or --broad/--forall-root"
        models[BROAD_PLUS] = load_token_model(Path(args.model_root))
        router = ModelRouter(available={BROAD_PLUS})
        logger.info("single-model mode: %s", args.model_root)
        pat_rows_path = args.pattern_bag_rows

    # Pattern bag for abstract reranker.
    bag_rows = _read_jsonl(Path(pat_rows_path)) if pat_rows_path else []
    bag = build_pattern_bag(bag_rows)
    rr = AbstractPatternReranker(bag=bag)
    logger.info("pattern bag: %d rows, %d patterns", bag.n_rows,
                len(bag.global_counts))

    learned = LearnedReranker.load(Path(args.learned_reranker))
    cache = VerificationCache.load(Path(args.cache), enabled=True)
    verifier = make_lean_cli_verifier(timeout=args.verifier_timeout)
    wu = verifier("__v21_warmup__", "(x : Nat) : x = x", "rfl")
    logger.info("warmup success=%s", wu.get("success"))

    per_records = {c: [] for c in CONFIGS}
    per_pass = {c: {1: 0, 5: 0, 10: 0} for c in CONFIGS}
    per_first = {c: [] for c in CONFIGS}
    per_tax = {c: {} for c in CONFIGS}
    per_cat = {c: {} for c in CONFIGS}
    per_malformed = {c: 0 for c in CONFIGS}

    for seed in seeds:
        nm, stmt, state = seed["theorem_name"], seed["theorem_statement"], seed["state_before"]
        category = seed["category"]
        op = _V18_CAT_TO_OP.get(category, "unknown")
        mk = router.route(category=category, required_operation=op)
        model, vocab, mcfg = models[mk]
        beams = predict_beams(model, vocab, mcfg, stmt, state,
                              beam_width=args.k_max, length_penalty=0.7)
        seen: Dict[str, str] = {}
        for t, _s in beams:
            t = t.strip()
            if t and t not in seen:
                seen[t] = f"token_seq2seq:{mk}"
        composed = compose_candidates(list(seen.keys()), state_before=state,
                                      theorem_statement=stmt)
        for t, src, _m in composed:
            if t not in seen:
                seen[t] = src
        pool = list(seen.items())
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
                order = _order_abstract(rr, rows, category=category)
            else:
                order = _order_policy_abstract(rr, learned, rows, category=category)
            reordered = [rows[j] for j in order][:args.k_max]
            verifs = []
            for r in reordered:
                hit = cache.get(nm, r.candidate)
                if hit is None:
                    hit = verifier(nm, stmt, r.candidate)
                    cache.put(nm, r.candidate, hit)
                verifs.append({"success": bool(hit.get("success")),
                               "error": hit.get("error")})
            for v, r in zip(verifs, reordered):
                if not v.get("success"):
                    ec = classify_error(v.get("error"))
                    per_tax[cfg][ec] = per_tax[cfg].get(ec, 0) + 1
            p1, p5, p10 = _pass_at(verifs, 1), _pass_at(verifs, 5), _pass_at(verifs, 10)
            per_pass[cfg][1] += int(p1)
            per_pass[cfg][5] += int(p5)
            per_pass[cfg][10] += int(p10)
            per_first[cfg].append(_first_rank(verifs))
            top1 = reordered[0] if reordered else None
            if top1 and classify_error(verifs[0].get("error")) in {
                    "parse_error", "unknown_tactic", "invalid"} and not verifs[0]["success"]:
                per_malformed[cfg] += 1
            cc = per_cat[cfg].setdefault(category, {"n": 0, "p1": 0, "p5": 0, "p10": 0})
            cc["n"] += 1
            cc["p1"] += int(p1)
            cc["p5"] += int(p5)
            cc["p10"] += int(p10)
            per_records[cfg].append({
                "theorem_name": nm, "category": category,
                "required_operation": op, "routed_model": mk,
                "config": cfg, "n_union_candidates": len(pool),
                "ordering": [r.candidate for r in reordered],
                "sources": [r.candidate_source for r in reordered],
                "verifications": verifs,
                "pass@1": p1, "pass@5": p5, "pass@10": p10,
                "first_verified_rank": _first_rank(verifs)})

    n = len(seeds)
    out_root = Path(args.out_root)
    summary = {"n_test_theorems": n, "routed": routed, "configs": {}}
    for cfg in CONFIGS:
        d = out_root / cfg
        d.mkdir(parents=True, exist_ok=True)
        pc = {cat: {"n": v["n"], "pass@1": v["p1"] / v["n"],
                    "pass@5": v["p5"] / v["n"], "pass@10": v["p10"] / v["n"]}
              for cat, v in per_cat[cfg].items()}
        fr = [r for r in per_first[cfg] if r is not None]
        m = {"n_test_theorems": n,
             "pass@1": per_pass[cfg][1] / n, "pass@5": per_pass[cfg][5] / n,
             "pass@10": per_pass[cfg][10] / n,
             "MRR": sum(1.0 / (r + 1) for r in fr) / n if n else 0.0,
             "n_no_candidate_verified": sum(1 for r in per_first[cfg] if r is None),
             "n_malformed_top1": per_malformed[cfg],
             "error_taxonomy": per_tax[cfg], "per_category": pc,
             "config": cfg, "uses_state_after": False, "routed": routed}
        (d / "metrics.json").write_text(json.dumps(m, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
        with (d / "predictions.jsonl").open("w", encoding="utf-8") as f:
            for r in per_records[cfg]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        summary["configs"][cfg] = m
        logger.info("  %s pass@1=%.3f pass@5=%.3f pass@10=%.3f no_verify=%d",
                    cfg, m["pass@1"], m["pass@5"], m["pass@10"],
                    m["n_no_candidate_verified"])
    cache.save()
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("V21 eval DONE -> %s", out_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
