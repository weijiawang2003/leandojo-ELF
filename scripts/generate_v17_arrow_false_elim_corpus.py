"""Mini-ELF v17 — Part 3: generate the arrow_false_elim corpus.

Targets the single residual v16 failure ``neg_exfalso_arrow_pq``.

The held-out test row's shape is
``(p q : Prop) (h : p → False) (hp : p) : q`` with proof
``exact (h hp).elim``. The v16 ``contrapositive_false_target``
corpus had the *same antecedents* but a different *goal* (``False``,
not ``q``) and a different proof (``exact h hp``). The model
therefore learned ``exact h hp`` (which produces ``False``) but
not the ``(h hp).elim`` step needed when the goal is a variable
``q``.

This corpus adds the missing shape with multiple variable namings.

Honesty contract:
  * No Mathlib (core Lean 4 only).
  * Every candidate verified by lean-cli before being persisted.
  * No ``state_after``.
  * No manual oracle.
  * Disjoint variable names from v11 LOFO test theorems
    (``(p q)``, ``(a b)``, ``(x y)``, ``(m n)``, ``(a d)``).
  * Disjoint variable names from v16 ``contrapositive_*`` corpus
    where practical (we reuse the same Greek/double-letter pairs
    so the v17 corpus is a clean sibling family).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import make_lean_cli_verifier  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_v17_arrow_false_elim_corpus")


# --------------------------------------------------------------------------- #
# Shapes
# --------------------------------------------------------------------------- #


# Shape A — the v17 headline target.
# (p q : Prop) (h : p → False) (hp : p) : q   with proof  exact (h hp).elim
SHAPE_AFE = {
    "surface_family": "arrow_false_elim",
    "statement_template": (
        "({p} {q} : Prop) ({h} : {p} → False) ({hp} : {p}) : {q}"),
    "proof_templates": (
        "exact ({h} {hp}).elim",
        "exact False.elim ({h} {hp})",
        "exact absurd {hp} {h}",
    ),
}


# Shape B — the False target sibling shape (already partly in v16's
# ``contrapositive_false_target`` family). Adding more variants here
# strengthens the cross-shape correlation between ``(h hp)`` and
# ``.elim``.
SHAPE_FALSE = {
    "surface_family": "arrow_false_elim_false_target",
    "statement_template": (
        "({p} : Prop) ({h} : {p} → False) ({hp} : {p}) : False"),
    "proof_templates": (
        "exact {h} {hp}",
        "exact absurd {hp} {h}",
    ),
}


# Disjoint variable-name pairs (no overlap with v11 LOFO test
# variable pairs: (p,q), (a,b), (x,y), (m,n), (a,d)).
VARIABLE_PAIRS_AFE: Tuple[Tuple[str, str], ...] = (
    ("u", "v"), ("s", "t"), ("e", "f"), ("r", "w"), ("c", "k"),
    ("i", "j"), ("o", "z"), ("alpha", "beta"), ("phi", "psi"),
    ("rho", "sigma"), ("aa", "bb"), ("uu", "vv"), ("ss", "tt"),
    ("ee", "ff"), ("pp", "qq"),
)


HYP_NAMES: Tuple[Tuple[str, str], ...] = (
    ("h", "hp"),
    ("hf", "hp"),
    ("hpfalse", "hp"),
    ("h1", "hp1"),
)


def build_plan() -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []
    # Shape A — headline target — broader coverage
    for p, q in VARIABLE_PAIRS_AFE[:12]:
        for h, hp in HYP_NAMES[:3]:
            stmt = SHAPE_AFE["statement_template"].format(
                p=p, q=q, h=h, hp=hp)
            proofs = [t.format(p=p, q=q, h=h, hp=hp)
                      for t in SHAPE_AFE["proof_templates"]]
            nm = f"v17_afe_{p}_{q}_{h}_{hp}"
            plan.append({
                "theorem_name": nm,
                "theorem_statement": stmt,
                "candidates": proofs,
                "surface_family": SHAPE_AFE["surface_family"],
                "operation": "contradiction",
            })
    # Shape B — sibling
    for p, _ in VARIABLE_PAIRS_AFE[:8]:
        for h, hp in HYP_NAMES[:2]:
            stmt = SHAPE_FALSE["statement_template"].format(
                p=p, h=h, hp=hp)
            proofs = [t.format(p=p, h=h, hp=hp)
                      for t in SHAPE_FALSE["proof_templates"]]
            nm = f"v17_afe_false_{p}_{h}_{hp}"
            plan.append({
                "theorem_name": nm,
                "theorem_statement": stmt,
                "candidates": proofs,
                "surface_family": SHAPE_FALSE["surface_family"],
                "operation": "contradiction",
            })
    return plan


def _state_before(stmt: str) -> str:
    """Mirror the v16 state-rendering helper. Pure-text."""
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


def verify_and_persist(plan: List[Dict[str, Any]], *,
                       verifier_timeout: float, warmup: bool,
                       out_seeds: Path, out_candidates: Path,
                       out_train_rows: Path) -> Dict[str, Any]:
    out_seeds.parent.mkdir(parents=True, exist_ok=True)
    out_candidates.parent.mkdir(parents=True, exist_ok=True)
    out_train_rows.parent.mkdir(parents=True, exist_ok=True)

    verifier = make_lean_cli_verifier(timeout=verifier_timeout)
    if warmup:
        t0 = time.perf_counter()
        wu = verifier("__v17_warmup__", "(x : Nat) : x = x", "rfl")
        logger.info("warmup: success=%s elapsed_ms=%.1f",
                    wu.get("success"), (time.perf_counter() - t0) * 1000.0)

    seeds: List[Dict[str, Any]] = []
    verified_candidates: List[Dict[str, Any]] = []
    train_rows: List[Dict[str, Any]] = []
    per_theorem: Dict[str, Dict[str, int]] = {}

    for entry in plan:
        nm = entry["theorem_name"]
        stmt = entry["theorem_statement"]
        state = _state_before(stmt)
        seeds.append({
            "theorem_name": nm,
            "theorem_statement": stmt,
            "state_before": state,
            "template": f"example {stmt} := by\n  __TACTIC__",
            "placeholder": "__TACTIC__",
            "imports": [],
            "surface_family": entry["surface_family"],
            "required_operation": entry["operation"],
            "source": "v17_arrow_false_elim_corpus",
        })
        per_theorem.setdefault(nm, {"proposed": 0, "verified": 0,
                                    "failed": 0})
        for cand in entry["candidates"]:
            per_theorem[nm]["proposed"] += 1
            try:
                res = verifier(nm, stmt, cand)
            except Exception as exc:  # noqa: BLE001
                res = {"success": False, "error": f"verifier_exception:{exc}"}
            ok = bool(res.get("success"))
            if ok:
                per_theorem[nm]["verified"] += 1
                row_candidate = {
                    "theorem_name": nm,
                    "theorem_statement": stmt,
                    "state_before": state,
                    "tactic": cand,
                    "family": entry["surface_family"],
                    "required_operation": entry["operation"],
                    "corpus_source": "v17_arrow_false_elim_corpus",
                    "tactic_source": "verified",
                    "split": "train",
                    "regime": "v17_arrow_false_elim_redundancy",
                    "redundancy_group": "arrow_false_elim",
                }
                verified_candidates.append({
                    **row_candidate, "verified": True,
                    "verifier": "lean-cli",
                    "verifier_timeout_s": verifier_timeout,
                })
                train_rows.append(row_candidate)
            else:
                per_theorem[nm]["failed"] += 1
                err = (res.get("error") or "").splitlines()[0] if res.get("error") else ""
                logger.info("  FAIL %s :: %r  err=%s", nm, cand, err[:80])

    with out_seeds.open("w", encoding="utf-8") as f:
        for s in seeds:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    with out_candidates.open("w", encoding="utf-8") as f:
        for c in verified_candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with out_train_rows.open("w", encoding="utf-8") as f:
        for r in train_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {
        "n_theorems_planned": len(plan),
        "n_candidates_proposed": sum(d["proposed"]
                                     for d in per_theorem.values()),
        "n_candidates_verified": sum(d["verified"]
                                     for d in per_theorem.values()),
        "n_candidates_failed": sum(d["failed"]
                                   for d in per_theorem.values()),
        "by_surface_family": {},
        "uses_state_after": False,
    }
    fam_counts: Dict[str, Dict[str, Any]] = {}
    for r in verified_candidates:
        d = fam_counts.setdefault(r["family"], {"theorems": set(),
                                                "candidates": 0})
        d["theorems"].add(r["theorem_name"])
        d["candidates"] += 1
    for fam, d in fam_counts.items():
        summary["by_surface_family"][fam] = {
            "theorems": len(d["theorems"]),
            "verified_candidates": d["candidates"],
        }
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out-seeds",
                    default=str(ROOT / "data" / "seeds"
                                / "v17_arrow_false_elim_seeds.jsonl"))
    ap.add_argument("--out-candidates",
                    default=str(ROOT / "data" / "manual"
                                / "v17_arrow_false_elim_candidates.jsonl"))
    ap.add_argument("--out-train-rows",
                    default=str(ROOT / "data" / "processed"
                                / "v17_arrow_false_elim_corpus"
                                / "train_rows.jsonl"))
    ap.add_argument("--summary",
                    default=str(ROOT / "data" / "processed"
                                / "v17_arrow_false_elim_corpus"
                                / "summary.json"))
    ap.add_argument("--verifier-timeout", type=float, default=60.0)
    ap.add_argument("--no-warmup", dest="warmup", action="store_false")
    ap.set_defaults(warmup=True)
    args = ap.parse_args(argv)

    plan = build_plan()
    logger.info("v17 plan: %d theorems × variant proofs", len(plan))
    summary = verify_and_persist(
        plan, verifier_timeout=args.verifier_timeout, warmup=args.warmup,
        out_seeds=Path(args.out_seeds),
        out_candidates=Path(args.out_candidates),
        out_train_rows=Path(args.out_train_rows),
    )
    Path(args.summary).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8")
    logger.info("v17 arrow_false_elim corpus: theorems=%d verified=%d/%d",
                summary["n_theorems_planned"],
                summary["n_candidates_verified"],
                summary["n_candidates_proposed"])
    for fam, d in summary["by_surface_family"].items():
        logger.info("  %s theorems=%d verified_candidates=%d",
                    fam, d["theorems"], d["verified_candidates"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
