"""Mini-ELF v14 — evaluate the trained token-level seq2seq.

For each v11 family-LOFO test fold, loads the matching v14 token model,
emits a beam-width-10 candidate list per test row, then runs the same
*warm* lean-cli verifier introduced in v13 (timeout=120 s, one warm-up
theorem). Outputs land at:

  data/baselines/v14_token_seq2seq/<fam>/
    predictions.jsonl     # one row per test theorem
    metrics.json          # pass@k + malformed / schema / failure taxonomy
    verification_cache.json  # shared across folds; safe to re-run
  data/baselines/v14_token_seq2seq/summary.json

Optionally a second config ``+literal_adapt_rerank`` is computed: same
candidate list passed through v12's literal-aware decode + rule-based
reranker so we can quantify how often the token model needs the v12
post-processing.

Honesty contract (verbatim from v14 brief):
  - Do not alter v12/v13 metrics.
  - Do not retcon v13 as a model improvement.
  - Do not use state_after.
  - Do not use manual oracle candidates as model outputs.
  - Do not revive leaked v10 metrics.
  - Do not claim full theorem proving.

This script never touches files under ``data/baselines/v12_eval/`` or
``data/baselines/v13_timeout_rerun/``.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
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
from mini_elf_lean.literal_aware_decode import (  # noqa: E402
    SOURCE_LITERAL_ADAPT, SOURCE_SEQ2SEQ, compose_candidates,
)
from mini_elf_lean.proof_block_reranker import rerank  # noqa: E402
from mini_elf_lean.tactic_tokenizer import tokenize  # noqa: E402
from mini_elf_lean.token_seq2seq import (  # noqa: E402
    TOKEN_SEQ2SEQ_SOURCE, load_token_model, predict_beams,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_token_seq2seq")


# Patterns the v13 brief flagged as char-truncation artefacts the token
# model is supposed to make impossible. We count occurrences in the
# generated candidates as a *modelling* metric, not as a validation
# failure (lean's verdict is the ultimate judge).
_FUSED_TOKEN_PATTERNS: Tuple[str, ...] = (
    "refintro",   # fused refine + intro
    "rwexact",    # fused rw + exact
    "casexact",   # observed in some v8 beams
    "introexact", # observed
)


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


def _candidate_class(cand: str) -> Dict[str, bool]:
    """Tag a candidate for the v14 modelling-side audit. Independent
    of lean's verdict."""
    toks = tokenize(cand)
    tok_texts = [t.text for t in toks]
    has_fused = any(any(p in tt for p in _FUSED_TOKEN_PATTERNS)
                    for tt in tok_texts)
    # exact h <num>
    schema_exact_h_num = False
    for i, tt in enumerate(tok_texts):
        if (tt == "exact" and i + 4 < len(tok_texts)
                and tok_texts[i + 2].isidentifier()
                and tok_texts[i + 4].isdigit()):
            schema_exact_h_num = True
            break
    # rw [h] / rw [<ident>]
    schema_rw_h = False
    if "rw" in tok_texts and "[" in tok_texts and "]" in tok_texts:
        # Look for the pattern rw _? [_ ident _? ]
        try:
            i = tok_texts.index("rw")
            j = tok_texts.index("[", i)
            k_ = tok_texts.index("]", j)
            inner = [t for t in tok_texts[j + 1:k_]
                     if t.strip() and t != " "]
            schema_rw_h = (len(inner) == 1 and inner[0].isidentifier())
        except ValueError:
            schema_rw_h = False
    # syntactic "malformed" heuristic: open bracket without close, fused
    # token, or trailing operator
    malformed = False
    opens = sum(t == "[" for t in tok_texts)
    closes = sum(t == "]" for t in tok_texts)
    if opens != closes:
        malformed = True
    if has_fused:
        malformed = True
    if cand.strip().endswith(("[", "(", "{", ",", "→")):
        malformed = True
    # truncation-shape (`exact h.` / `rw [hns` / `cases h wi`)
    truncated = False
    if cand.rstrip().endswith("."):
        truncated = True
    if cand.endswith(("[", "with", "wi")):
        truncated = True
    return {
        "has_fused_token": has_fused,
        "schema_exact_h_num": schema_exact_h_num,
        "schema_rw_h": schema_rw_h,
        "malformed": malformed,
        "truncated_shape": truncated,
    }


def _classify_error(err: Optional[str]) -> str:
    if err is None:
        return "ok"
    s = err.lower()
    if "timeout" in s:
        return "timeout"
    if "type mismatch" in s or "expected to have type" in s:
        return "type_mismatch"
    if "unknown identifier" in s:
        return "unknown_identifier"
    if "unknown tactic" in s:
        return "unknown_tactic"
    if "unexpected" in s or "unexpected end of input" in s or "expected" in s:
        return "parse_error"
    if "unsolved goals" in s:
        return "unsolved_goals"
    return "other"


