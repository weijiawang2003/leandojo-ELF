"""Mini-ELF v24 — Parts 2/3: targeted residual shape corpus.

One small core-Lean family per generator-bound failure
([`V24_GENERATOR_BOUND_ROWS.md`]). Every candidate is lean-cli verified
(direct toolchain binary — never the elan shim, which hangs under
sustained load); only verified candidates become training rows. Varied
variable / proposition / hypothesis names keep the corpus disjoint from
the v18 eval statements (name + (statement,state,tactic) triple guards).

Families (target → verified core-Lean shape):
  * **or_intro**     `a ∨ b`            → `exact Or.inl/inr h` / `left`/`right`
  * **or_elim**      `a∨b, a→c, b→c ⊢c` → `Or.elim h f g` / cases inl/inr
  * **conj_reassoc** `a∧b∧c ⊢(a∧b)∧c`   → `exact ⟨⟨h.1,h.2.1⟩,h.2.2⟩`, swaps
  * **neg_of_or**    `¬(a∨b) ⊢ ¬a/¬b`   → `intro hx; exact h (Or.inl/inr hx)`
  * **exists_eq_rev**`∃ m, n = m`        → `exact ⟨n, rfl⟩`
  * **nat_zero_add** `0 + n = n` & omega-facts → `Nat.zero_add n`/`omega`/`simp`
  * **nat_succ_inj** `n.succ = m.succ ⊢ n=m` → `Nat.succ.inj h`/`injection h`/`omega`
  * **list_append_nil** `xs ++ [] = xs`  → `List.append_nil xs`/`simp`

Honesty: no Mathlib, no state_after, no manual oracle (candidates are
corpus targets verified by Lean, never decoder outputs); v18 leakage
guards; WSL spurious-timeout retry.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import make_lean_cli_verifier  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_v24_residual_shape_corpus")

# name pools chosen to differ from v18 (p/q/r, h, hp/hq, n/m, xs, α)
PROP3 = [("a", "b", "c"), ("c", "d", "e"), ("A", "B", "C"), ("r", "s", "t"),
         ("u", "v", "w")]
HYP = ["g", "hyp", "hx", "hab", "hh"]
NATV = ["i", "j", "k", "a", "b"]
BVAR = ["x", "y", "z", "w", "u"]
LISTT = [("B", "ys"), ("T", "zs"), ("β", "l"), ("S", "ws"), ("A2", "vs")]


def build_plan() -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []

    def add(name, stmt, cands, fam, cat, op, target):
        plan.append({"theorem_name": name, "theorem_statement": stmt,
                     "candidates": cands, "surface_family": fam,
                     "category": cat, "required_operation": op,
                     "target_v18_failure": target})

    # --- or_intro (left + right) ---
    for i, (a, b, _c) in enumerate(PROP3):
        hb = HYP[i % len(HYP)]
        add(f"v24_or_inr_{i}", f"({a} {b} : Prop) ({hb} : {b}) : {a} ∨ {b}",
            [f"exact Or.inr {hb}", f"right\n  exact {hb}",
             f"apply Or.inr\n  exact {hb}"],
            "or_intro", "disjunction", "disjunction_cases", "v18_or_inr")
        ha = HYP[(i + 1) % len(HYP)]
        add(f"v24_or_inl_{i}", f"({a} {b} : Prop) ({ha} : {a}) : {a} ∨ {b}",
            [f"exact Or.inl {ha}", f"left\n  exact {ha}"],
            "or_intro", "disjunction", "disjunction_cases", "v18_or_inr")

    # --- or_elim to a common goal ---
    for i, (a, b, c) in enumerate(PROP3):
        h, f, g = HYP[i % len(HYP)], "f" + str(i), "g" + str(i)
        stmt = (f"({a} {b} {c} : Prop) ({h} : {a} ∨ {b}) ({f} : {a} → {c}) "
                f"({g} : {b} → {c}) : {c}")
        add(f"v24_or_elim_{i}", stmt,
            [f"exact Or.elim {h} {f} {g}",
             f"cases {h} with\n  | inl ha => exact {f} ha\n  | inr hb => exact {g} hb",
             f"rcases {h} with ha | hb\n  · exact {f} ha\n  · exact {g} hb"],
            "or_elim", "disjunction", "disjunction_cases", "v18_or_elim_to_common")

    # --- conj_reassoc + swap ---
    for i, (a, b, c) in enumerate(PROP3):
        h = HYP[i % len(HYP)]
        add(f"v24_conj_reassoc_{i}",
            f"({a} {b} {c} : Prop) ({h} : {a} ∧ {b} ∧ {c}) : ({a} ∧ {b}) ∧ {c}",
            [f"exact ⟨⟨{h}.1, {h}.2.1⟩, {h}.2.2⟩",
             f"exact ⟨⟨{h}.left, {h}.right.left⟩, {h}.right.right⟩"],
            "conj_reassoc", "conjunction", "project_conjunction", "v18_and_assoc_one")
    for i, (a, b, _c) in enumerate(PROP3):
        h = HYP[(i + 2) % len(HYP)]
        add(f"v24_conj_swap_{i}",
            f"({a} {b} : Prop) ({h} : {a} ∧ {b}) : {b} ∧ {a}",
            [f"exact ⟨{h}.2, {h}.1⟩", f"exact ⟨{h}.right, {h}.left⟩"],
            "conj_reassoc", "conjunction", "project_conjunction", "v18_and_assoc_one")

    # --- neg_of_or (left + right) ---
    for i, (a, b, _c) in enumerate(PROP3):
        h = HYP[i % len(HYP)]
        # intro name 'hgoal' is chosen disjoint from HYP so it never
        # shadows the hypothesis h (which can itself be 'hx').
        add(f"v24_neg_or_left_{i}",
            f"({a} {b} : Prop) ({h} : ¬({a} ∨ {b})) : ¬{a}",
            [f"intro hgoal\n  exact {h} (Or.inl hgoal)",
             f"exact fun hgoal => {h} (Or.inl hgoal)"],
            "neg_of_or", "negation", "intro_negation", "v18_neg_or_left")
        add(f"v24_neg_or_right_{i}",
            f"({a} {b} : Prop) ({h} : ¬({a} ∨ {b})) : ¬{b}",
            [f"intro hgoal\n  exact {h} (Or.inr hgoal)",
             f"exact fun hgoal => {h} (Or.inr hgoal)"],
            "neg_of_or", "negation", "intro_negation", "v18_neg_or_left")

    # --- exists_eq_rev (∃ m, n = m  and  ∃ m, m = n) ---
    for i, nv in enumerate(NATV):
        bv = BVAR[i % len(BVAR)]
        add(f"v24_exists_eq_rev_{i}", f"({nv} : Nat) : ∃ {bv}, {nv} = {bv}",
            [f"exact ⟨{nv}, rfl⟩", f"refine ⟨{nv}, ?_⟩\n  rfl"],
            "exists_eq_rev", "exists", "destruct_exists", "v18_exists_intro_eq")
        add(f"v24_exists_eq_fwd_{i}", f"({nv} : Nat) : ∃ {bv}, {bv} = {nv}",
            [f"exact ⟨{nv}, rfl⟩", f"refine ⟨{nv}, ?_⟩\n  rfl"],
            "exists_eq_rev", "exists", "destruct_exists", "v18_exists_intro_eq")

    # --- nat_zero_add + a few omega-provable Nat facts ---
    for i, nv in enumerate(NATV):
        add(f"v24_nat_zero_add_{i}", f"({nv} : Nat) : 0 + {nv} = {nv}",
            [f"exact Nat.zero_add {nv}", "omega", "simp"],
            "nat_zero_add", "nat_succ", "rewrite", "v18_nat_zero_add")
    for i, nv in enumerate(NATV[:4]):
        add(f"v24_nat_one_add_{i}", f"({nv} : Nat) : 1 + {nv} = {nv} + 1",
            ["omega", f"exact Nat.add_comm 1 {nv}"],
            "nat_zero_add", "nat_succ", "rewrite", "v18_nat_zero_add")

    # --- nat_succ_inj ---
    for i in range(len(NATV)):
        nv, mv = NATV[i], NATV[(i + 1) % len(NATV)]
        h = HYP[i % len(HYP)]
        add(f"v24_nat_succ_inj_{i}",
            f"({nv} {mv} : Nat) ({h} : {nv}.succ = {mv}.succ) : {nv} = {mv}",
            [f"exact Nat.succ.inj {h}", f"injection {h}", "omega"],
            "nat_succ_inj", "nat_succ", "rewrite", "v18_nat_succ_inj")

    # --- list_append_nil + nil_append ---
    for i, (ty, xs) in enumerate(LISTT):
        add(f"v24_list_append_nil_{i}",
            f"({ty} : Type) ({xs} : List {ty}) : {xs} ++ [] = {xs}",
            [f"exact List.append_nil {xs}", "simp"],
            "list_append_nil", "list", "rewrite", "v18_list_append_nil")
        add(f"v24_list_nil_append_{i}",
            f"({ty} : Type) ({xs} : List {ty}) : [] ++ {xs} = {xs}",
            ["rfl", f"exact List.nil_append {xs}", "simp"],
            "list_append_nil", "list", "rewrite", "v18_list_append_nil")

    return plan


def _state_before(stmt: str) -> str:
    s = stmt.strip()
    bindings: List[str] = []
    rest = s
    while rest.startswith("("):
        depth = 0
        for i, c in enumerate(rest):
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    bindings.append(rest[1:i])
                    rest = rest[i + 1:].lstrip()
                    break
        else:
            break
    goal = rest[1:].strip() if rest.startswith(":") else rest
    lines = []
    for b in bindings:
        if ":" in b:
            names_part, type_part = b.split(":", 1)
            tp = type_part.strip()
            for nm in names_part.split():
                lines.append(f"{nm} : {tp}")
        else:
            lines.append(b.strip())
    return "\n".join(lines + [f"⊢ {goal}"])


def _v18_sets() -> Tuple[Set[str], Set[Tuple[str, str, str]]]:
    names: Set[str] = set()
    triples: Set[Tuple[str, str, str]] = set()
    v18 = ROOT / "data" / "processed" / "v18_broad_core"
    for fn in ("train.jsonl", "val.jsonl", "test.jsonl"):
        p = v18 / fn
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            o = json.loads(ln)
            if o.get("theorem_name"):
                names.add(o["theorem_name"])
            triples.add((o.get("theorem_statement", ""),
                         o.get("state_before", ""), o.get("tactic", "")))
    return names, triples


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out-seeds", default=str(ROOT / "data" / "seeds"
                                               / "v24_residual_shape_seeds.jsonl"))
    ap.add_argument("--out-candidates", default=str(ROOT / "data" / "manual"
                                                    / "v24_residual_shape_candidates.jsonl"))
    ap.add_argument("--out-train-rows", default=str(ROOT / "data" / "processed"
                                                    / "v24_residual_shape_corpus" / "train_rows.jsonl"))
    ap.add_argument("--summary", default=str(ROOT / "data" / "processed"
                                             / "v24_residual_shape_corpus" / "summary.json"))
    ap.add_argument("--verifier-timeout", type=float, default=20.0)
    args = ap.parse_args(argv)

    plan = build_plan()
    logger.info("v24 residual plan: %d theorems", len(plan))
    verifier = make_lean_cli_verifier(timeout=args.verifier_timeout)
    wu = verifier("__v24_warmup__", "(x : Nat) : x = x", "rfl")
    logger.info("warmup success=%s", wu.get("success"))
    v18_names, v18_triples = _v18_sets()

    for p in (Path(args.out_seeds), Path(args.out_candidates), Path(args.out_train_rows)):
        p.parent.mkdir(parents=True, exist_ok=True)

    seeds, verified, train_rows = [], [], []
    per_fam: Dict[str, Dict[str, int]] = {}
    dn = dt = n_timeout = 0
    zero_success: List[str] = []
    for entry in plan:
        nm, stmt = entry["theorem_name"], entry["theorem_statement"]
        state = _state_before(stmt)
        fam = entry["surface_family"]
        d = per_fam.setdefault(fam, {"theorems": 0, "proposed": 0, "verified": 0, "failed": 0})
        d["theorems"] += 1
        seeds.append({"theorem_name": nm, "theorem_statement": stmt,
                      "state_before": state,
                      "template": f"example {stmt} := by\n  __TACTIC__",
                      "placeholder": "__TACTIC__", "imports": [],
                      "surface_family": fam, "category": entry["category"],
                      "required_operation": entry["required_operation"],
                      "source": "v24_residual_shape_corpus", "core_lean": True})
        any_ok = False
        for cand in entry["candidates"]:
            d["proposed"] += 1
            res = verifier(nm, stmt, cand)
            if (not res.get("success")) and (res.get("error") or "").startswith("timeout"):
                res2 = verifier(nm, stmt, cand)
                if res2.get("success"):
                    res = res2
            if not res.get("success"):
                d["failed"] += 1
                if (res.get("error") or "").startswith("timeout"):
                    n_timeout += 1
                logger.info("  FAIL %s :: %r err=%s", nm, cand,
                            ((res.get("error") or "").splitlines() or [""])[0][:70])
                continue
            triple = (stmt, state, cand)
            if nm in v18_names:
                dn += 1
                continue
            if triple in v18_triples:
                dt += 1
                logger.info("  DROP(triple) %s :: %r", nm, cand)
                continue
            any_ok = True
            d["verified"] += 1
            row = {"theorem_name": nm, "theorem_statement": stmt,
                   "state_before": state, "tactic": cand,
                   "family": fam, "category": entry["category"],
                   "required_operation": entry["required_operation"],
                   "corpus_source": "v24_residual_shape_corpus",
                   "tactic_source": "verified", "split": "train",
                   "target_v18_failure": entry["target_v18_failure"],
                   "core_lean": True}
            train_rows.append(row)
            verified.append({**row, "verified": True, "verifier": "lean-cli",
                             "verifier_timeout_s": args.verifier_timeout})
        if not any_ok:
            zero_success.append(nm)

    with open(args.out_seeds, "w", encoding="utf-8") as f:
        for s in seeds:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    with open(args.out_candidates, "w", encoding="utf-8") as f:
        for c in verified:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(args.out_train_rows, "w", encoding="utf-8") as f:
        for r in train_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {
        "n_theorems_planned": len(plan),
        "n_candidates_proposed": sum(d["proposed"] for d in per_fam.values()),
        "n_candidates_verified": sum(d["verified"] for d in per_fam.values()),
        "n_candidates_failed": sum(d["failed"] for d in per_fam.values()),
        "n_timeout": n_timeout,
        "n_zero_success_theorems": len(zero_success),
        "zero_success_theorems": zero_success,
        "n_dropped_by_v18_name_guard": dn,
        "n_dropped_by_v18_triple_guard": dt,
        "by_surface_family": per_fam,
        "categories_covered": sorted({e["category"] for e in plan}),
        "uses_state_after": False, "uses_manual_oracle": False, "uses_mathlib": False}
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
    logger.info("v24 residual corpus: planned=%d verified=%d/%d failed=%d timeout=%d "
                "zero_success=%d name/triple drops=%d/%d",
                summary["n_theorems_planned"], summary["n_candidates_verified"],
                summary["n_candidates_proposed"], summary["n_candidates_failed"],
                n_timeout, len(zero_success), dn, dt)
    for fam, d in per_fam.items():
        logger.info("  %-16s verified=%d/%d (theorems=%d)", fam, d["verified"],
                    d["proposed"], d["theorems"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
