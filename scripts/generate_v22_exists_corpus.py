"""Mini-ELF v22 — Part 3b: generate the exists corpus.

The exists failure audit ([`V22_EXISTS_FAILURE_AUDIT.md`]) showed the
v18 exists category needs witness-introduction (`exact ⟨k, h⟩`),
reflexive-witness (`exact ⟨k, rfl⟩`), relabel (`exact h` /
reconstruct), and compose (`cases h with | intro ...`) shapes — all
under-represented in the v21 pool. This corpus supplies them with
varied witnesses and predicate names so a single model can learn
witness-copy without overfitting to a fixed literal set.

Shape families (core Lean, no Mathlib):

  1. **exists_intro_witness**  ``(P : Nat → Prop) (h : P 3) : ∃ n, P n``
                               → ``exact ⟨3, h⟩``
  2. **exists_eq_witness**     ``: ∃ n : Nat, n = 3`` → ``exact ⟨3, rfl⟩``
  3. **exists_reconstruct_var**``(m : Nat) : ∃ n : Nat, n = m``
                               → ``exact ⟨m, rfl⟩``
  4. **exists_relabel**        ``(P : Nat → Prop) (h : ∃ n, P n) : ∃ m, P m``
                               → ``exact h`` (defeq) and
                                 ``cases h with | intro n hn => exact ⟨n, hn⟩``
  5. **exists_elim_prop**      ``(r : Prop) (h : ∃ _ : Nat, r) : r``
                               → ``cases h with | intro n hr => exact hr``
  6. **exists_compose**        ``(P Q : Nat → Prop) (h : ∃ n, P n)
                                  (hpq : ∀ n, P n → Q n) : ∃ n, Q n``
                               → ``cases h with | intro n hn => exact ⟨n, hpq n hn⟩``

Honesty: no Mathlib; every candidate lean-cli verified (direct
``lean``); no state_after; no manual oracle; v18 leakage guards
(capital ``P``/``Q`` predicate names disjoint from v18's lowercase
``p``/``q``; triple guard catches any overlap). WSL spurious-timeout
retry.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import make_lean_cli_verifier  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_v22_exists_corpus")

PREDS = ("P", "Q", "R", "Pr", "Phi", "Psi")
PRED_PAIRS = (("P", "Q"), ("R", "S"), ("Pr", "Qr"), ("Phi", "Psi"))
WITNESSES = ("0", "1", "2", "3", "5", "7", "11", "42")
HYPS = ("h", "hp", "hpf", "hwit", "hex")
VARS = ("m", "k", "j", "x")


def build_plan() -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []

    # 1 — witness intro from hypothesis.
    for P in PREDS[:5]:
        for w in WITNESSES:
            for hyp in HYPS[:3]:
                stmt = f"({P} : Nat → Prop) ({hyp} : {P} {w}) : ∃ n, {P} n"
                plan.append({
                    "theorem_name": f"v22_ex_intro_{P}_{w}_{hyp}",
                    "theorem_statement": stmt,
                    "candidates": [f"exact ⟨{w}, {hyp}⟩",
                                   f"refine ⟨{w}, ?_⟩\n  exact {hyp}",
                                   f"exact Exists.intro {w} {hyp}"],
                    "surface_family": "exists_intro_witness",
                })

    # 2 — reflexive witness (literal).
    for w in WITNESSES:
        stmt = f": ∃ n : Nat, n = {w}"
        plan.append({
            "theorem_name": f"v22_ex_eq_{w}",
            "theorem_statement": stmt,
            "candidates": [f"exact ⟨{w}, rfl⟩", f"refine ⟨{w}, ?_⟩\n  rfl"],
            "surface_family": "exists_eq_witness",
        })

    # 3 — reconstruct with bound variable.
    for var in VARS:
        stmt = f"({var} : Nat) : ∃ n : Nat, n = {var}"
        plan.append({
            "theorem_name": f"v22_ex_recon_{var}",
            "theorem_statement": stmt,
            "candidates": [f"exact ⟨{var}, rfl⟩", f"refine ⟨{var}, ?_⟩\n  rfl"],
            "surface_family": "exists_reconstruct_var",
        })

    # 4 — relabel.
    for P in PREDS[:5]:
        for hyp in HYPS[:3]:
            stmt = f"({P} : Nat → Prop) ({hyp} : ∃ n, {P} n) : ∃ m, {P} m"
            plan.append({
                "theorem_name": f"v22_ex_relabel_{P}_{hyp}",
                "theorem_statement": stmt,
                "candidates": [
                    f"exact {hyp}",
                    f"cases {hyp} with\n  | intro n hn => exact ⟨n, hn⟩",
                    f"rcases {hyp} with ⟨n, hn⟩\n  exact ⟨n, hn⟩",
                ],
                "surface_family": "exists_relabel",
            })

    # 5 — elimination to a Prop.
    for hyp in HYPS[:3]:
        for rn in ("r", "s", "goal"):
            stmt = f"({rn} : Prop) ({hyp} : ∃ _ : Nat, {rn}) : {rn}"
            plan.append({
                "theorem_name": f"v22_ex_elim_{rn}_{hyp}",
                "theorem_statement": stmt,
                "candidates": [
                    f"cases {hyp} with\n  | intro n hr => exact hr",
                    f"rcases {hyp} with ⟨n, hr⟩\n  exact hr",
                ],
                "surface_family": "exists_elim_prop",
            })

    # 6 — compose.
    for P, Q in PRED_PAIRS:
        for hyp, hpq in (("h", "hpq"), ("hex", "hall"), ("hp", "himp")):
            stmt = (f"({P} {Q} : Nat → Prop) ({hyp} : ∃ n, {P} n) "
                    f"({hpq} : ∀ n, {P} n → {Q} n) : ∃ n, {Q} n")
            plan.append({
                "theorem_name": f"v22_ex_compose_{P}_{Q}_{hyp}_{hpq}",
                "theorem_statement": stmt,
                "candidates": [
                    f"cases {hyp} with\n  | intro n hn => exact ⟨n, {hpq} n hn⟩",
                    f"rcases {hyp} with ⟨n, hn⟩\n  exact ⟨n, {hpq} n hn⟩",
                ],
                "surface_family": "exists_compose",
            })

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
    for fname in ("train.jsonl", "val.jsonl", "test.jsonl"):
        p = v18 / fname
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            s = ln.strip()
            if not s:
                continue
            o = json.loads(s)
            if o.get("theorem_name"):
                names.add(o["theorem_name"])
            triples.add((o.get("theorem_statement", ""),
                         o.get("state_before", ""), o.get("tactic", "")))
    return names, triples


def verify_and_persist(plan, *, verifier_timeout, warmup,
                       out_seeds, out_candidates, out_train_rows):
    for p in (out_seeds, out_candidates, out_train_rows):
        p.parent.mkdir(parents=True, exist_ok=True)
    verifier = make_lean_cli_verifier(timeout=verifier_timeout)
    if warmup:
        wu = verifier("__v22_ex_warmup__", "(x : Nat) : x = x", "rfl")
        logger.info("warmup success=%s", wu.get("success"))
    v18_names, v18_triples = _v18_sets()

    seeds, verified, train_rows = [], [], []
    per_family: Dict[str, Dict[str, int]] = {}
    dn = dt = 0
    for entry in plan:
        nm, stmt = entry["theorem_name"], entry["theorem_statement"]
        state = _state_before(stmt)
        fam = entry["surface_family"]
        per_family.setdefault(fam, {"proposed": 0, "verified": 0,
                                    "failed": 0, "theorems": 0})
        per_family[fam]["theorems"] += 1
        seeds.append({
            "theorem_name": nm, "theorem_statement": stmt,
            "state_before": state,
            "template": f"example {stmt} := by\n  __TACTIC__",
            "placeholder": "__TACTIC__", "imports": [],
            "surface_family": fam, "category": "exists",
            "required_operation": "destruct_exists",
            "source": "v22_exists_corpus", "core_lean": True})
        for cand in entry["candidates"]:
            per_family[fam]["proposed"] += 1
            try:
                res = verifier(nm, stmt, cand)
                if (not res.get("success")
                        and (res.get("error") or "").startswith("timeout")):
                    res2 = verifier(nm, stmt, cand)
                    if res2.get("success"):
                        res = res2
            except Exception as exc:  # noqa: BLE001
                res = {"success": False, "error": f"verifier_exception:{exc}"}
            if not res.get("success"):
                per_family[fam]["failed"] += 1
                err = ((res.get("error") or "").splitlines() or [""])[0]
                logger.info("  FAIL %s :: %r  err=%s", nm, cand, err[:80])
                continue
            triple = (stmt, state, cand)
            if nm in v18_names:
                dn += 1
                continue
            if triple in v18_triples:
                dt += 1
                logger.info("  DROP(triple) %s :: %r", nm, cand)
                continue
            per_family[fam]["verified"] += 1
            row = {"theorem_name": nm, "theorem_statement": stmt,
                   "state_before": state, "tactic": cand, "family": fam,
                   "category": "exists", "required_operation": "destruct_exists",
                   "corpus_source": "v22_exists_corpus", "tactic_source": "verified",
                   "split": "train", "regime": "v22_exists_redundancy",
                   "redundancy_group": fam, "core_lean": True}
            verified.append({**row, "verified": True, "verifier": "lean-cli",
                             "verifier_timeout_s": verifier_timeout})
            train_rows.append(row)

    with out_seeds.open("w", encoding="utf-8") as f:
        for s in seeds:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    with out_candidates.open("w", encoding="utf-8") as f:
        for c in verified:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with out_train_rows.open("w", encoding="utf-8") as f:
        for r in train_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return {
        "n_theorems_planned": len(plan),
        "n_candidates_proposed": sum(d["proposed"] for d in per_family.values()),
        "n_candidates_verified": sum(d["verified"] for d in per_family.values()),
        "n_candidates_failed": sum(d["failed"] for d in per_family.values()),
        "n_dropped_by_v18_name_guard": dn,
        "n_dropped_by_v18_triple_guard": dt,
        "by_surface_family": {f: {"theorems": d["theorems"],
                                  "proposed": d["proposed"],
                                  "verified": d["verified"],
                                  "failed": d["failed"]}
                              for f, d in per_family.items()},
        "uses_state_after": False, "uses_manual_oracle": False}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out-seeds", default=str(ROOT / "data" / "seeds" / "v22_exists_seeds.jsonl"))
    ap.add_argument("--out-candidates", default=str(ROOT / "data" / "manual" / "v22_exists_candidates.jsonl"))
    ap.add_argument("--out-train-rows", default=str(ROOT / "data" / "processed" / "v22_exists_corpus" / "train_rows.jsonl"))
    ap.add_argument("--summary", default=str(ROOT / "data" / "processed" / "v22_exists_corpus" / "summary.json"))
    ap.add_argument("--verifier-timeout", type=float, default=30.0)
    ap.add_argument("--no-warmup", dest="warmup", action="store_false")
    ap.set_defaults(warmup=True)
    args = ap.parse_args(argv)

    plan = build_plan()
    logger.info("v22 exists plan: %d theorems", len(plan))
    summary = verify_and_persist(
        plan, verifier_timeout=args.verifier_timeout, warmup=args.warmup,
        out_seeds=Path(args.out_seeds), out_candidates=Path(args.out_candidates),
        out_train_rows=Path(args.out_train_rows))
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
    logger.info("v22 exists corpus: planned=%d verified=%d/%d name/triple drops=%d/%d",
                summary["n_theorems_planned"], summary["n_candidates_verified"],
                summary["n_candidates_proposed"],
                summary["n_dropped_by_v18_name_guard"],
                summary["n_dropped_by_v18_triple_guard"])
    for fam, d in summary["by_surface_family"].items():
        logger.info("  %s verified=%d/%d", fam, d["verified"], d["proposed"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
