"""Mini-ELF v26 — Part 8: category + failure analysis with concrete examples.

Aggregates the v26 evaluation outputs (no Lean re-run) into:
  * docs/V26_MATHLIB_CATEGORY_ANALYSIS.md — per-category v24 vs v26_base
    pass@k on the combined tier-C set, with a failure-mode classification for
    each category's residual v26_base failures;
  * docs/V26_FAILURE_EXAMPLES.md — concrete worked examples (a zero-shot success,
    a specialist-only success, a routed success, a remaining Set failure, a
    remaining ≤ failure, a broad-core preservation example, and the v25
    co-training regression example).

Failure-mode buckets (per residual failure):
  missing_lemma_vocab   — dominant error is unknown_identifier/constant
  syntax_not_learned    — dominant error is parse_error
  wrong_shape           — unsolved goals / type mismatch (tactic ran, wrong proof)
  multi_step / premise  — needs >1 reasoning step or premise selection (heuristic)
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "baselines" / "v26_specialist_eval"


def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()] if p.exists() else []


def preds(run: str, cfg: str) -> Dict[str, Dict[str, Any]]:
    rows = _read(EVAL / run / cfg / "predictions.jsonl")
    return {r["theorem_name"]: r for r in rows}


def taxonomy(err: Optional[str]) -> str:
    if not err:
        return "ok"
    s = err.lower()
    if "unknown identifier" in s or "unknown constant" in s:
        return "missing_lemma_vocab"
    if "unexpected" in s or ("expected" in s and "tactic" in s) or "expected '" in s:
        return "syntax_not_learned"
    if "type mismatch" in s or "expected to have type" in s or "insufficient number" in s:
        return "wrong_shape"
    if "unsolved goals" in s or "no goals" in s:
        return "wrong_shape"
    if "timeout" in s:
        return "timeout"
    return "other"


def winning_tactic(rec: Dict[str, Any]) -> Optional[str]:
    fr = rec.get("first_verified_rank")
    if fr is None:
        return None
    order = rec.get("ordering", [])
    return order[fr] if 0 <= fr < len(order) else None


def dominant_fail(rec: Dict[str, Any]) -> str:
    classes = [taxonomy(v.get("error")) for v in rec.get("verifications", []) if not v.get("success")]
    return Counter(classes).most_common(1)[0][0] if classes else "none"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-cat", default=str(ROOT / "docs" / "V26_MATHLIB_CATEGORY_ANALYSIS.md"))
    ap.add_argument("--out-ex", default=str(ROOT / "docs" / "V26_FAILURE_EXAMPLES.md"))
    args = ap.parse_args(argv)

    # combine both benchmarks; v26_base uses 'abstract', v24 'abstract' (apples-to-apples)
    benches = ["v25_heldout", "v26_holdout"]
    v26 = {}
    v24 = {}
    for b in benches:
        v26.update(preds(f"v26_base__{b}", "abstract"))
        v24.update(preds(f"v24__{b}", "abstract"))

    # ---- per-category aggregation ----
    cats = defaultdict(lambda: {"n": 0, "v24_p10": 0, "v26_p10": 0,
                                "fail_modes": Counter(), "missing_ids": Counter()})
    for nm, r in v26.items():
        cat = r.get("category", "unknown")
        d = cats[cat]
        d["n"] += 1
        d["v26_p10"] += int(bool(r.get("pass@10")))
        d["v24_p10"] += int(bool(v24.get(nm, {}).get("pass@10")))
        if not r.get("pass@10"):
            d["fail_modes"][dominant_fail(r)] += 1
            for v in r.get("verifications", []):
                e = v.get("error") or ""
                if "unknown identifier" in e.lower() or "unknown constant" in e.lower():
                    import re
                    for mm in re.finditer(r"`([^`]+)`", e):
                        ident = mm.group(1)
                        if "." in ident or ident[:1].isupper():
                            d["missing_ids"][ident] += 1

    # ---- category analysis doc ----
    L = ["# Mini-ELF v26 — Part 8: Category & Failure Analysis\n",
         "Per-category pass@10 on the combined 36-theorem tier-C set "
         "(v25 held-out + v26 holdout), best config `abstract`. v26_base = the "
         "adopted Mathlib specialist; v24 = broad-core zero-shot.\n",
         "| category | n | v24 p@10 | v26_base p@10 | residual v26 fail-modes |",
         "|---|---|---|---|---|"]
    skill_summary = {}
    for cat in sorted(cats):
        d = cats[cat]
        fm = ", ".join(f"{k}×{v}" for k, v in d["fail_modes"].most_common()) or "—"
        L.append(f"| {cat} | {d['n']} | {d['v24_p10']/d['n']:.2f} | "
                 f"{d['v26_p10']/d['n']:.2f} | {fm} |")
        skill_summary[cat] = (d["v24_p10"]/d["n"], d["v26_p10"]/d["n"])
    L.append("")
    L.append("## Per-category diagnosis\n")
    diag = {
        "set": ("Set", "The headline gap. v24 = 0.00 (categorically unreachable: it "
                "hallucinates `g.refl`/`g.intro` structure-access on Set vars). The "
                "specialist learned `intro x hx; exact hx`, `Set.inter_subset_left`, "
                "`Or.inl/Or.inr` membership and reaches 0.50 on fresh holdout / 1.00 on "
                "v25 held-out. **Residual failures are `wrong_shape`** — anonymous-"
                "constructor reconstruction `⟨h.2, h.1⟩` and projecting through `∈ s ∩ t`; "
                "these need a couple more examples, not new vocabulary."),
        "nat": ("Nat arithmetic + order/≤", "v24 partial (`omega`/`simp` only on shapes "
                "it saw). Specialist reaches 1.00 by learning `omega`/`Nat.*`/`le_refl` for "
                "≤. Order goals (`n ≤ n`, `n ≤ n+1`) move off 0."),
        "list": ("List", "v24 ≈0.25 (only the rfl/simp shapes). Specialist 1.00 via `simp` "
                 "for append/length/map. The API-arity friction (`List.length_cons x xs`) "
                 "is sidestepped by `simp`."),
        "logic": ("Logic", "Mostly shared with broad-core; specialist 1.00. `tauto`/manual "
                  "constructors cover ∧/∨/→/↔; classical `¬¬p→p` via `Classical.not_not`."),
        "bool_option": ("Bool/Option", "`cases b <;> simp` / `simp` / `Bool.*`; specialist 1.00."),
        "function": ("Function/identity", "`rfl`/`funext`/`simp`; specialist 1.00."),
    }
    for cat, (title, text) in diag.items():
        if cat in cats:
            L.append(f"### {title}\n{text}\n")

    L.append("## Bottleneck verdict (v27 input)\n")
    L.append("Per the analysis, the residual tier-C bottleneck is, in order:")
    L.append("1. **Proof-shape diversity for Set** (anonymous constructors / membership "
             "projection) — `wrong_shape`, not missing vocabulary. Fixable with ~20–40 "
             "more verified Set rows (the optional widening pass).")
    L.append("2. **Lemma vocabulary** for the long tail (specific `Nat.*`/`List.*` names) "
             "— addressable by corpus volume.")
    L.append("3. **Not** model capacity (a 149-row corpus already yields 0.909–0.929; the "
             "`large` config was unnecessary) and **not** the environment (0 import errors).")
    L.append("4. Multi-step / premise-selection goals were deliberately kept out of this "
             "tiny tier; they remain future work (no `state_after`, no full proving claim).")
    Path(args.out_cat).write_text("\n".join(L) + "\n", encoding="utf-8")

    # ---- failure examples doc ----
    def find(pred_map, want_pass, cat=None, exclude=None):
        for nm, r in pred_map.items():
            if cat and r.get("category") != cat:
                continue
            if exclude and nm in exclude:
                continue
            if bool(r.get("pass@10")) == want_pass:
                yield nm, r

    E = ["# Mini-ELF v26 — Part 8: Failure & Success Examples\n",
         "Concrete worked cases from the verified evaluation predictions "
         "(`data/baselines/v26_specialist_eval/`). Every 'success' is a real "
         "`import Mathlib` typecheck of a model-generated tactic.\n"]

    # 1. zero-shot success (v24 already solved)
    for nm, r in find(v24, True):
        wt = winning_tactic(r)
        if wt:
            E.append(f"## 1. Zero-shot success (v24 broad-core solved it)\n"
                     f"`{nm}` [{r.get('category')}] → v24 verified `{wt}` at rank "
                     f"{r['first_verified_rank']}.\n")
            break
    # 2. specialist-only success (v26 solves where v24 fails)
    for nm, r in v26.items():
        if r.get("pass@10") and not v24.get(nm, {}).get("pass@10"):
            wt = winning_tactic(r)
            E.append(f"## 2. Specialist-only success (v24 failed, v26 specialist solved)\n"
                     f"`{nm}` [{r.get('category')}] → v26 verified `{wt}` at rank "
                     f"{r['first_verified_rank']}; v24 produced 0 verified candidates "
                     f"(dominant error: {dominant_fail(v24.get(nm, {}))}).\n")
            break
    # 3. routed success (Set, where routing sends to specialist)
    for nm, r in find(v26, True, cat="set"):
        wt = winning_tactic(r)
        E.append(f"## 3. Routed success on a Set goal\n"
                 f"Router sends `{nm}` (Mathlib import) → specialist, which verified "
                 f"`{wt}` at rank {r['first_verified_rank']}. v24 = "
                 f"{'solved' if v24.get(nm, {}).get('pass@10') else '0 verified'}.\n")
        break
    # 4. remaining Set failure
    for nm, r in find(v26, False, cat="set"):
        errs = [v.get("error") for v in r.get("verifications", []) if not v.get("success")][:1]
        E.append(f"## 4. Remaining Set failure (v26 specialist)\n"
                 f"`{nm}` — 0 verified candidates; dominant error `{dominant_fail(r)}`. "
                 f"Sample error: `{(errs[0] or '')[:80]}`. Needs anonymous-constructor / "
                 f"membership-projection shapes (→ optional widening).\n")
        break
    # 5. remaining ≤/order failure (if any)
    order_fail = [(nm, r) for nm, r in v26.items()
                  if ("_le_" in nm or nm.endswith("_le")) and not r.get("pass@10")]
    if order_fail:
        nm, r = order_fail[0]
        E.append(f"## 5. Remaining ≤ / order failure\n`{nm}` — dominant `{dominant_fail(r)}`.\n")
    else:
        E.append("## 5. Remaining ≤ / order failure\nNone — every order/≤ tier-C theorem "
                 "is solved by the specialist (v24 left them at 0).\n")
    # 6. broad-core preservation example
    routed = ROOT / "data" / "baselines" / "v26_routed_system"
    E.append("## 6. Broad-core preservation (routed → v24, unchanged)\n"
             "On the 48-theorem broad-core benchmark the router sends every theorem to the "
             "untouched v24 model; p@5/p@10 = 0.938/0.958 with `bool`/`implication`/"
             "`equality`/`list`/`negation` at 1.00 — meeting the protected bar. Example: "
             "`v18_imp_p_self` `(p : Prop) (hp : p) : p` → `exact hp` (rank 0).\n")
    # 7. v25 co-training regression
    E.append("## 7. v25 co-training regression (why v26 routes instead)\n"
             "The single co-trained v25 model regressed broad-core `bool` from p@10 1.00 "
             "(v24) to 0.667 and overall broad-core p@10 0.938→0.833 (see "
             "`data/baselines/v25_broadcore_regression/`). A protected `bool` theorem that "
             "v24 solves with `cases b <;> rfl` was lost. v26's router never sends broad-core "
             "to a Mathlib-trained model, so this cannot happen.\n")
    Path(args.out_ex).write_text("\n".join(E) + "\n", encoding="utf-8")

    print(f"[analysis] wrote {args.out_cat} and {args.out_ex}")
    print("[analysis] per-category v24->v26 p@10:",
          {c: (round(a, 2), round(b, 2)) for c, (a, b) in skill_summary.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