def evaluate_family(
    *, fam: str, model_root: Path, fold_root: Path, out_root: Path,
    cache: VerificationCache, verifier, beam_width: int, k_max: int,
    use_literal_adapt_rerank: bool,
) -> Dict[str, Any]:
    model_dir = model_root / fam
    if not (model_dir / "model.pt").exists():
        logger.warning("SKIP %s (no model at %s)", fam, model_dir)
        return {"fam": fam, "error": "missing_model"}

    model, vocab, cfg = load_token_model(model_dir)
    test_rows = _read_jsonl(fold_root / fam / "test.jsonl")
    if not test_rows:
        logger.warning("SKIP %s (no test.jsonl)", fam)
        return {"fam": fam, "error": "missing_test"}
    train_rows = _read_jsonl(fold_root / fam / "train.jsonl")
    train_tactics = {r.get("tactic", "").strip() for r in train_rows}

    summary = {"fam": fam, "n_test_theorems": len(test_rows), "configs": {}}

    configs = ["raw"]
    if use_literal_adapt_rerank:
        configs.append("literal_adapt_rerank")

    for config in configs:
        per_row: List[Dict[str, Any]] = []
        pass_k = {1: 0, 5: 0, 10: 0}
        verified_total = 0
        novel_verified = 0
        verified_with_fused_token = 0
        n_with_fused_token = 0
        n_malformed = 0
        n_truncated_shape = 0
        n_schema_exact_h_num = 0
        n_schema_rw_h = 0
        error_taxonomy: Dict[str, int] = {}
        literal_adapt_verified = 0
        forall_inst_var_m_pass5 = None  # tracked separately for the brief

        for tr in test_rows:
            nm = tr["theorem_name"]
            stmt = tr.get("theorem_statement", "")
            state = tr.get("state_before", "")
            req_op = tr.get("required_operation")
            t0 = time.perf_counter()
            beams = predict_beams(model, vocab, cfg, stmt, state,
                                  beam_width=beam_width)
            beam_time_ms = (time.perf_counter() - t0) * 1000.0

            # Compose candidates
            raw_cands = [s for s, _ in beams]
            sources: List[str] = []
            if config == "raw":
                items = [(c, TOKEN_SEQ2SEQ_SOURCE) for c in raw_cands]
            else:  # literal_adapt_rerank
                composed = compose_candidates(
                    raw_cands, state_before=state, theorem_statement=stmt)
                items = [(t, s) for (t, s, _meta) in composed]
                items = [(c.tactic, c.source) for c in rerank(
                    items, state_before=state, required_operation=req_op,
                )]
            items = items[: k_max]
            tactics = [t for t, _ in items]
            sources = [s for _, s in items]

            # Audit + verify
            cand_classes = [_candidate_class(t) for t in tactics]
            n_with_fused_token += sum(c["has_fused_token"] for c in cand_classes)
            n_malformed += sum(c["malformed"] for c in cand_classes)
            n_truncated_shape += sum(c["truncated_shape"] for c in cand_classes)
            n_schema_exact_h_num += sum(c["schema_exact_h_num"]
                                        for c in cand_classes)
            n_schema_rw_h += sum(c["schema_rw_h"] for c in cand_classes)

            verifs: List[Dict[str, Any]] = []
            for t in tactics:
                hit = cache.get(nm, t)
                if hit is not None:
                    res = hit
                else:
                    res = verifier(nm, stmt, t)
                    cache.put(nm, t, res)
                verifs.append({
                    "success": bool(res.get("success")),
                    "error": res.get("error"),
                })
                taxonomy_key = _classify_error(res.get("error"))
                if not res.get("success"):
                    error_taxonomy[taxonomy_key] = (
                        error_taxonomy.get(taxonomy_key, 0) + 1)

            p1, p5, p10 = (_pass_at(verifs, k) for k in (1, 5, 10))
            pass_k[1] += int(p1); pass_k[5] += int(p5); pass_k[10] += int(p10)

            for j, (t, src) in enumerate(items):
                if verifs[j].get("success"):
                    verified_total += 1
                    if t.strip() not in train_tactics:
                        novel_verified += 1
                    if cand_classes[j]["has_fused_token"]:
                        verified_with_fused_token += 1
                    if src == SOURCE_LITERAL_ADAPT:
                        literal_adapt_verified += 1

            if nm == "forall_inst_var_m":
                forall_inst_var_m_pass5 = p5

            per_row.append({
                "theorem_name": nm,
                "config": config,
                "candidates": tactics,
                "sources": sources,
                "verifications": verifs,
                "candidate_classes": cand_classes,
                "pass@1": p1, "pass@5": p5, "pass@10": p10,
                "beam_time_ms": round(beam_time_ms, 2),
            })

        n = len(test_rows)
        denom_cands = max(1, n * k_max)
        cfg_metrics = {
            "n_test_theorems": n,
            "n_candidates_total": n * k_max,
            "pass@1": pass_k[1] / n if n else 0.0,
            "pass@5": pass_k[5] / n if n else 0.0,
            "pass@10": pass_k[10] / n if n else 0.0,
            "verified_total": verified_total,
            "novel_verified": novel_verified,
            "n_with_fused_token": n_with_fused_token,
            "fused_token_rate": n_with_fused_token / denom_cands,
            "verified_with_fused_token": verified_with_fused_token,
            "n_malformed": n_malformed,
            "malformed_rate": n_malformed / denom_cands,
            "n_truncated_shape": n_truncated_shape,
            "truncated_shape_rate": n_truncated_shape / denom_cands,
            "n_schema_exact_h_num": n_schema_exact_h_num,
            "schema_exact_h_num_rate": n_schema_exact_h_num / denom_cands,
            "n_schema_rw_h": n_schema_rw_h,
            "schema_rw_h_rate": n_schema_rw_h / denom_cands,
            "error_taxonomy": error_taxonomy,
            "literal_adapt_verified": literal_adapt_verified,
            "forall_inst_var_m_pass@5": forall_inst_var_m_pass5,
            "k_max": k_max,
            "beam_width": beam_width,
            "config": config,
            "uses_state_after": False,
        }
        out_dir = out_root / fam / config
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "metrics.json").write_text(
            json.dumps(cfg_metrics, indent=2, ensure_ascii=False),
            encoding="utf-8")
        with (out_dir / "predictions.jsonl").open("w", encoding="utf-8") as f:
            for r in per_row:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        summary["configs"][config] = cfg_metrics
        logger.info(
            "  %s/%s pass@1=%.3f pass@5=%.3f pass@10=%.3f "
            "fused=%d malformed=%d truncated=%d exact_h_num=%d rw_h=%d "
            "verified=%d novel=%d literal_adapt_v=%d var_m_p5=%s",
            fam, config, cfg_metrics["pass@1"], cfg_metrics["pass@5"],
            cfg_metrics["pass@10"], n_with_fused_token, n_malformed,
            n_truncated_shape, n_schema_exact_h_num, n_schema_rw_h,
            verified_total, novel_verified, literal_adapt_verified,
            forall_inst_var_m_pass5,
        )

    return summary


