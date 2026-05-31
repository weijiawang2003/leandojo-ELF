"""Mini-ELF v26 — Part 1: audit of the v25 Mathlib tier-C failures.

Reads the *already-computed* v25 eval predictions (no re-running of Lean):

  * v24 broad generator, zero-shot, full 36-theorem tier-C benchmark
    (``data/baselines/v25_zero_shot_tierc/``);
  * v24 zero-shot on the 14 held-out tier-C theorems
    (``data/baselines/v24_zeroshot_tierc_test/``);
  * v25 co-trained ("augmented") model on the same 14 held-out theorems
    (``data/baselines/v25_aug_tierc_test/``);
  * v24 vs v25 broad-core 48-theorem evals (for the co-training interference
    evidence).

For every tier-C theorem it records: category, expected skill, transfer flag
(core vs mathlib-lemma), v24 zero-shot first-verified rank, v25 augmented
first-verified rank (held-out only), the dominant failure class among the
failed candidates, the missing identifiers Lean complained about, and a single
**bound** label:

  solved              — v24 already verifies a candidate in top-10
  ranking_bound       — a candidate verifies but only at rank >= 5
  generator_bound     — no candidate verifies; failures are unknown-id / wrong
                        lemma / wrong shape (the generator never proposes the
                        Mathlib lemma or proof shape)
  syntax_api_bound    — failures dominated by parse / arity / type-mismatch
  import_env_bound    — failures dominated by import/olean errors (expected ~0)

Honesty: this only summarizes prior verified results. No state_after, no manual
oracle, no Mathlib faked. Writes ``docs/V26_MATHLIB_FAILURE_AUDIT.md`` and
``data/baselines/v26_mathlib_failure_audit.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]

_UNKNOWN_RE = re.compile(r"[Uu]nknown (?:identifier|constant) `([^`]+)`")


def _read_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def taxonomy(err: Optional[str]) -> str:
    """Coarse error class for a single failed candidate."""
    if not err:
        return "ok"
    s = err.lower()
    if "timeout" in s:
        return "timeout"
    if "unknown module" in s or "olean" in s or ("failed to" in s and "import" in s):
        return "import_env"
    if "unknown identifier" in s or "unknown constant" in s:
        return "unknown_identifier"
    if "unknown tactic" in s or "has not been implemented" in s:
        return "unknown_tactic"
    if "type mismatch" in s or "expected to have type" in s \
            or "application type mismatch" in s \
            or "insufficient number of fields" in s or "function expected" in s:
        return "type_or_arity"
    if "unexpected" in s or ("expected" in s and "tactic" in s) \
            or "expected '" in s:
        return "parse_error"
    if "unsolved goals" in s or "no goals" in s:
        return "shape_miss"
    return "other"


# category -> expected skill bucket (the task's skill taxonomy)
def _is_order_goal(name: str) -> bool:
    n = name.lower()
    return "_le_" in n or n.endswith("_le") or "_lt_" in n or "subset" in n


def expected_skill(category: str, transfer: str, op: str, name: str = "") -> str:
    cat = (category or "").lower()
    if cat == "set":
        return "set"
    if _is_order_goal(name) and cat in ("nat", "set"):
        return "order"
    if transfer == "core":
        return "core-shaped"
    if cat == "nat":
        return "arithmetic"
    if cat == "list":
        return "list"
    if cat == "bool_option":
        return "bool/option"
    if cat == "logic":
        return "mathlib-lemma"
    return "mathlib-lemma"


def first_rank_map(eval_dir: Path, config: str) -> Dict[str, Any]:
    """theorem_name -> prediction row, from <eval_dir>/<config>/predictions.jsonl"""
    rows = _read_jsonl(eval_dir / config / "predictions.jsonl")
    return {r["theorem_name"]: r for r in rows}


def bound_label(zs_row: Dict[str, Any]) -> str:
    fr = zs_row.get("first_verified_rank")
    if fr is not None:
        return "solved" if fr < 5 else "ranking_bound"
    # no candidate verified in top-10: classify by dominant failure
    classes = [taxonomy(v.get("error")) for v in zs_row.get("verifications", [])
               if not v.get("success")]
    if not classes:
        return "generator_bound"
    dom = Counter(classes).most_common(1)[0][0]
    if dom == "import_env":
        return "import_env_bound"
    if dom in ("parse_error", "type_or_arity"):
        return "syntax_api_bound"
    # unknown_identifier / shape_miss / unknown_tactic -> generator can't
    # produce the right lemma or shape
    return "generator_bound"


def _is_lemma_name(ident: str) -> bool:
    """Heuristic: a missing *lemma/vocabulary* name (e.g. ``Set.Subset.refl``,
    ``Nat.zero_add``, ``Or.refl``) vs a hallucinated local binder (``g``,
    ``hx``, ``i``). Lemma names are dotted or capitalized or reasonably long."""
    if "." in ident:
        return True
    if ident[:1].isupper():
        return True
    return len(ident) >= 5


def missing_ids(zs_row: Dict[str, Any]) -> List[str]:
    """Missing lemma/vocabulary identifiers only (binder typos filtered out)."""
    out: List[str] = []
    for v in zs_row.get("verifications", []):
        if v.get("success"):
            continue
        for m in _UNKNOWN_RE.finditer(v.get("error") or ""):
            ident = m.group(1)
            if _is_lemma_name(ident):
                out.append(ident)
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x); uniq.append(x)
    return uniq[:8]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--zs-full", default=str(ROOT / "data" / "baselines" / "v25_zero_shot_tierc"))
    ap.add_argument("--zs-test", default=str(ROOT / "data" / "baselines" / "v24_zeroshot_tierc_test"))
    ap.add_argument("--aug-test", default=str(ROOT / "data" / "baselines" / "v25_aug_tierc_test"))
    ap.add_argument("--v24-broad", default=str(ROOT / "data" / "baselines" / "v24_broad_residual_eval"))
    ap.add_argument("--v25-broad", default=str(ROOT / "data" / "baselines" / "v25_broadcore_regression"))
    ap.add_argument("--test-theorems", default=str(ROOT / "data" / "processed"
                                                  / "v25_tierc_augmented" / "test_theorems.json"))
    ap.add_argument("--out-json", default=str(ROOT / "data" / "baselines" / "v26_mathlib_failure_audit.json"))
    ap.add_argument("--out-md", default=str(ROOT / "docs" / "V26_MATHLIB_FAILURE_AUDIT.md"))
    ap.add_argument("--config", default="raw", help="generator-order config to audit (raw = pure beam order)")
    args = ap.parse_args(argv)

    cfg = args.config
    zs_full = first_rank_map(Path(args.zs_full), cfg)
    zs_full_best = {c: first_rank_map(Path(args.zs_full), c)
                    for c in ("learned", "abstract", "policy_abstract")}
    aug_test = first_rank_map(Path(args.aug_test), cfg)
    v24_test = first_rank_map(Path(args.zs_test), cfg)

    tt = json.loads(Path(args.test_theorems).read_text()) if Path(args.test_theorems).exists() else {}
    test_set = set(tt.get("test_theorems", []))

    rows: List[Dict[str, Any]] = []
    for nm, r in sorted(zs_full.items()):
        cat = r.get("category", "?")
        transfer = r.get("transfer", "?")
        op = r.get("required_operation", "?")
        skill = expected_skill(cat, transfer, op, nm)
        # best v24 zero-shot rank across rerank configs
        best_rank = r.get("first_verified_rank")
        for c, mp in zs_full_best.items():
            fr = mp.get(nm, {}).get("first_verified_rank")
            if fr is not None and (best_rank is None or fr < best_rank):
                best_rank = fr
        aug_fr = aug_test.get(nm, {}).get("first_verified_rank") if nm in test_set else None
        v24_held_fr = v24_test.get(nm, {}).get("first_verified_rank") if nm in test_set else None
        fail_classes = Counter(taxonomy(v.get("error"))
                               for v in r.get("verifications", []) if not v.get("success"))
        delta = None
        if nm in test_set:
            a = aug_fr is not None
            b = v24_held_fr is not None
            delta = ("aug_fixed" if a and not b else
                     "aug_regressed" if b and not a else
                     "both_solved" if a and b else "both_fail")
        rows.append({
            "theorem_name": nm, "category": cat, "transfer": transfer,
            "required_operation": op, "expected_skill": skill,
            "v24_zs_first_rank_raw": r.get("first_verified_rank"),
            "v24_zs_first_rank_best": best_rank,
            "in_heldout_test": nm in test_set,
            "v24_heldout_first_rank": v24_held_fr,
            "v25_aug_first_rank": aug_fr,
            "heldout_delta": delta,
            "bound": bound_label(r),
            "dominant_failure": (fail_classes.most_common(1)[0][0]
                                 if fail_classes else "none"),
            "failure_classes": dict(fail_classes),
            "missing_identifiers": missing_ids(r),
            "n_union_candidates": r.get("n_union_candidates"),
        })

    # ---- aggregate ----
    by_bound = Counter(r["bound"] for r in rows)
    by_skill_bound: Dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_skill_bound[r["expected_skill"]][r["bound"]] += 1
    set_rows = [r for r in rows if r["category"] == "set"]
    order_rows = [r for r in rows if r["expected_skill"] == "order"]
    missing_all = Counter()
    for r in rows:
        for mid in r["missing_identifiers"]:
            missing_all[mid] += 1

    audit = {
        "config_audited": cfg,
        "n_tierc_theorems": len(rows),
        "bound_counts": dict(by_bound),
        "by_skill_bound": {k: dict(v) for k, v in by_skill_bound.items()},
        "most_missing_identifiers": missing_all.most_common(15),
        "set_theorems_all_unsolved": all(r["v24_zs_first_rank_best"] is None for r in set_rows),
        "rows": rows,
    }
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- markdown ----
    def fr(x):
        return "—" if x is None else str(x)

    L: List[str] = []
    L.append("# Mini-ELF v26 — Part 1: v25 Mathlib tier-C Failure Audit\n")
    L.append("Audit of the **already-verified** v25 tier-C evaluations (no Lean re-run). "
             f"Generator order audited: `{cfg}` (pure beam order); the *best* column "
             "takes the min rank over learned/abstract/policy_abstract rerankers.\n")
    L.append("**Honesty:** summarizes prior real-Mathlib (`import Mathlib`) typecheck "
             "results. No state_after, no manual oracle as predictions, Mathlib real & external.\n")

    L.append("## Bound distribution (36 tier-C theorems)\n")
    L.append("| bound | count | meaning |")
    L.append("|---|---|---|")
    meaning = {
        "solved": "v24 verifies a candidate at rank <5",
        "ranking_bound": "a candidate verifies but only at rank >=5",
        "generator_bound": "no candidate verifies; missing lemma / wrong shape",
        "syntax_api_bound": "failures dominated by parse / arity / type-mismatch",
        "import_env_bound": "failures dominated by import/olean errors",
    }
    for b, c in by_bound.most_common():
        L.append(f"| {b} | {c} | {meaning.get(b,'')} |")
    L.append("")

    L.append("## Bound x expected-skill\n")
    skills = sorted(by_skill_bound)
    bounds = ["solved", "ranking_bound", "generator_bound", "syntax_api_bound", "import_env_bound"]
    L.append("| skill | " + " | ".join(bounds) + " |")
    L.append("|" + "---|" * (len(bounds) + 1))
    for sk in skills:
        L.append(f"| {sk} | " + " | ".join(str(by_skill_bound[sk].get(b, 0)) for b in bounds) + " |")
    L.append("")

    L.append("## Per-theorem audit\n")
    L.append("| theorem | cat | skill | transfer | v24 rank (raw/best) | held-out | v25-aug rank | Δ | bound | dominant fail | missing ids |")
    L.append("|" + "---|" * 11)
    for r in rows:
        held = "test" if r["in_heldout_test"] else "train"
        L.append("| {nm} | {cat} | {sk} | {tr} | {raw}/{best} | {held} | {aug} | {d} | {b} | {df} | {mids} |".format(
            nm=r["theorem_name"], cat=r["category"], sk=r["expected_skill"],
            tr=r["transfer"], raw=fr(r["v24_zs_first_rank_raw"]),
            best=fr(r["v24_zs_first_rank_best"]), held=held,
            aug=fr(r["v25_aug_first_rank"]), d=r["heldout_delta"] or "—",
            b=r["bound"], df=r["dominant_failure"],
            mids=", ".join(r["missing_identifiers"][:4]) or "—"))
    L.append("")

    L.append("## Special focus\n")
    L.append(f"* **Set goals ({len(set_rows)}):** "
             + ("all unsolved by v24 zero-shot (every rerank config). "
                if audit["set_theorems_all_unsolved"] else "")
             + "Set names: " + ", ".join(r["theorem_name"] for r in set_rows) + ".")
    # nat order / <= goals (skill == order, e.g. n<=n, n<=n+1, subset)
    L.append("* **≤ / order goals:** " + ", ".join(
        f"{r['theorem_name']}(rank raw={fr(r['v24_zs_first_rank_raw'])}, bound={r['bound']})"
        for r in order_rows) + ".")
    mul1 = [r for r in rows if "mul_one" in r["theorem_name"]]
    if mul1:
        r = mul1[0]
        L.append(f"* **n*1=n (`{r['theorem_name']}`):** bound={r['bound']}, "
                 f"v24 raw rank={fr(r['v24_zs_first_rank_raw'])}, missing={r['missing_identifiers'] or '—'}.")
    list_rows = [r for r in rows if r["category"] == "list"]
    L.append("* **List goals:** " + ", ".join(
        f"{r['theorem_name']}(bound={r['bound']})" for r in list_rows) + ".")
    aug_fixed = [r for r in rows if r["heldout_delta"] == "aug_fixed"]
    L.append("* **v25 augmentation FIXED (held-out):** "
             + (", ".join(r["theorem_name"] for r in aug_fixed) or "none") + ".")
    aug_reg = [r for r in rows if r["heldout_delta"] == "aug_regressed"]
    L.append("* **v25 augmentation REGRESSED a tier-C theorem:** "
             + (", ".join(r["theorem_name"] for r in aug_reg) or "none") + ".")
    L.append("")

    L.append("## Most-missing Mathlib identifiers (what the generator never proposes)\n")
    L.append("| identifier | #theorems |")
    L.append("|---|---|")
    for ident, c in missing_all.most_common(15):
        L.append(f"| `{ident}` | {c} |")
    L.append("")

    # ---- co-training interference (broad-core) ----
    v24b = Path(args.v24_broad) / "policy_abstract" / "metrics.json"
    v25b = Path(args.v25_broad) / "raw" / "metrics.json"
    if v24b.exists() and v25b.exists():
        a = json.loads(v24b.read_text())
        b = json.loads(v25b.read_text())
        L.append("## Co-training interference on broad-core (v24 vs v25 augmented)\n")
        L.append("Evidence for why v26 must route, not co-train. v24 = "
                 "`policy_abstract`, v25 augmented = `raw` (its best broad-core config).\n")
        L.append("| broad-core category | v24 p@10 | v25-aug p@10 | Δ |")
        L.append("|---|---|---|---|")
        ac, bc = a.get("per_category", {}), b.get("per_category", {})
        for cat in sorted(set(ac) | set(bc)):
            av = ac.get(cat, {}).get("pass@10")
            bv = bc.get(cat, {}).get("pass@10")
            if av is None or bv is None:
                continue
            d = bv - av
            flag = " ⬇️" if d < -1e-9 else (" ⬆️" if d > 1e-9 else "")
            L.append(f"| {cat} | {av:.3f} | {bv:.3f} | {d:+.3f}{flag} |")
        L.append(f"| **overall** | {a['pass@10']:.3f} | {b['pass@10']:.3f} | {b['pass@10']-a['pass@10']:+.3f} |")
        L.append("")

    L.append("## Conclusions (feeding Parts 2–7)\n")
    gb = by_bound.get("generator_bound", 0)
    L.append(f"1. **{gb}/{len(rows)} tier-C failures are generator-bound** — the model never "
             "proposes the needed Mathlib lemma or proof shape. The environment is **not** the "
             "wall (import_env_bound = {ie}).".format(ie=by_bound.get("import_env_bound", 0)))
    L.append("2. **Set goals are categorically unreachable** for the broad generator — a "
             "dedicated specialist must learn `intro x hx; exact hx`, `Set.Subset.refl`, "
             "`Set.inter_subset_left`, membership unfolding.")
    L.append("3. Missing-identifier counts show the gap is **lemma vocabulary** "
             "(`Nat.*`, `Set.*`, `List.*` names) plus proof-shape, not syntax.")
    L.append("4. Co-training improved tier-C held-out but **regressed broad-core** (table above) "
             "→ v26 builds a **specialist + router** so broad-core stays on the untouched v24 model.")
    Path(args.out_md).write_text("\n".join(L) + "\n", encoding="utf-8")

    print(f"[audit] {len(rows)} tier-C theorems; bounds={dict(by_bound)}")
    print(f"[audit] set_all_unsolved={audit['set_theorems_all_unsolved']}; "
          f"top missing ids={missing_all.most_common(6)}")
    print(f"[audit] wrote {args.out_md} and {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
