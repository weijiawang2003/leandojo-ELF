"""Mini-ELF v27 — Part 3: expanded Mathlib category gap audit.

Aggregates the v26 artifacts (verified corpus, Lean-rejected corpus, specialist
eval predictions) into a per-category gap report that drives the v27 corpus
expansion (Part 4). For each category we surface:

  * solved / unsolved theorem counts (from v26 specialist eval on the held-out
    benchmarks);
  * the proof shapes already covered (verified-corpus proof-head distribution and
    lemma vocabulary);
  * Lean-rejected shapes — API / arity mistakes the corpus generator hit;
  * the specific residual theorems the specialist still misses, with their
    failure class;
  * a proposed corpus expansion.

Reads only existing artifacts (no Lean). Writes
``data/baselines/v27_category_gaps/report.json``. Honesty: derived from real
Lean-verified traces and real eval verdicts; no state_after, no manual oracle.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


_LEMMA_RE = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:\.[A-Za-z0-9_']+)+)\b")


def lemma_vocab(tactic: str) -> List[str]:
    """Qualified identifiers used in a tactic (Set.inter_subset_left, Nat.le_refl…)."""
    return _LEMMA_RE.findall(tactic or "")


def proof_head(tactic: str) -> str:
    t = (tactic or "").strip()
    return t.split()[0].split(";")[0] if t else ""


def best_metrics(eval_dir: Path) -> Dict[str, Any]:
    """Pick the best-config metrics.json under a v26 eval run dir."""
    best = None
    for f in eval_dir.glob("*/metrics.json"):
        m = json.loads(f.read_text())
        key = (m.get("pass@5", 0), m.get("pass@1", 0))
        if best is None or key > best[0]:
            best = (key, m)
    return best[1] if best else {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines" / "v27_category_gaps" / "report.json"))
    args = ap.parse_args(argv)

    verified = _read(ROOT / "data" / "traces" / "v26_mathlib_specialist_verified.jsonl")
    failed = _read(ROOT / "data" / "traces" / "v26_mathlib_specialist_failed.jsonl")

    # 1. coverage per category
    cov: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"theorems": set(), "rows": 0, "proof_heads": Counter(),
                 "lemmas": Counter(), "uses_simp": 0, "uses_omega": 0,
                 "uses_aesop": 0, "uses_tauto": 0})
    for r in verified:
        cat = r.get("category", "unknown")
        c = cov[cat]
        c["theorems"].add(r["theorem_name"])
        c["rows"] += 1
        t = r["tactic"]
        c["proof_heads"][proof_head(t)] += 1
        for lm in lemma_vocab(t):
            c["lemmas"][lm] += 1
        c["uses_simp"] += int("simp" in t)
        c["uses_omega"] += int("omega" in t)
        c["uses_aesop"] += int("aesop" in t)
        c["uses_tauto"] += int("tauto" in t)

    # 2. Lean-rejected shapes per category (API/arity mistakes)
    rejected: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for r in failed:
        rejected[r.get("category", "unknown")].append(
            {"tactic": r["tactic"], "error": r.get("error_head", "")[:90],
             "theorem": r.get("theorem_name", "")})

    # 3. residual theorems the specialist still misses (eval)
    benches = {
        "v25_heldout": ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl",
        "v26_holdout": ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout" / "test_seeds.jsonl",
    }
    seed_stmt = {}
    for bp in benches.values():
        for s in _read(bp):
            seed_stmt[s["theorem_name"]] = s["theorem_statement"]

    residuals: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    eval_cat_pass: Dict[str, Dict[str, Any]] = {}
    for model in ("v26_base", "v26_widened"):
        for bench in benches:
            base_dir = ROOT / "data" / "baselines" / ("v26_widen_eval" if model == "v26_widened" else "v26_specialist_eval")
            ev = base_dir / f"{model}__{bench}"
            m = best_metrics(ev)
            if not m:
                continue
            eval_cat_pass[f"{model}__{bench}"] = {
                "best_config": m.get("config"), "pass@10": m.get("pass@10"),
                "per_category": {c: v.get("pass@10") for c, v in m.get("per_category", {}).items()}}
            # residual theorems = no candidate verified
            cfg = m.get("config")
            preds = _read(ev / cfg / "predictions.jsonl")
            for r in preds:
                if not r.get("pass@10"):
                    residuals[r.get("category", "unknown")].append({
                        "model": model, "bench": bench, "theorem": r["theorem_name"],
                        "statement": seed_stmt.get(r["theorem_name"], ""),
                        "failure": (m.get("no_verify_reason", {}) or {}).get(r["theorem_name"], "no_verified_in_top10")})

    # assemble report
    all_cats = sorted(set(cov) | set(rejected) | set(residuals))
    report: Dict[str, Any] = {"config": "v27_category_gaps", "eval_summary": eval_cat_pass, "categories": {}}
    # proposed expansion hints per category (data-driven label; corpus in Part 4)
    expansion_hint = {
        "set": "membership iff (mem_inter_iff/mem_union), inter/union comm & assoc subset, "
               "diff/compl subset, singleton/insert membership, subset_trans, mem→union",
        "nat": "associativity variants (add_assoc both directions), two_mul/succ, "
               "≤ transitivity/min/max/lt_succ, add_sub_cancel correct arity",
        "list": "use simp / arity-free lemma forms (length_cons w/o explicit args), "
                "append_assoc, reverse_reverse, map_map, mem_append",
        "logic": "contrapositive, demorgan, curry/uncurry, or/and symm & self_iff, em",
        "bool_option": "and/or/not identities via cases<;>simp, dichotomy, option map id/getD",
        "function": "comp id both sides via funext, comp_assoc, const apply",
        "order": "le_refl/le_succ/zero_le/le_add, le_trans, succ_le_succ, lt_succ_self, le_of_eq",
    }
    for cat in all_cats:
        c = cov.get(cat)
        res = residuals.get(cat, [])
        # dedup residual theorems
        seen = set()
        res_dedup = []
        for r in res:
            if r["theorem"] in seen:
                continue
            seen.add(r["theorem"])
            res_dedup.append(r)
        report["categories"][cat] = {
            "covered_theorems": len(c["theorems"]) if c else 0,
            "covered_rows": c["rows"] if c else 0,
            "top_proof_heads": dict(c["proof_heads"].most_common(8)) if c else {},
            "top_lemmas": dict(c["lemmas"].most_common(12)) if c else {},
            "uses_simp_rows": c["uses_simp"] if c else 0,
            "uses_omega_rows": c["uses_omega"] if c else 0,
            "lean_rejected": rejected.get(cat, []),
            "n_residual_theorems": len(res_dedup),
            "residual_theorems": res_dedup,
            "proposed_expansion": expansion_hint.get(cat, "general shape diversity"),
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[gaps] wrote {out}")
    for cat in all_cats:
        d = report["categories"][cat]
        print(f"  {cat:12s} covered_thms={d['covered_theorems']:2d} rows={d['covered_rows']:3d} "
              f"rejected={len(d['lean_rejected'])} residual_thms={d['n_residual_theorems']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
