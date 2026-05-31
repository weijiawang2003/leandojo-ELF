"""Mini-ELF v20 — Part 3: generate the Bool corpus.

Targets the v18 broad-core ``bool`` category (currently pass@5 =
0.000 under every config). The Part 1 audit confirmed the
synthetic training pool contains **zero** rows mentioning ``Bool``
or ``cases b``, so the model has no Bool data shape at all.

Shape families:

  1. **bool_refl**        ``(b : Bool) : b = b``                  → ``rfl``
  2. **bool_cases_taut**  ``(b : Bool) : b = true ∨ b = false``   → ``cases b <;> simp``
                                                                  → ``cases b\\n  · exact Or.inl rfl\\n  · exact Or.inr rfl``
  3. **bool_no_conf**     ``(b : Bool) : b = false ∨ b = true``   → ``cases b <;> simp``
                                                                  → explicit cases analogue
  4. **bool_if_id**       ``(b : Bool) : (if b then true else false) = b``
                                                                  → ``cases b <;> rfl``
  5. **bool_eq_rw**       ``(b : Bool) (h : b = true) : b = true`` → ``exact h``
  6. **bool_double_neg**  ``(b : Bool) : !!b = b``                → ``cases b <;> rfl``

We probe a few core-Lean syntactic variants for each shape and keep
only those that the lean-cli verifier accepts (no Mathlib).

Honesty:
  * No Mathlib.
  * Every candidate verified by lean-cli before persisting.
  * No state_after.
  * No manual oracle.
  * v18 leakage guards applied at the end.
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
logger = logging.getLogger("generate_v20_bool_corpus")


BOOL_VARS: Tuple[str, ...] = (
    "b", "x", "y", "c", "d", "bb", "bb1", "ok", "flag",
    "boolVar", "value",
)


def build_plan() -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []

    # Shape 1 — bool_refl: (b : Bool) : b = b → rfl
    for b in BOOL_VARS:
        stmt = f"({b} : Bool) : {b} = {b}"
        nm = f"v20_bool_refl_{b}"
        plan.append({
            "theorem_name": nm,
            "theorem_statement": stmt,
            "candidates": ["rfl", "exact rfl", "exact Eq.refl _"],
            "surface_family": "bool_refl",
            "operation": "bool_cases",
        })

    # Shape 2 — bool_cases_taut: (b : Bool) : b = true ∨ b = false
    for b in BOOL_VARS[:8]:
        stmt = f"({b} : Bool) : {b} = true ∨ {b} = false"
        nm = f"v20_bool_taut_tf_{b}"
        plan.append({
            "theorem_name": nm,
            "theorem_statement": stmt,
            "candidates": [
                f"cases {b} <;> simp",
                f"cases {b}\n  · exact Or.inr rfl\n  · exact Or.inl rfl",
                f"cases {b} with\n  | true => exact Or.inl rfl\n  | false => exact Or.inr rfl",
                f"by_cases h : {b} = true\n  · exact Or.inl h\n  · cases {b}\n    · exact Or.inl rfl\n    · exact Or.inr rfl",
            ],
            "surface_family": "bool_cases_taut",
            "operation": "bool_cases",
        })

    # Shape 3 — bool_no_conf swap: (b : Bool) : b = false ∨ b = true
    for b in BOOL_VARS[:6]:
        stmt = f"({b} : Bool) : {b} = false ∨ {b} = true"
        nm = f"v20_bool_taut_ft_{b}"
        plan.append({
            "theorem_name": nm,
            "theorem_statement": stmt,
            "candidates": [
                f"cases {b} <;> simp",
                f"cases {b}\n  · exact Or.inr rfl\n  · exact Or.inl rfl",
                f"cases {b} with\n  | true => exact Or.inr rfl\n  | false => exact Or.inl rfl",
            ],
            "surface_family": "bool_no_conf",
            "operation": "bool_cases",
        })

    # Shape 4 — bool_if_id: (b : Bool) : (if b then true else false) = b
    for b in BOOL_VARS[:6]:
        stmt = f"({b} : Bool) : (if {b} then true else false) = {b}"
        nm = f"v20_bool_if_id_{b}"
        plan.append({
            "theorem_name": nm,
            "theorem_statement": stmt,
            "candidates": [
                f"cases {b} <;> rfl",
                f"cases {b}\n  · rfl\n  · rfl",
                f"by cases {b} <;> rfl",
            ],
            "surface_family": "bool_if_id",
            "operation": "bool_cases",
        })

    # Shape 5 — bool_eq_rw: (b : Bool) (h : b = true) : b = true → exact h
    HYPS = ("h", "h1", "heq", "hp", "hh")
    for b in BOOL_VARS[:5]:
        for h in HYPS:
            stmt = f"({b} : Bool) ({h} : {b} = true) : {b} = true"
            nm = f"v20_bool_eq_rw_{b}_{h}"
            plan.append({
                "theorem_name": nm,
                "theorem_statement": stmt,
                "candidates": [
                    f"exact {h}",
                    f"assumption",
                    f"rw [{h}]",
                ],
                "surface_family": "bool_eq_rw",
                "operation": "bool_cases",
            })

    # Shape 6 — bool_double_neg: (b : Bool) : !!b = b
    for b in BOOL_VARS[:6]:
        stmt = f"({b} : Bool) : !!{b} = {b}"
        nm = f"v20_bool_dneg_{b}"
        plan.append({
            "theorem_name": nm,
            "theorem_statement": stmt,
            "candidates": [
                f"cases {b} <;> rfl",
                f"cases {b}\n  · rfl\n  · rfl",
                f"cases {b} <;> decide",
            ],
            "surface_family": "bool_double_neg",
            "operation": "bool_cases",
        })

    # Shape 7 — bool_and_rw: (b : Bool) (h : (b && true) = true) : b = true
    # Mirrors v18_bool_and_left's shape. exact h works because of
    # definitional unfolding of (b && true).
    for b in BOOL_VARS[:5]:
        for h in HYPS[:3]:
            stmt = f"({b} : Bool) ({h} : ({b} && true) = true) : {b} = true"
            nm = f"v20_bool_and_rw_{b}_{h}"
            plan.append({
                "theorem_name": nm,
                "theorem_statement": stmt,
                "candidates": [
                    f"exact {h}",
                    f"rw [Bool.and_true] at {h}\n  exact {h}",
                    f"simpa using {h}",
                ],
                "surface_family": "bool_and_rw",
                "operation": "bool_cases",
            })

    return plan


def _state_before(stmt: str) -> str:
    """Mirror v17 helper."""
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
    binding_lines: List[str] = []
    for b in bindings:
        if ":" in b:
            names_part, type_part = b.split(":", 1)
            type_str = type_part.strip()
            for n in names_part.split():
                binding_lines.append(f"{n} : {type_str}")
        else:
            binding_lines.append(b.strip())
    return "\n".join(binding_lines + [f"⊢ {goal}"])


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
                         o.get("state_before", ""),
                         o.get("tactic", "")))
    return names, triples


def verify_and_persist(plan, *, verifier_timeout, warmup,
                       out_seeds, out_candidates, out_train_rows):
    out_seeds.parent.mkdir(parents=True, exist_ok=True)
    out_candidates.parent.mkdir(parents=True, exist_ok=True)
    out_train_rows.parent.mkdir(parents=True, exist_ok=True)

    verifier = make_lean_cli_verifier(timeout=verifier_timeout)
    if warmup:
        t0 = time.perf_counter()
        wu = verifier("__v20_bool_warmup__", "(x : Nat) : x = x", "rfl")
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
            "category": "bool",
            "required_operation": entry["operation"],
            "source": "v20_bool_corpus",
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
                res = {"success": False,
                       "error": f"verifier_exception:{exc}"}
            ok = bool(res.get("success"))
            if not ok:
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
                continue
            per_family[fam]["verified"] += 1
            row = {
                "theorem_name": nm,
                "theorem_statement": stmt,
                "state_before": state,
                "tactic": cand,
                "family": fam,
                "category": "bool",
                "required_operation": entry["operation"],
                "corpus_source": "v20_bool_corpus",
                "tactic_source": "verified",
                "split": "train",
                "regime": "v20_bool_redundancy",
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
        "n_candidates_proposed": sum(d["proposed"]
                                     for d in per_family.values()),
        "n_candidates_verified": sum(d["verified"]
                                     for d in per_family.values()),
        "n_candidates_failed": sum(d["failed"]
                                   for d in per_family.values()),
        "n_dropped_by_v18_name_guard": dropped_by_name,
        "n_dropped_by_v18_triple_guard": dropped_by_triple,
        "by_surface_family": {
            fam: {
                "theorems": d["theorems"],
                "proposed": d["proposed"],
                "verified": d["verified"],
                "failed": d["failed"],
            } for fam, d in per_family.items()
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
                                / "v20_bool_seeds.jsonl"))
    ap.add_argument("--out-candidates",
                    default=str(ROOT / "data" / "manual"
                                / "v20_bool_candidates.jsonl"))
    ap.add_argument("--out-train-rows",
                    default=str(ROOT / "data" / "processed"
                                / "v20_bool_corpus"
                                / "train_rows.jsonl"))
    ap.add_argument("--summary",
                    default=str(ROOT / "data" / "processed"
                                / "v20_bool_corpus"
                                / "summary.json"))
    ap.add_argument("--verifier-timeout", type=float, default=60.0)
    ap.add_argument("--no-warmup", dest="warmup", action="store_false")
    ap.set_defaults(warmup=True)
    args = ap.parse_args(argv)

    plan = build_plan()
    logger.info("v20 bool plan: %d theorems", len(plan))
    summary = verify_and_persist(
        plan, verifier_timeout=args.verifier_timeout, warmup=args.warmup,
        out_seeds=Path(args.out_seeds),
        out_candidates=Path(args.out_candidates),
        out_train_rows=Path(args.out_train_rows),
    )
    Path(args.summary).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8")
    logger.info("v20 bool corpus: planned=%d verified=%d/%d "
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
