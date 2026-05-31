"""Mini-ELF v18 — Part 4: zero-shot v17 pipeline on v18 benchmark.

For each v18 theorem we:
  1. Decode a beam-width-10 from every v16/v17 token model
     (5 models = 4 v16 + 1 v17 for neg_exfalso). The union is a
     50-candidate "panel" — what the v17 pipeline would have
     access to without knowing the v18 category.
  2. Dedup and append the v12 literal-aware decode additions.
  3. Apply each of the four v15-policy configs (raw / rule /
     learned / policy) to the union, retaining the top 10.
  4. Verify with the warm lean-cli verifier (timeout 120 s).

Outputs at ``data/baselines/v18_zero_shot_v17_pipeline/<config>/``.

This is the **honest** transfer test the v18 brief asks for:
"How much of Mini-ELF v17 transfers from templated synthetic
families to a broader, less-templated Lean corpus?"
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
    TOKEN_SEQ2SEQ_SOURCE, load_token_model, predict_beams,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v18_zero_shot")


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


def _load_model_panel(model_v16_root: Path, model_v17_root: Path,
                      *, broad_synthetic_root: Optional[Path] = None,
                      broad_only: bool = False,
                      ) -> List[Tuple[str, Any, Any, Any]]:
    """v17 composed: v17 for neg_exfalso, v16 for the other 4.
    Optionally augment / replace with the v18 broad-synthetic model."""
    panel: List[Tuple[str, Any, Any, Any]] = []
    if not broad_only:
        families = [
            ("forall_inst", model_v16_root),
            ("rewrite_succ", model_v16_root),
            ("exists_reconstruct", model_v16_root),
            ("neg_imp_exfalso", model_v16_root),
            ("neg_exfalso", model_v17_root),
        ]
        for fam, root in families:
            d = root / fam
            if not (d / "model.pt").exists():
                logger.warning("SKIP model %s/%s — model.pt missing",
                               root, fam)
                continue
            model, vocab, cfg = load_token_model(d)
            panel.append((fam, model, vocab, cfg))
    if broad_synthetic_root and (broad_synthetic_root / "model.pt").exists():
        model, vocab, cfg = load_token_model(broad_synthetic_root)
        panel.append(("broad_synthetic", model, vocab, cfg))
    return panel


def panel_beams(
    panel: Sequence[Tuple[str, Any, Any, Any]],
    *, theorem_statement: str, state_before: str,
) -> List[Tuple[str, str]]:
    seen: Dict[str, str] = {}
    for fam, model, vocab, cfg in panel:
        beams = predict_beams(
            model, vocab, cfg, theorem_statement, state_before,
            beam_width=10, length_penalty=0.7,
        )
        for tactic, _score in beams:
            t = tactic.strip()
            if not t:
                continue
            if t not in seen:
                seen[t] = f"token_seq2seq:{fam}"
    return list(seen.items())


def _build_candidate_rows(
    pool: Sequence[Tuple[str, str]], *, theorem_name: str, theorem_statement: str,
    state_before: str, required_operation: Optional[str],
) -> List[CandidateRow]:
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
            source_run="v18_zero_shot",
        ))
    return out


def _order_raw(cand_rows: Sequence[CandidateRow]) -> List[int]:
    primary, la, other = [], [], []
    for i, r in enumerate(cand_rows):
        if r.candidate_source == SOURCE_LITERAL_ADAPT:
            la.append(i)
        elif r.candidate_source.startswith("token_seq2seq"):
            primary.append(i)
        else:
            other.append(i)
    primary.sort(key=lambda i: cand_rows[i].beam_rank)
    la.sort(key=lambda i: cand_rows[i].beam_rank)
    other.sort(key=lambda i: cand_rows[i].beam_rank)
    return primary + la + other


def _order_rule(cand_rows: Sequence[CandidateRow]) -> List[int]:
    if not cand_rows:
        return []
    items = [(r.candidate, r.candidate_source) for r in cand_rows]
    state_before = cand_rows[0].state_before
    required_operation = cand_rows[0].required_operation
    reranked = rule_rerank_fn(items, state_before=state_before,
                              required_operation=required_operation)
    idx_by_tactic: Dict[str, List[int]] = {}
    for j, r in enumerate(cand_rows):
        idx_by_tactic.setdefault(r.candidate, []).append(j)
    order: List[int] = []
    for c in reranked:
        js = idx_by_tactic.get(c.tactic, [])
        if js:
            order.append(js.pop(0))
    seen = set(order)
    for j in range(len(cand_rows)):
        if j not in seen:
            order.append(j)
    return order


def _order_learned(model: LearnedReranker,
                   cand_rows: Sequence[CandidateRow]) -> List[int]:
    scored: List[Tuple[int, float, int]] = []
    for i, r in enumerate(cand_rows):
        p = model.score_row(r)
        scored.append((i, p, r.beam_rank))
    scored.sort(key=lambda t: (-t[1], t[2]))
    return [t[0] for t in scored]


def _order_policy(
    model: LearnedReranker, cand_rows: Sequence[CandidateRow],
) -> List[int]:
    if not cand_rows:
        return []
    state_before = cand_rows[0].state_before
    required_operation = cand_rows[0].required_operation
    return v15_rerank_policy.reorder(
        cand_rows, model=model, state_before=state_before,
        required_operation=required_operation,
    )


_V18_CAT_TO_OP = {
    "implication": "unknown",
    "conjunction": "unknown",
    "disjunction": "unknown",
    "negation": "intro_negation",
    "equality_rewrite": "rewrite",
    "exists": "unknown",
    "forall": "instantiate_forall",
    "nat_succ": "rewrite",
    "bool": "unknown",
    "list": "rewrite",
}


def evaluate(
    *, panel, learned_model: LearnedReranker, seeds: List[Dict[str, Any]],
    cache: VerificationCache, verifier, out_root: Path, k_max: int,
) -> Dict[str, Any]:
    configs = ("raw", "rule", "learned", "policy")
    summary: Dict[str, Any] = {"n_test_theorems": len(seeds), "configs": {}}

    per_config_records: Dict[str, List[Dict[str, Any]]] = {c: [] for c in configs}
    per_config_pass: Dict[str, Dict[int, int]] = {
        c: {1: 0, 5: 0, 10: 0} for c in configs}
    per_config_first_rank: Dict[str, List[Optional[int]]] = {c: [] for c in configs}
    per_config_no_verify: Dict[str, int] = {c: 0 for c in configs}
    per_config_malformed_top1: Dict[str, int] = {c: 0 for c in configs}
    per_config_taxonomy: Dict[str, Dict[str, int]] = {c: {} for c in configs}
    per_config_top1_head_correct: Dict[str, int] = {c: 0 for c in configs}
    per_config_category_pass5: Dict[str, Dict[str, Dict[str, int]]] = {
        c: {} for c in configs}

    for seed in seeds:
        nm = seed["theorem_name"]
        stmt = seed["theorem_statement"]
        state = seed["state_before"]
        category = seed["category"]
        expected_head = seed.get("expected_tactic_head")
        operation = _V18_CAT_TO_OP.get(category, "unknown")

        t0 = time.perf_counter()
        union = panel_beams(panel, theorem_statement=stmt, state_before=state)
        raw_tactics = [t for t, _ in union]
        composed = compose_candidates(
            raw_tactics, state_before=state, theorem_statement=stmt)
        seen = {t: s for t, s in union}
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
            else:  # policy
                order = _order_policy(learned_model, cand_rows)
            reordered = [cand_rows[j] for j in order][: k_max]

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
                tax = per_config_taxonomy[cfg]
                if not v.get("success"):
                    tax[r.error_class] = tax.get(r.error_class, 0) + 1

            p1 = _pass_at(verifs, 1)
            p5 = _pass_at(verifs, 5)
            p10 = _pass_at(verifs, 10)
            per_config_pass[cfg][1] += int(p1)
            per_config_pass[cfg][5] += int(p5)
            per_config_pass[cfg][10] += int(p10)
            fr = _first_verified_rank(verifs)
            per_config_first_rank[cfg].append(fr)
            if fr is None:
                per_config_no_verify[cfg] += 1
            top1 = reordered[0] if reordered else None
            if top1 is not None:
                if top1.error_class in {"parse_error", "unknown_tactic",
                                        "invalid"}:
                    per_config_malformed_top1[cfg] += 1
                if expected_head and top1.candidate.split():
                    if top1.candidate.split()[0] == expected_head:
                        per_config_top1_head_correct[cfg] += 1
            ccat = per_config_category_pass5[cfg].setdefault(category, {
                "n": 0, "pass@5": 0, "pass@1": 0, "pass@10": 0,
            })
            ccat["n"] += 1
            ccat["pass@1"] += int(p1)
            ccat["pass@5"] += int(p5)
            ccat["pass@10"] += int(p10)

            per_config_records[cfg].append({
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
        recs = per_config_records[cfg]
        out_dir = out_root / cfg
        out_dir.mkdir(parents=True, exist_ok=True)
        per_cat = {}
        for cat, d in per_config_category_pass5[cfg].items():
            per_cat[cat] = {
                "n": d["n"],
                "pass@1": d["pass@1"] / d["n"] if d["n"] else 0.0,
                "pass@5": d["pass@5"] / d["n"] if d["n"] else 0.0,
                "pass@10": d["pass@10"] / d["n"] if d["n"] else 0.0,
            }
        first_ranks = [r for r in per_config_first_rank[cfg] if r is not None]
        mrr = (sum(1.0 / (r + 1) for r in first_ranks) / n) if n else 0.0
        cfg_metrics = {
            "n_test_theorems": n,
            "pass@1": per_config_pass[cfg][1] / n if n else 0.0,
            "pass@5": per_config_pass[cfg][5] / n if n else 0.0,
            "pass@10": per_config_pass[cfg][10] / n if n else 0.0,
            "MRR": mrr,
            "n_no_candidate_verified": per_config_no_verify[cfg],
            "n_malformed_top1": per_config_malformed_top1[cfg],
            "n_top1_head_correct": per_config_top1_head_correct[cfg],
            "first_verified_rank_distribution": {
                str(i): sum(1 for r in per_config_first_rank[cfg] if r == i)
                for i in range(k_max)
            },
            "first_verified_rank_none": sum(
                1 for r in per_config_first_rank[cfg] if r is None),
            "error_taxonomy": per_config_taxonomy[cfg],
            "per_category": per_cat,
            "config": cfg,
            "uses_state_after": False,
        }
        (out_dir / "metrics.json").write_text(
            json.dumps(cfg_metrics, indent=2, ensure_ascii=False),
            encoding="utf-8")
        with (out_dir / "predictions.jsonl").open("w", encoding="utf-8") as f:
            for r in recs:
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
    ap.add_argument("--model-v16-root",
                    default=str(ROOT / "data" / "models"
                                / "token_seq2seq_v16"))
    ap.add_argument("--model-v17-root",
                    default=str(ROOT / "data" / "models"
                                / "token_seq2seq_v17"))
    ap.add_argument("--learned-reranker",
                    default=str(ROOT / "data" / "models" / "v15_reranker"
                                / "neg_imp_exfalso"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v18_zero_shot_v17_pipeline"))
    ap.add_argument("--cache",
                    default=str(ROOT / "data" / "lean_cache"
                                / "v18_zero_shot_cache.json"))
    ap.add_argument("--verifier-timeout", type=float, default=120.0)
    ap.add_argument("--k-max", type=int, default=10)
    ap.add_argument("--broad-synthetic-root",
                    default=None,
                    help="If set, add this v18 broad-synthetic model to the "
                         "panel.")
    ap.add_argument("--broad-only", action="store_true",
                    help="Use ONLY the broad-synthetic model (drop the "
                         "v16/v17 family panel). Honest scaling test.")
    args = ap.parse_args(argv)

    seeds = _read_jsonl(Path(args.seeds))
    if not seeds:
        logger.error("no v18 seeds at %s", args.seeds)
        return 1
    logger.info("loaded %d v18 seeds across %d categories",
                len(seeds), len({s["category"] for s in seeds}))

    broad_root = (Path(args.broad_synthetic_root)
                  if args.broad_synthetic_root else None)
    panel = _load_model_panel(
        Path(args.model_v16_root), Path(args.model_v17_root),
        broad_synthetic_root=broad_root, broad_only=args.broad_only,
    )
    logger.info("panel: %d models loaded (broad_only=%s)",
                len(panel), args.broad_only)

    learned_model = LearnedReranker.load(Path(args.learned_reranker))
    logger.info("learned reranker: %s (n_features=%d)",
                args.learned_reranker, len(learned_model.weights))

    cache = VerificationCache.load(Path(args.cache), enabled=True)
    verifier = make_lean_cli_verifier(timeout=args.verifier_timeout)
    t0 = time.perf_counter()
    wu = verifier("__v18_warmup__", "(x : Nat) : x = x", "rfl")
    logger.info("warmup: success=%s elapsed_ms=%.1f",
                wu.get("success"), (time.perf_counter() - t0) * 1000.0)

    summary = evaluate(
        panel=panel, learned_model=learned_model, seeds=seeds,
        cache=cache, verifier=verifier,
        out_root=Path(args.out_root), k_max=args.k_max,
    )
    cache.save()
    (Path(args.out_root) / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8")
    logger.info("V18 zero-shot eval DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
