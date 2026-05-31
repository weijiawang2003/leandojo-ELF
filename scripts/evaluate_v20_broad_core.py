"""Mini-ELF v20 — Part 5/6: evaluate the v20 broad-plus model on
v18 broad-core, with five configs:

  * ``raw``      — beam-order from the v20 model + composed
                    literal-aware adapt.
  * ``rule``     — v15 rule reranker.
  * ``learned``  — v15 learned reranker.
  * ``policy``   — v15+v17 policy router.
  * ``abstract`` — v20 ranker-time abstract-pattern reranker
                    (Part 6).
  * ``policy_abstract`` — policy router then abstract-pattern
                    reorder of ties.

The v20 model is the SOLE generator (no v16/v17 panel). This
mirrors the v18 ``--broad-only`` setting that gave the best v18
result (pass@5 = 0.583). We are testing whether v20's expanded
corpus shifts the v18 broad-only baseline up.

No state_after, no manual oracle, no Mathlib.

Outputs:
  ``data/baselines/v20_broad_plus_eval/<config>/{metrics,predictions}.{json,jsonl}``
  ``data/baselines/v20_broad_plus_eval/summary.json``
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
    AbstractPatternReranker, build_pattern_bag, save_pattern_bag,
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
from mini_elf_lean.token_seq2seq import (  # noqa: E402
    load_token_model, predict_beams,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v20_broad_core")


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def _pass_at(verifs: Sequence[Dict[str, Any]], k: int) -> bool:
    for v in verifs[:k]:
        if v.get("success"):
            return True
    return False


def _first_verified_rank(verifs: Sequence[Dict[str, Any]]) -> Optional[int]:
    for i, v in enumerate(verifs):
        if v.get("success"):
            return i
    return None


def _build_candidate_rows(pool, *, theorem_name, theorem_statement,
                          state_before, required_operation):
    out: List[CandidateRow] = []
    for i, (tactic, src) in enumerate(pool):
        out.append(CandidateRow(
            theorem_name=theorem_name,
            family=required_operation or "unknown",
            required_operation=required_operation,
            theorem_statement=theorem_statement,
            state_before=state_before,
            candidate=tactic,
            candidate_source=src,
            beam_rank=i,
            verified=False,
            error_class="ok",
            source_run="v20_broad_plus_eval",
        ))
    return out


def _order_raw(rows):
    primary, la, other = [], [], []
    for i, r in enumerate(rows):
        if r.candidate_source == SOURCE_LITERAL_ADAPT:
            la.append(i)
        elif r.candidate_source.startswith("token_seq2seq"):
            primary.append(i)
        else:
            other.append(i)
    primary.sort(key=lambda i: rows[i].beam_rank)
    la.sort(key=lambda i: rows[i].beam_rank)
    other.sort(key=lambda i: rows[i].beam_rank)
    return primary + la + other


def _order_rule(rows):
    if not rows:
        return []
    items = [(r.candidate, r.candidate_source) for r in rows]
    state_before = rows[0].state_before
    required_operation = rows[0].required_operation
    reranked = rule_rerank_fn(items, state_before=state_before,
                              required_operation=required_operation)
    idx_by_t: Dict[str, List[int]] = {}
    for j, r in enumerate(rows):
        idx_by_t.setdefault(r.candidate, []).append(j)
    order: List[int] = []
    for c in reranked:
        js = idx_by_t.get(c.tactic, [])
        if js:
            order.append(js.pop(0))
    seen = set(order)
    for j in range(len(rows)):
        if j not in seen:
            order.append(j)
    return order


def _order_learned(model, rows):
    scored: List[Tuple[int, float, int]] = []
    for i, r in enumerate(rows):
        p = model.score_row(r)
        scored.append((i, p, r.beam_rank))
    scored.sort(key=lambda t: (-t[1], t[2]))
    return [t[0] for t in scored]


def _order_policy(model, rows):
    if not rows:
        return []
    state_before = rows[0].state_before
    required_operation = rows[0].required_operation
    return v15_rerank_policy.reorder(
        rows, model=model, state_before=state_before,
        required_operation=required_operation,
    )


def _order_abstract(reranker: AbstractPatternReranker, rows,
                    *, category: Optional[str]):
    if not rows:
        return []
    state = rows[0].state_before
    cands = [r.candidate for r in rows]
    return reranker.order(cands, state_before=state, category=category)


def _order_policy_abstract(reranker, model, rows, *,
                            category: Optional[str]):
    """First apply v15 policy, then within the top-k re-order ties
    using the abstract-pattern score. Implementation: get policy
    order, then stable-sort by (-abstract_score, policy_index)."""
    pol = _order_policy(model, rows)
    if not rows:
        return pol
    state = rows[0].state_before
    cands = [rows[i].candidate for i in pol]
    rer = reranker.rerank(cands, state_before=state, category=category)
    # rer is sorted by score descending; map back to original rows
    # via pol indices
    out: List[int] = []
    seen_pos: Dict[str, int] = {}
    for s in rer:
        # match s.candidate to next occurrence in cands
        c = s.candidate
        start = seen_pos.get(c, 0)
        for j in range(start, len(cands)):
            if cands[j] == c:
                out.append(pol[j])
                seen_pos[c] = j + 1
                break
    # Append any remaining (shouldn't happen)
    used = set(out)
    for k in pol:
        if k not in used:
            out.append(k)
    return out


# v18 category → required_operation hint used by v15 policy
_V18_CAT_TO_OP = {
    "implication": "implication",
    "conjunction": "unknown",
    "disjunction": "unknown",
    "negation": "intro_negation",
    "equality_rewrite": "rewrite",
    "exists": "unknown",
    "forall": "instantiate_forall",
    "nat_succ": "rewrite",
    "bool": "bool_cases",
    "list": "rewrite",
}


def evaluate(*, model, vocab, mcfg, learned_model, abstract_reranker,
             seeds, cache, verifier, out_root: Path, k_max: int):
    configs = ("raw", "rule", "learned", "policy", "abstract",
               "policy_abstract")
    summary: Dict[str, Any] = {"n_test_theorems": len(seeds), "configs": {}}
    per_records = {c: [] for c in configs}
    per_pass = {c: {1: 0, 5: 0, 10: 0} for c in configs}
    per_first_rank = {c: [] for c in configs}
    per_no_verify = {c: 0 for c in configs}
    per_malformed = {c: 0 for c in configs}
    per_taxonomy = {c: {} for c in configs}
    per_head_correct = {c: 0 for c in configs}
    per_cat_pass = {c: {} for c in configs}

    for seed in seeds:
        nm = seed["theorem_name"]
        stmt = seed["theorem_statement"]
        state = seed["state_before"]
        category = seed["category"]
        expected_head = seed.get("expected_tactic_head")
        operation = _V18_CAT_TO_OP.get(category, "unknown")

        t0 = time.perf_counter()
        beams = predict_beams(
            model, vocab, mcfg, stmt, state,
            beam_width=k_max, length_penalty=0.7,
        )
        seen = {}
        for tactic, _score in beams:
            t = tactic.strip()
            if t and t not in seen:
                seen[t] = "token_seq2seq:v20_broad_plus"
        raw_tactics = list(seen.keys())
        composed = compose_candidates(
            raw_tactics, state_before=state, theorem_statement=stmt)
        for tactic, src, _meta in composed:
            if tactic not in seen:
                seen[tactic] = src
        pool = list(seen.items())
        beam_ms = (time.perf_counter() - t0) * 1000.0
        cand_rows = _build_candidate_rows(
            pool, theorem_name=nm, theorem_statement=stmt,
            state_before=state, required_operation=operation,
        )

        for cfg in configs:
            if cfg == "raw":
                order = _order_raw(cand_rows)
            elif cfg == "rule":
                order = _order_rule(cand_rows)
            elif cfg == "learned":
                order = _order_learned(learned_model, cand_rows)
            elif cfg == "policy":
                order = _order_policy(learned_model, cand_rows)
            elif cfg == "abstract":
                order = _order_abstract(abstract_reranker, cand_rows,
                                        category=category)
            else:  # policy_abstract
                order = _order_policy_abstract(
                    abstract_reranker, learned_model, cand_rows,
                    category=category)
            reordered = [cand_rows[j] for j in order][:k_max]

            verifs: List[Dict[str, Any]] = []
            for r in reordered:
                hit = cache.get(nm, r.candidate)
                if hit is not None:
                    res = hit
                else:
                    res = verifier(nm, stmt, r.candidate)
                    cache.put(nm, r.candidate, res)
                verifs.append({"success": bool(res.get("success")),
                               "error": res.get("error")})

            for v, r in zip(verifs, reordered):
                r.verified = bool(v.get("success"))
                r.error_class = classify_error(v.get("error"))
                if not v.get("success"):
                    per_taxonomy[cfg][r.error_class] = \
                        per_taxonomy[cfg].get(r.error_class, 0) + 1
            p1 = _pass_at(verifs, 1)
            p5 = _pass_at(verifs, 5)
            p10 = _pass_at(verifs, 10)
            per_pass[cfg][1] += int(p1)
            per_pass[cfg][5] += int(p5)
            per_pass[cfg][10] += int(p10)
            fr = _first_verified_rank(verifs)
            per_first_rank[cfg].append(fr)
            if fr is None:
                per_no_verify[cfg] += 1
            top1 = reordered[0] if reordered else None
            if top1 is not None:
                if top1.error_class in {"parse_error", "unknown_tactic",
                                        "invalid"}:
                    per_malformed[cfg] += 1
                if expected_head and top1.candidate.split():
                    if top1.candidate.split()[0] == expected_head:
                        per_head_correct[cfg] += 1
            ccat = per_cat_pass[cfg].setdefault(category, {
                "n": 0, "pass@5": 0, "pass@1": 0, "pass@10": 0})
            ccat["n"] += 1
            ccat["pass@1"] += int(p1)
            ccat["pass@5"] += int(p5)
            ccat["pass@10"] += int(p10)

            per_records[cfg].append({
                "theorem_name": nm,
                "category": category,
                "required_operation": operation,
                "expected_tactic_head": expected_head,
                "config": cfg,
                "n_union_candidates": len(pool),
                "ordering": [r.candidate for r in reordered],
                "sources": [r.candidate_source for r in reordered],
                "verifications": verifs,
                "pass@1": p1, "pass@5": p5, "pass@10": p10,
                "first_verified_rank": fr,
                "beam_ms": round(beam_ms, 1),
            })

    n = len(seeds)
    for cfg in configs:
        out_dir = out_root / cfg
        out_dir.mkdir(parents=True, exist_ok=True)
        per_cat = {}
        for cat, d in per_cat_pass[cfg].items():
            per_cat[cat] = {
                "n": d["n"],
                "pass@1": d["pass@1"] / d["n"] if d["n"] else 0.0,
                "pass@5": d["pass@5"] / d["n"] if d["n"] else 0.0,
                "pass@10": d["pass@10"] / d["n"] if d["n"] else 0.0,
            }
        fr = [r for r in per_first_rank[cfg] if r is not None]
        mrr = (sum(1.0 / (r + 1) for r in fr) / n) if n else 0.0
        cfg_metrics = {
            "n_test_theorems": n,
            "pass@1": per_pass[cfg][1] / n if n else 0.0,
            "pass@5": per_pass[cfg][5] / n if n else 0.0,
            "pass@10": per_pass[cfg][10] / n if n else 0.0,
            "MRR": mrr,
            "n_no_candidate_verified": per_no_verify[cfg],
            "n_malformed_top1": per_malformed[cfg],
            "n_top1_head_correct": per_head_correct[cfg],
            "first_verified_rank_distribution": {
                str(i): sum(1 for r in per_first_rank[cfg] if r == i)
                for i in range(k_max)
            },
            "first_verified_rank_none": sum(
                1 for r in per_first_rank[cfg] if r is None),
            "error_taxonomy": per_taxonomy[cfg],
            "per_category": per_cat,
            "config": cfg,
            "uses_state_after": False,
        }
        (out_dir / "metrics.json").write_text(
            json.dumps(cfg_metrics, indent=2, ensure_ascii=False),
            encoding="utf-8")
        with (out_dir / "predictions.jsonl").open("w", encoding="utf-8") as f:
            for r in per_records[cfg]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        summary["configs"][cfg] = cfg_metrics
        logger.info(
            "  %s pass@1=%.3f pass@5=%.3f pass@10=%.3f MRR=%.3f "
            "no_verify=%d malformed_top1=%d head_correct=%d",
            cfg, cfg_metrics["pass@1"], cfg_metrics["pass@5"],
            cfg_metrics["pass@10"], cfg_metrics["MRR"],
            cfg_metrics["n_no_candidate_verified"],
            cfg_metrics["n_malformed_top1"],
            cfg_metrics["n_top1_head_correct"],
        )
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--seeds",
                    default=str(ROOT / "data" / "seeds"
                                / "v18_broad_core_seeds.jsonl"))
    ap.add_argument("--model-root",
                    default=str(ROOT / "data" / "models"
                                / "token_seq2seq_v20_broad_plus"))
    ap.add_argument("--train-rows",
                    default=str(ROOT / "data" / "processed"
                                / "v20_broad_synthetic_plus"
                                / "train_rows.jsonl"))
    ap.add_argument("--learned-reranker",
                    default=str(ROOT / "data" / "models" / "v15_reranker"
                                / "neg_imp_exfalso"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v20_broad_plus_eval"))
    ap.add_argument("--pattern-bag-out",
                    default=str(ROOT / "data" / "baselines"
                                / "v20_broad_plus_eval"
                                / "pattern_bag.json"))
    ap.add_argument("--cache",
                    default=str(ROOT / "data" / "lean_cache"
                                / "v20_broad_plus_cache.json"))
    ap.add_argument("--verifier-timeout", type=float, default=120.0)
    ap.add_argument("--k-max", type=int, default=10)
    args = ap.parse_args(argv)

    seeds = _read_jsonl(Path(args.seeds))
    if not seeds:
        logger.error("no v18 seeds at %s", args.seeds)
        return 1
    logger.info("loaded %d v18 seeds", len(seeds))

    model, vocab, mcfg = load_token_model(Path(args.model_root))
    logger.info("v20 broad-plus model loaded")
    learned_model = LearnedReranker.load(Path(args.learned_reranker))
    logger.info("learned reranker: %s", args.learned_reranker)

    # Build pattern bag from training rows
    train_rows = _read_jsonl(Path(args.train_rows))
    bag = build_pattern_bag(train_rows)
    logger.info("pattern bag: %d rows, %d unique global patterns",
                bag.n_rows, len(bag.global_counts))
    save_pattern_bag(Path(args.pattern_bag_out), bag)
    abstract_reranker = AbstractPatternReranker(bag=bag)

    cache = VerificationCache.load(Path(args.cache), enabled=True)
    verifier = make_lean_cli_verifier(timeout=args.verifier_timeout)
    t0 = time.perf_counter()
    wu = verifier("__v20_warmup__", "(x : Nat) : x = x", "rfl")
    logger.info("warmup: success=%s elapsed_ms=%.1f",
                wu.get("success"), (time.perf_counter() - t0) * 1000.0)

    summary = evaluate(
        model=model, vocab=vocab, mcfg=mcfg,
        learned_model=learned_model,
        abstract_reranker=abstract_reranker,
        seeds=seeds, cache=cache, verifier=verifier,
        out_root=Path(args.out_root), k_max=args.k_max,
    )
    cache.save()
    (Path(args.out_root) / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8")
    logger.info("V20 broad-core eval DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
