"""Mini-ELF v25 — Part 4: zero-shot evaluation of the fixed v24 broad
generator on the v25 Mathlib tier-C benchmark.

Identical candidate-pool + rerank machinery as the v21/v24 broad-core
eval (token seq2seq beams + literal-adapt compose + raw/rule/learned/
policy/abstract/policy_abstract orderings), but:

  * candidates are verified by **whole-file typecheck against Mathlib**
    (`lake env lean`, `import Mathlib`, inside the external scratch
    project) — never the core-Lean verifier, never a mock;
  * metrics are broken down per **category** (nat/list/bool_option/set/
    logic) **and** per **transfer** flag (core vs mathlib);
  * a v25 **failure taxonomy** is recorded per failed candidate
    (unknown tactic / unknown identifier / type mismatch / unsolved
    goals = shape miss / parse error / import-env / timeout / other),
    plus a theorem-level "no candidate verified" reason.

The v24 model is **fixed** — it never saw any v25 / Mathlib data, so the
zero-shot eval is leakage-free by construction. No state_after; the
manual reference candidates are NOT fed to the model (beams come only
from the generator).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.abstract_pattern_reranker import (  # noqa: E402
    AbstractPatternReranker, build_pattern_bag,
)
from mini_elf_lean.baseline_eval import VerificationCache  # noqa: E402
from mini_elf_lean.learned_reranker import LearnedReranker  # noqa: E402
from mini_elf_lean.lean_runner import LeanCliRunner  # noqa: E402
from mini_elf_lean.literal_aware_decode import (  # noqa: E402
    SOURCE_LITERAL_ADAPT, compose_candidates,
)
from mini_elf_lean.proof_block_reranker import rerank as rule_rerank_fn  # noqa: E402
from mini_elf_lean.rerank_dataset import CandidateRow, classify_error  # noqa: E402
from mini_elf_lean.schemas import TheoremSeed  # noqa: E402
from mini_elf_lean import v15_rerank_policy  # noqa: E402
from mini_elf_lean.token_seq2seq import load_token_model, predict_beams  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_v25_tierc")

DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"
CONFIGS = ("raw", "rule", "learned", "policy", "abstract", "policy_abstract")


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


# ---- Mathlib verifier (whole-file typecheck, import Mathlib) ----
def make_mathlib_verifier(scratch: Path, timeout: float, imports: List[str]):
    runner = LeanCliRunner(command="lake env lean", working_dir=scratch)

    def verify(theorem_name: str, statement: str, tactic: str) -> Dict[str, Any]:
        seed = TheoremSeed(
            theorem_name=theorem_name, theorem_statement=statement,
            template=f"example {statement} := by\n  __TACTIC__",
            placeholder="__TACTIC__", imports=imports)
        state0 = runner.start(seed)
        t0 = time.perf_counter()
        try:
            res = runner.run_tactic(state0, tactic, timeout=timeout)
        finally:
            runner.close()
        return {"success": bool(res.success), "error": res.error,
                "elapsed_ms": (time.perf_counter() - t0) * 1000.0}

    return verify


# ---- v25 failure taxonomy (brief Part 4) ----
def v25_taxonomy(err: Optional[str]) -> str:
    if err is None:
        return "ok"
    s = err.lower()
    if "timeout" in s:
        return "timeout"
    if "unknown module" in s or "no directory" in s or "olean" in s \
            or "failed to" in s and "import" in s:
        return "import_env"
    if "unknown identifier" in s or "unknown constant" in s:
        return "unknown_identifier"
    if "unknown tactic" in s or ("tactic" in s and "has not been implemented" in s):
        return "unknown_tactic"
    if "type mismatch" in s or "expected to have type" in s \
            or "application type mismatch" in s:
        return "type_mismatch"
    if ("unexpected token" in s or "unexpected end of input" in s
            or "unexpected identifier" in s or "expected" in s and "tactic" in s):
        return "parse_error"
    if "unsolved goals" in s or "no goals" in s:
        return "shape_miss"  # tactic ran but did not close (or over-closed) the goal
    return "other"


# ---- ordering helpers (same as v21/v24 broad-core eval) ----
def _rows(pool, *, nm, stmt, state, op):
    out = []
    for i, (t, src) in enumerate(pool):
        out.append(CandidateRow(
            theorem_name=nm, family=op or "unknown", required_operation=op,
            theorem_statement=stmt, state_before=state, candidate=t,
            candidate_source=src, beam_rank=i, verified=False,
            error_class="ok", source_run="v25_eval"))
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


def _pass_at(verifs, k):
    return any(v.get("success") for v in verifs[:k])


def _first_rank(verifs):
    for i, v in enumerate(verifs):
        if v.get("success"):
            return i
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--seeds", default=str(ROOT / "data" / "seeds"
                                           / "v25_mathlib_tierc_seeds.jsonl"))
    ap.add_argument("--model-root",
                    default=str(ROOT / "data" / "models" / "token_seq2seq_v24_broad_residual"))
    ap.add_argument("--pattern-bag-rows",
                    default=str(ROOT / "data" / "processed"
                                / "v24_broad_plus_residual" / "train_rows.jsonl"))
    ap.add_argument("--learned-reranker",
                    default=str(ROOT / "data" / "models" / "v15_reranker" / "neg_imp_exfalso"))
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--out-root", default=str(ROOT / "data" / "baselines"
                                              / "v25_zero_shot_tierc"))
    ap.add_argument("--cache", default=str(ROOT / "data" / "lean_cache"
                                           / "v25_tierc_cache.json"))
    ap.add_argument("--verifier-timeout", type=float, default=60.0)
    ap.add_argument("--k-max", type=int, default=10)
    ap.add_argument("--model-label", default="v24_broad_residual")
    args = ap.parse_args(argv)

    seeds = _read_jsonl(Path(args.seeds))
    if not seeds:
        logger.error("no v25 seeds at %s", args.seeds)
        return 2
    scratch = Path(args.scratch_dir).resolve()

    model, vocab, mcfg = load_token_model(Path(args.model_root))
    logger.info("loaded model %s (%d seeds)", args.model_root, len(seeds))

    bag_rows = _read_jsonl(Path(args.pattern_bag_rows))
    bag = build_pattern_bag(bag_rows)
    rr = AbstractPatternReranker(bag=bag)
    logger.info("pattern bag: %d rows, %d patterns", bag.n_rows, len(bag.global_counts))
    learned = LearnedReranker.load(Path(args.learned_reranker))

    imports = seeds[0].get("imports", ["import Mathlib"])
    cache = VerificationCache.load(Path(args.cache), enabled=True)
    verifier = make_mathlib_verifier(scratch, args.verifier_timeout, imports)
    wu = verifier("__v25_warmup__", "(n : Nat) : n + 0 = n", "rfl")
    logger.info("Mathlib warmup success=%s", wu.get("success"))
    if not wu.get("success"):
        logger.error("Mathlib warmup failed: %s", (wu.get("error") or "")[:160])
        return 2

    per_records = {c: [] for c in CONFIGS}
    per_pass = {c: {1: 0, 5: 0, 10: 0} for c in CONFIGS}
    per_first = {c: [] for c in CONFIGS}
    per_tax = {c: {} for c in CONFIGS}
    per_cat = {c: {} for c in CONFIGS}
    per_transfer = {c: {} for c in CONFIGS}
    no_verify_reason = {c: {} for c in CONFIGS}

    for seed in seeds:
        nm = seed["theorem_name"]
        stmt = seed["theorem_statement"]
        state = seed["state_before"]
        category = seed.get("category", "unknown")
        transfer = seed.get("transfer", "unknown")
        op = seed.get("required_operation", "unknown")

        beams = predict_beams(model, vocab, mcfg, stmt, state,
                              beam_width=args.k_max, length_penalty=0.7)
        seen: Dict[str, str] = {}
        for t, _s in beams:
            t = t.strip()
            if t and t not in seen:
                seen[t] = "token_seq2seq:v24_broad_residual"
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
            for v in verifs:
                if not v.get("success"):
                    ec = v25_taxonomy(v.get("error"))
                    per_tax[cfg][ec] = per_tax[cfg].get(ec, 0) + 1
            p1, p5, p10 = _pass_at(verifs, 1), _pass_at(verifs, 5), _pass_at(verifs, 10)
            per_pass[cfg][1] += int(p1)
            per_pass[cfg][5] += int(p5)
            per_pass[cfg][10] += int(p10)
            fr = _first_rank(verifs)
            per_first[cfg].append(fr)
            if fr is None:
                # theorem-level no-verify reason: most common failure class,
                # or "no_schema_in_beam" if the pool was empty
                if not verifs:
                    reason = "no_schema_in_beam"
                else:
                    classes = [v25_taxonomy(v.get("error")) for v in verifs]
                    reason = max(set(classes), key=classes.count)
                no_verify_reason[cfg][nm] = reason
            cc = per_cat[cfg].setdefault(category, {"n": 0, "p1": 0, "p5": 0, "p10": 0})
            cc["n"] += 1
            cc["p1"] += int(p1); cc["p5"] += int(p5); cc["p10"] += int(p10)
            tt = per_transfer[cfg].setdefault(transfer, {"n": 0, "p1": 0, "p5": 0, "p10": 0})
            tt["n"] += 1
            tt["p1"] += int(p1); tt["p5"] += int(p5); tt["p10"] += int(p10)
            per_records[cfg].append({
                "theorem_name": nm, "category": category, "transfer": transfer,
                "required_operation": op, "config": cfg,
                "n_union_candidates": len(pool),
                "ordering": [r.candidate for r in reordered],
                "sources": [r.candidate_source for r in reordered],
                "verifications": verifs,
                "pass@1": p1, "pass@5": p5, "pass@10": p10,
                "first_verified_rank": fr})

    n = len(seeds)
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    summary = {"n_test_theorems": n, "model": args.model_label,
               "mathlib": True, "imports": imports, "configs": {}}
    for cfg in CONFIGS:
        d = out_root / cfg
        d.mkdir(parents=True, exist_ok=True)
        pc = {cat: {"n": v["n"], "pass@1": v["p1"] / v["n"],
                    "pass@5": v["p5"] / v["n"], "pass@10": v["p10"] / v["n"]}
              for cat, v in per_cat[cfg].items()}
        pt = {tr: {"n": v["n"], "pass@1": v["p1"] / v["n"],
                   "pass@5": v["p5"] / v["n"], "pass@10": v["p10"] / v["n"]}
              for tr, v in per_transfer[cfg].items()}
        fr = [r for r in per_first[cfg] if r is not None]
        m = {"n_test_theorems": n,
             "pass@1": per_pass[cfg][1] / n, "pass@5": per_pass[cfg][5] / n,
             "pass@10": per_pass[cfg][10] / n,
             "MRR": sum(1.0 / (r + 1) for r in fr) / n if n else 0.0,
             "n_no_candidate_verified": sum(1 for r in per_first[cfg] if r is None),
             "no_verify_reason": no_verify_reason[cfg],
             "failure_taxonomy": per_tax[cfg],
             "per_category": pc, "per_transfer": pt,
             "config": cfg, "model": args.model_label,
             "mathlib": True, "uses_state_after": False, "uses_manual_oracle": False}
        (d / "metrics.json").write_text(json.dumps(m, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
        with (d / "predictions.jsonl").open("w", encoding="utf-8") as f:
            for r in per_records[cfg]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        summary["configs"][cfg] = {k: m[k] for k in (
            "pass@1", "pass@5", "pass@10", "MRR", "n_no_candidate_verified",
            "per_transfer")}
        logger.info("  %-16s p@1=%.3f p@5=%.3f p@10=%.3f no_verify=%d",
                    cfg, m["pass@1"], m["pass@5"], m["pass@10"],
                    m["n_no_candidate_verified"])
    cache.save()
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
    logger.info("V25 zero-shot tier-C eval DONE -> %s", out_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