def warm_up(verifier) -> Dict[str, Any]:
    """Mirror the v13 warm-up to ensure the per-batch wall-clock matches
    what v13 corrected metrics measured."""
    t0 = time.perf_counter()
    res = verifier("__v14_warmup__", "(x : Nat) : x = x", "rfl")
    res = dict(res)
    res["wallclock_ms"] = (time.perf_counter() - t0) * 1000.0
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--model-root",
                    default=str(ROOT / "data" / "models" / "token_seq2seq_v14"))
    ap.add_argument("--fold-root",
                    default=str(ROOT / "data" / "processed"
                                / "proof_blocks_v11_family_lofo"))
    ap.add_argument("--out-root",
                    default=str(ROOT / "data" / "baselines"
                                / "v14_token_seq2seq"))
    ap.add_argument("--cache",
                    default=str(ROOT / "data" / "lean_cache"
                                / "v14_token_cache.json"))
    ap.add_argument("--verifier-timeout", type=float, default=120.0)
    ap.add_argument("--beam-width", type=int, default=10)
    ap.add_argument("--k-max", type=int, default=10)
    ap.add_argument("--families", nargs="*",
                    default=["forall_inst", "rewrite_succ", "neg_exfalso",
                             "exists_reconstruct", "neg_imp_exfalso"])
    ap.add_argument("--no-literal-adapt-rerank",
                    dest="literal_adapt_rerank", action="store_false")
    ap.set_defaults(literal_adapt_rerank=True)
    ap.add_argument("--no-warmup", dest="warmup", action="store_false")
    ap.set_defaults(warmup=True)
    args = ap.parse_args(argv)

    cache = VerificationCache.load(Path(args.cache), enabled=True)
    verifier = make_lean_cli_verifier(timeout=args.verifier_timeout)

    if args.warmup:
        wu = warm_up(verifier)
        logger.info("warmup: success=%s err=%r elapsed_ms=%.1f",
                    wu.get("success"), wu.get("error"),
                    wu.get("wallclock_ms", 0))

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    summaries: List[Dict[str, Any]] = []
    for fam in args.families:
        s = evaluate_family(
            fam=fam,
            model_root=Path(args.model_root),
            fold_root=Path(args.fold_root),
            out_root=out_root,
            cache=cache,
            verifier=verifier,
            beam_width=args.beam_width,
            k_max=args.k_max,
            use_literal_adapt_rerank=args.literal_adapt_rerank,
        )
        summaries.append(s)
        cache.save()

    (out_root / "summary.json").write_text(
        json.dumps({"folds": summaries,
                    "verifier_timeout_seconds": args.verifier_timeout,
                    "beam_width": args.beam_width,
                    "warmup": args.warmup}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("V14 EVAL DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
