"""Mini-ELF v19 — Part 4/5: evaluate v19 abstract model on v18.

Inference pipeline:
  1. For each v18 theorem, build its abstraction map against the
     test state_before.
  2. Feed the **abstract state** as the model's input.
  3. Beam-decode N candidate abstract tactics.
  4. Concretise each abstract tactic against the v18 state's
     placeholder→name map. Unresolved placeholders → fail with
     ``unresolved_placeholder``.
  5. Verify the concretised candidate with the warm lean-cli
     verifier (timeout 120 s + warm-up).
  6. Optionally compose with the v18 raw-name broad-synthetic
     beam (ensemble) and apply the v17 policy reranker.

Outputs at ``data/baselines/v19_abstract_eval/<config>/`` with the
same metric structure as v18.
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
from mini_elf_lean.identifier_abstraction import (  # noqa: E402
    abstract_state, build_abstraction_map, concretise_or_fail,
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
logger = logging.getLogger("evaluate_v19_abstract")


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


def _first_verified_rank(verifs: Sequence[Dict[str, Any]]
                         ) -> Optional[int]:
    for i, v in enumerate(verifs):
        if v.get("success"):
            return i
    return None


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


def _build_panel(
    *, abstract_model_dir: Path, broad_synthetic_dir: Optional[Path],
) -> List[Tuple[str, Any, Any, Any, bool]]:
    """Returns (name, model, vocab, cfg, is_abstract) tuples."""
    panel: List[Tuple[str, Any, Any, Any, bool]] = []
    if abstract_model_dir and (abstract_model_dir / "model.pt").exists():
        m, v, c = load_token_model(abstract_model_dir)
        panel.append(("v19_abstract", m, v, c, True))
    if (broad_synthetic_dir
            and (broad_synthetic_dir / "model.pt").exists()):
        m, v, c = load_token_model(broad_synthetic_dir)
        panel.append(("v18_broad_synthetic", m, v, c, False))
    return panel


def _emit_candidates_for_theorem(
    *, panel: List[Tuple[str, Any, Any, Any, bool]],
    theorem_statement: str, state_before: str, beam_width: int,
) -> List[Tuple[str, str, str, str, Optional[str]]]:
    """Returns a list of
    (tactic_concrete_or_raw, source, abstract_tactic_or_None,
     concretisation_reason, raw_beam_tactic).

    For abstract models we emit:
      * abstract_tactic: the model's literal output (placeholders)
      * concretised tactic: after substitution against
        ``state_before``; None if unresolved.
    For raw-name models we emit the beam string directly.
    """
    out: List[Tuple[str, str, str, str, Optional[str]]] = []
    for name, model, vocab, cfg, is_abstract in panel:
        if is_abstract:
            abs_state, _, _ = abstract_state(state_before, "")
            beams = predict_beams(model, vocab, cfg,
                                  theorem_statement, abs_state,
                                  beam_width=beam_width,
                                  length_penalty=0.7)
            for tactic_abs, _score in beams:
                concrete, reason = concretise_or_fail(
                    tactic_abs, state_before)
                if reason in ("ok", "no_placeholders") and concrete:
                    out.append((concrete, f"token_seq2seq:{name}",
                                tactic_abs, reason, tactic_abs))
                else:
                    # Keep the abstract tactic for failure-taxonomy
                    # accounting (will be classified as
                    # 'unresolved_placeholder' downstream).
                    out.append((tactic_abs, f"token_seq2seq:{name}",
                                tactic_abs, reason, tactic_abs))
        else:
            beams = predict_beams(model, vocab, cfg,
                                  theorem_statement, state_before,
                                  beam_width=beam_width,
                                  length_penalty=0.7)
            for tactic, _score in beams:
                out.append((tactic, f"token_seq2seq:{name}",
                            None, "raw", tactic))
    # Dedup on concretised text (first occurrence wins, keeps
    # provenance).
    seen: Dict[str, Tuple[str, str, str, str, Optional[str]]] = {}
    for rec in out:
        text = rec[0]
        if text and text not in seen:
            seen[text] = rec
    return list(seen.values())


def _build_candidate_rows(
    items: Sequence[Tuple[str, str, str, str, Optional[str]]],
    *, theorem_name: str, theorem_statement: str, state_before: str,
    required_operation: Optional[str],
) -> List[CandidateRow]:
    rows: List[CandidateRow] = []
    for i, (tactic, src, _abs, _reason, _raw) in enumerate(items):
        rows.append(CandidateRow(
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
            source_run="v19_abstract_eval",
        ))
    return rows


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


def _order_policy(model: LearnedReranker,
                  cand_rows: Sequence[CandidateRow]) -> List[int]:
    if not cand_rows:
        return []
    state_before = cand_rows[0].state_before
    required_operation = cand_rows[0].required_operation
    return v15_rerank_policy.reorder(
        cand_rows, model=model, state_before=state_before,
        required_operation=required_operation,
    )


def evaluate(
    *, panel, learned_model: LearnedReranker,
    seeds: List[Dict[str, Any]], cache: VerificationCache, verifier,
    out_root: Path, beam_width: int, k_max: int,
) -> Dict[str, Any]:
    configs = ("raw", "rule", "policy")
    summary: Dict[str, Any] = {"n_test_theorems": len(seeds),
                               "configs": {}}
    per_config_records: Dict[str, List[Dict[str, Any]]] = {
        c: [] for c in configs}
    per_config_pass: Dict[str, Dict[int, int]] = {
        c: {1: 0, 5: 0, 10: 0} for c in configs}
    per_config_first: Dict[str, List[Optional[int]]] = {
        c: [] for c in configs}
    per_config_taxonomy: Dict[str, Dict[str, int]] = {
        c: {} for c in configs}
    per_config_category: Dict[str, Dict[str, Dict[str, int]]] = {
        c: {} for c in configs}
    per_config_unresolved: Dict[str, int] = {c: 0 for c in configs}

    for seed in seeds:
        nm = seed["theorem_name"]
        stmt = seed["theorem_statement"]
        state = seed["state_before"]
        cat = seed["category"]
        operation = _V18_CAT_TO_OP.get(cat, "unknown")

        t0 = time.perf_counter()
        items = _emit_candidates_for_theorem(
            panel=panel, theorem_statement=stmt, state_before=state,
            beam_width=beam_width)
        # Append literal_adapt candidates (raw side)
        raw_tactics = [t for t, _, _, _, _ in items]
        composed = compose_candidates(
            raw_tactics, state_before=state, theorem_statement=stmt)
        existing = {t for t, _, _, _, _ in items}
        for tactic, src, _meta in composed:
            if tactic not in existing:
                items.append((tactic, src, None, "literal_adapt",
                              tactic))
                existing.add(tactic)
        beam_ms = (time.perf_counter() - t0) * 1000.0

        cand_rows = _build_candidate_rows(
            items, theorem_name=nm, theorem_statement=stmt,
            state_before=state, required_operation=operation,
        )

        # Track unresolved placeholders separately (concretisation
        # failed). Items where reason != ok produced an abstract
        # tactic as the candidate string — that's failure-class
        # information, not a verifiable candidate.
        unresolved_set = set()
        for i, (tactic, src, abs_t, reason, raw) in enumerate(items):
            if reason not in ("ok", "no_placeholders", "raw",
                              "literal_adapt"):
                unresolved_set.add(tactic)

        for cfg in configs:
            if cfg == "raw":
                order = _order_raw(cand_rows)
            elif cfg == "rule":
                order = _order_rule(cand_rows)
            else:
                order = _order_policy(learned_model, cand_rows)
            reordered = [cand_rows[j] for j in order][: k_max]

            verifs: List[Dict[str, Any]] = []
            for r in reordered:
                # Unresolved placeholders: skip lean entirely; mark
                # as concretisation_failed.
                if r.candidate in unresolved_set:
                    verifs.append({"success": False,
                                   "error": "unresolved_placeholder"})
                    per_config_unresolved[cfg] += 1
                    continue
                hit = cache.get(r.theorem_name, r.candidate)
                if hit is not None:
                    res = hit
                else:
                    res = verifier(r.theorem_name, r.theorem_statement,
                                   r.candidate)
                    cache.put(r.theorem_name, r.candidate, res)
                verifs.append({"success": bool(res.get("success")),
                               "error": res.get("error")})

            for v, r in zip(verifs, reordered):
                r.verified = bool(v.get("success"))
                r.error_class = (classify_error(v.get("error"))
                                 if not v.get("success")
                                 else "ok")
                tax = per_config_taxonomy[cfg]
                if not v.get("success"):
                    err = v.get("error") or ""
                    if "unresolved_placeholder" in err:
                        tax["unresolved_placeholder"] = (
                            tax.get("unresolved_placeholder", 0) + 1)
                    else:
                        tax[r.error_class] = tax.get(
                            r.error_class, 0) + 1

            p1 = _pass_at(verifs, 1)
            p5 = _pass_at(verifs, 5)
            p10 = _pass_at(verifs, 10)
            per_config_pass[cfg][1] += int(p1)
            per_config_pass[cfg][5] += int(p5)
            per_config_pass[cfg][10] += int(p10)
            per_config_first[cfg].append(_first_verified_rank(verifs))
            ccat = per_config_category[cfg].setdefault(cat, {
                "n": 0, "pass@1": 0, "pass@5": 0, "pass@10": 0,
            })
            ccat["n"] += 1
            ccat["pass@1"] += int(p1)
            ccat["pass@5"] += int(p5)
            ccat["pass@10"] += int(p10)

            per_config_records[cfg].append({
                "theorem_name": nm,
                "category": cat,
                "required_operation": operation,
                "config": cfg,
                "n_union_candidates": len(items),
                "ordering": [r.candidate for r in reordered],
                "sources": [r.candidate_source for r in reordered],
                "verifications": verifs,
                "pass@1": p1, "pass@5": p5, "pass@10": p10,
                "first_verified_rank": _first_verified_rank(verifs),
                "beam_ms": round(beam_ms, 1),
            })

    n = len(seeds)
    for cfg in configs:
        recs = per_config_records[cfg]
        out_dir = out_root / cfg
        out_dir.mkdir(parents=True, exist_ok=True)
        per_cat = {}
        for cat, d in per_config_category[cfg].items():
            per_cat[cat] = {
                "n": d["n"],
                "pass@1": d["pass@1"] / d["n"] if d["n"] else 0.0,
                "pass@5": d["pass@5"] / d["n"] if d["n"] else 0.0,
                "pass@10": d["pass@10"] / d["n"] if d["n"] else 0.0,
            }
        cfg_metrics = {
            "n_test_theorems": n,
            "pass@1": per_config_pass[cfg][1] / n if n else 0.0,
            "pass@5": per_config_pass[cfg][5] / n if n else 0.0,
            "pass@10": per_config_pass[cfg][10] / n if n else 0.0,
            "n_no_candidate_verified": sum(
                1 for r in per_config_first[cfg] if r is None),
            "n_unresolved_placeholder_top10": per_config_unresolved[cfg],
            "error_taxonomy": per_config_taxonomy[cfg],
            "per_category": per_cat,
            "config": cfg,
            "uses_state_after": False,
        }
        (out_dir / "metrics.json").write_text(
            json.dumps(cfg_metrics, indent=2, ensure_ascii=False),
            encoding="utf-8")
        with (out_dir / "predictions.jsonl").open("w",
                                                  encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        summary["configs"][cfg] = cfg_metrics
        logger.info(
            "  %s pass@1=%.3f pass@5=%.3f pass@10=%.3f "
            "no_verify=%d unresolved=%d",
            cfg, cfg_metrics["pass@1"], cfg_metrics["pass@5"],
            cfg_metrics["pass@10"],
            cfg_metrics["n_no_candidate_verified"],
            cfg_metrics["n_unresolved_placeholder_top10"],
        )
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--seeds",
                    default=str(ROOT / "data" / "seeds"
                                / "v18_broad_core_seeds.jsonl"))
    ap.add_argument("--abstract-model",
                    default=str(ROOT / "data" / "models"
                                / "token_seq2seq_v19_abstract"))
    ap.add_argument("--broad-synthetic",
                    default=str(ROOT / "data" / "models"
                                / "token_seq2seq_v18_broad_synthetic"),
                    help="If set, ensemble: include the v18 broad-"
                         "synthetic raw-name model in the panel "
                         "alongside the v19 abstract model.")
    ap.add_argument("--no-broad-synthetic", dest="use_broad",
                    action="store_false")
    ap.set_defaults(use_broad=True)
    ap.add_argument("--abstract-only", action="store_true",
                    help="Skip the broad-synthetic panel member.")
    ap.add_argument("--learned-reranker",
                    default=str(ROOT / "data" / "models"
                                / "v15_reranker" / "neg_imp_exfalso"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v19_abstract_eval"))
    ap.add_argument("--cache",
                    default=str(ROOT / "data" / "lean_cache"
                                / "v19_abstract_cache.json"))
    ap.add_argument("--verifier-timeout", type=float, default=120.0)
    ap.add_argument("--beam-width", type=int, default=10)
    ap.add_argument("--k-max", type=int, default=10)
    args = ap.parse_args(argv)

    seeds = _read_jsonl(Path(args.seeds))
    if not seeds:
        logger.error("no v18 seeds at %s", args.seeds)
        return 1
    logger.info("loaded %d v18 seeds", len(seeds))

    broad_root = (None if args.abstract_only
                  else Path(args.broad_synthetic) if args.use_broad
                  else None)
    panel = _build_panel(
        abstract_model_dir=Path(args.abstract_model),
        broad_synthetic_dir=broad_root,
    )
    logger.info("panel: %d models loaded (abstract_only=%s)",
                len(panel), args.abstract_only)
    if not panel:
        logger.error("no models loaded")
        return 1

    learned = LearnedReranker.load(Path(args.learned_reranker))
    cache = VerificationCache.load(Path(args.cache), enabled=True)
    verifier = make_lean_cli_verifier(timeout=args.verifier_timeout)
    t0 = time.perf_counter()
    wu = verifier("__v19_warmup__", "(x : Nat) : x = x", "rfl")
    logger.info("warmup: success=%s elapsed_ms=%.1f",
                wu.get("success"), (time.perf_counter() - t0) * 1000.0)

    summary = evaluate(
        panel=panel, learned_model=learned, seeds=seeds,
        cache=cache, verifier=verifier,
        out_root=Path(args.out_root),
        beam_width=args.beam_width, k_max=args.k_max,
    )
    cache.save()
    (Path(args.out_root) / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8")
    logger.info("V19 ABSTRACT EVAL DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
