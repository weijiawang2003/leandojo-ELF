"""Mini-ELF v21 — Part 2: generate the forall-instantiation corpus.

The v21 regression audit ([`V21_FORALL_REGRESSION_AUDIT.md`]) showed
the v20 broad-plus model **lost the `exact h <arg>` instantiation
schema** from its beam on forall goals — a capacity/distribution
tradeoff after the implication+bool augmentation. This corpus
restores that schema with enough volume and surface variety that a
retrained model re-learns it.

Shape families (all core Lean, no Mathlib):

  1. **forall_inst_literal**  ``(P : Nat → Prop) (h : ∀ n, P n) : P 0``
                              → ``exact h 0`` (literals 0,1,2,3,5,7,13,42)
  2. **forall_inst_var**      ``(P : Nat → Prop) (h : ∀ n, P n) (k : Nat) : P k``
                              → ``exact h k``
  3. **forall_prop**          ``(P : Prop → Prop) (h : ∀ p, P p) (q : Prop) : P q``
                              → ``exact h q``
  4. **forall_arrow_inst**    ``(P Q : Nat → Prop) (h : ∀ n, P n → Q n) : P k → Q k``
                              → ``exact h k`` (matches v18_forall_to_arrow shape)
  5. **forall_inst_compose**  ``(P Q : Nat → Prop) (h : ∀ n, P n → Q n) (hp : P 5) : Q 5``
                              → ``exact h 5 hp`` (the v18-unsolved 2-arg case)

Mixed hypothesis names (``h``, ``hAll``, ``allP``, ``proofAll``,
``hforall``) probe whether Lean accepts them; only verified ones are
kept.

Honesty:
  * No Mathlib; every candidate lean-cli verified (direct ``lean``).
  * No state_after; no manual oracle.
  * v18 leakage guards (name + triple). Predicate names use capital
    ``P``/``Q`` (disjoint from v18's lowercase ``p``/``q``); the triple
    guard catches any accidental overlap (e.g. ``exact h 7``).
  * WSL spurious-timeout retry (one retry before classifying failure).
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
logger = logging.getLogger("generate_v21_forall_corpus")


# Disjoint predicate names (capital — v18 uses lowercase p/q).
PRED_SINGLES: Tuple[str, ...] = ("P", "Q", "R", "Pr", "Pred", "Phi", "Psi")
PRED_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("P", "Q"), ("R", "S"), ("Pr", "Qr"), ("Phi", "Psi"), ("F", "G"),
)
LITERALS: Tuple[str, ...] = ("0", "1", "2", "3", "5", "7", "13", "42")
VAR_NAMES: Tuple[str, ...] = ("k", "m", "j", "i", "x", "y")
FORALL_HYPS: Tuple[str, ...] = ("h", "hAll", "allP", "proofAll", "hforall")
BVAR: Tuple[str, ...] = ("n", "m", "x", "a")


def build_plan() -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []

    # Shape 1 — forall_inst_literal.
    for P in PRED_SINGLES[:5]:
        for hyp in FORALL_HYPS:
            for lit in LITERALS:
                bv = "n"
                stmt = f"({P} : Nat → Prop) ({hyp} : ∀ {bv}, {P} {bv}) : {P} {lit}"
                plan.append({
                    "theorem_name": f"v21_fa_lit_{P}_{hyp}_{lit}",
                    "theorem_statement": stmt,
                    "candidates": [f"exact {hyp} {lit}"],
                    "surface_family": "forall_inst_literal",
                })

    # Shape 2 — forall_inst_var.
    for P in PRED_SINGLES[:5]:
        for hyp in FORALL_HYPS:
            for var in VAR_NAMES[:4]:
                stmt = (f"({P} : Nat → Prop) ({hyp} : ∀ n, {P} n) "
                        f"({var} : Nat) : {P} {var}")
                plan.append({
                    "theorem_name": f"v21_fa_var_{P}_{hyp}_{var}",
                    "theorem_statement": stmt,
                    "candidates": [f"exact {hyp} {var}",
                                   f"apply {hyp}"],
                    "surface_family": "forall_inst_var",
                })

    # Shape 3 — forall over Prop.
    for hyp in FORALL_HYPS:
        for qn in ("q", "r", "s", "prop1"):
            stmt = (f"(P : Prop → Prop) ({hyp} : ∀ p, P p) "
                    f"({qn} : Prop) : P {qn}")
            plan.append({
                "theorem_name": f"v21_fa_prop_{hyp}_{qn}",
                "theorem_statement": stmt,
                "candidates": [f"exact {hyp} {qn}", f"apply {hyp}"],
                "surface_family": "forall_prop",
            })

    # Shape 4 — forall_arrow_inst (matches v18_forall_to_arrow).
    for P, Q in PRED_PAIRS[:4]:
        for hyp in FORALL_HYPS[:3]:
            for lit in ("0", "3", "5", "7"):
                stmt = (f"({P} {Q} : Nat → Prop) "
                        f"({hyp} : ∀ n, {P} n → {Q} n) : {P} {lit} → {Q} {lit}")
                plan.append({
                    "theorem_name": f"v21_fa_arrow_{P}_{Q}_{hyp}_{lit}",
                    "theorem_statement": stmt,
                    "candidates": [f"exact {hyp} {lit}"],
                    "surface_family": "forall_arrow_inst",
                })

    # Shape 5 — forall_inst_compose (2-arg; the v18-unsolved case).
    for P, Q in PRED_PAIRS[:4]:
        for hyp, hp in (("h", "hp"), ("hAll", "hp"), ("h", "hP"),
                        ("hforall", "hp")):
            for lit in ("0", "3", "5", "7"):
                stmt = (f"({P} {Q} : Nat → Prop) "
                        f"({hyp} : ∀ n, {P} n → {Q} n) "
                        f"({hp} : {P} {lit}) : {Q} {lit}")
                plan.append({
                    "theorem_name": f"v21_fa_compose_{P}_{Q}_{hyp}_{hp}_{lit}",
                    "theorem_statement": stmt,
                    "candidates": [
                        f"exact {hyp} {lit} {hp}",
                        f"exact ({hyp} {lit}) {hp}",
                        f"apply {hyp}\n  exact {hp}",
                    ],
                    "surface_family": "forall_inst_compose",
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
    lines: List[str] = []
    for b in bindings:
        if ":" in b:
            names_part, type_part = b.split(":", 1)
            type_str = type_part.strip()
            for nm in names_part.split():
                lines.append(f"{nm} : {type_str}")
        else:
            lines.append(b.strip())
    return "\n".join(lines + [f"⊢ {goal}"])


def _v18_leakage_sets() -> Tuple[Set[str], Set[Tuple[str, str, str]]]:
    names: Set[str] = set()
    triples: Set[Tuple[str, str, str]] = set()
    v18_root = ROOT / "data" / "processed" / "v18_broad_core"
    for fname in ("train.jsonl", "val.jsonl", "test.jsonl"):
        p = v18_root / fname
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
    out_seeds.parent.mkdir(parents=True, exist_ok=True)
    out_candidates.parent.mkdir(parents=True, exist_ok=True)
    out_train_rows.parent.mkdir(parents=True, exist_ok=True)

    verifier = make_lean_cli_verifier(timeout=verifier_timeout)
    if warmup:
        t0 = time.perf_counter()
        wu = verifier("__v21_fa_warmup__", "(x : Nat) : x = x", "rfl")
        logger.info("warmup: success=%s elapsed_ms=%.1f",
                    wu.get("success"), (time.perf_counter() - t0) * 1000.0)

    v18_names, v18_triples = _v18_leakage_sets()

    seeds: List[Dict[str, Any]] = []
    verified: List[Dict[str, Any]] = []
    train_rows: List[Dict[str, Any]] = []
    per_family: Dict[str, Dict[str, int]] = {}
    dropped_by_name = 0
    dropped_by_triple = 0

    for entry in plan:
        nm = entry["theorem_name"]
        stmt = entry["theorem_statement"]
        state = _state_before(stmt)
        fam = entry["surface_family"]
        per_family.setdefault(fam, {"proposed": 0, "verified": 0, "failed": 0,
                                    "theorems": 0})
        per_family[fam]["theorems"] += 1
        seeds.append({
            "theorem_name": nm,
            "theorem_statement": stmt,
            "state_before": state,
            "template": f"example {stmt} := by\n  __TACTIC__",
            "placeholder": "__TACTIC__",
            "imports": [],
            "surface_family": fam,
            "category": "forall",
            "required_operation": "instantiate_forall",
            "source": "v21_forall_corpus",
            "core_lean": True,
        })
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
                dropped_by_name += 1
                continue
            if triple in v18_triples:
                dropped_by_triple += 1
                logger.info("  DROP(triple-leak) %s :: %r", nm, cand)
                continue
            per_family[fam]["verified"] += 1
            row = {
                "theorem_name": nm,
                "theorem_statement": stmt,
                "state_before": state,
                "tactic": cand,
                "family": fam,
                "category": "forall",
                "required_operation": "instantiate_forall",
                "corpus_source": "v21_forall_corpus",
                "tactic_source": "verified",
                "split": "train",
                "regime": "v21_forall_redundancy",
                "redundancy_group": fam,
                "core_lean": True,
            }
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

    summary = {
        "n_theorems_planned": len(plan),
        "n_candidates_proposed": sum(d["proposed"] for d in per_family.values()),
        "n_candidates_verified": sum(d["verified"] for d in per_family.values()),
        "n_candidates_failed": sum(d["failed"] for d in per_family.values()),
        "n_dropped_by_v18_name_guard": dropped_by_name,
        "n_dropped_by_v18_triple_guard": dropped_by_triple,
        "by_surface_family": {
            fam: {"theorems": d["theorems"], "proposed": d["proposed"],
                  "verified": d["verified"], "failed": d["failed"]}
            for fam, d in per_family.items()
        },
        "uses_state_after": False,
        "uses_manual_oracle": False,
    }
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out-seeds",
                    default=str(ROOT / "data" / "seeds"
                                / "v21_forall_seeds.jsonl"))
    ap.add_argument("--out-candidates",
                    default=str(ROOT / "data" / "manual"
                                / "v21_forall_candidates.jsonl"))
    ap.add_argument("--out-train-rows",
                    default=str(ROOT / "data" / "processed"
                                / "v21_forall_corpus" / "train_rows.jsonl"))
    ap.add_argument("--summary",
                    default=str(ROOT / "data" / "processed"
                                / "v21_forall_corpus" / "summary.json"))
    ap.add_argument("--verifier-timeout", type=float, default=30.0)
    ap.add_argument("--no-warmup", dest="warmup", action="store_false")
    ap.set_defaults(warmup=True)
    args = ap.parse_args(argv)

    plan = build_plan()
    logger.info("v21 forall plan: %d theorems", len(plan))
    summary = verify_and_persist(
        plan, verifier_timeout=args.verifier_timeout, warmup=args.warmup,
        out_seeds=Path(args.out_seeds),
        out_candidates=Path(args.out_candidates),
        out_train_rows=Path(args.out_train_rows),
    )
    Path(args.summary).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("v21 forall corpus: planned=%d verified=%d/%d "
                "name_drops=%d triple_drops=%d",
                summary["n_theorems_planned"],
                summary["n_candidates_verified"],
                summary["n_candidates_proposed"],
                summary["n_dropped_by_v18_name_guard"],
                summary["n_dropped_by_v18_triple_guard"])
    for fam, d in summary["by_surface_family"].items():
        logger.info("  %s theorems=%d verified=%d/%d",
                    fam, d["theorems"], d["verified"], d["proposed"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
