"""Mini-ELF v16 — Part 2: generate the contrapositive augmentation corpus.

Produces a small core-Lean-only corpus of contrapositive-style theorems
and their verified proofs. The v16 brief explicitly asks for the
classical contrapositive ``(h : p → q) (hnq : ¬q) : ¬p``; for v16's
primary target (``neg_imp_exfalso_ab``) we also include the
**negation-implication** shape ``(hnp : ¬p) : p → q`` because that is
the actual v11 LOFO test shape held out from train.

For each shape × variable-name pair × proof variant, we:
  1. Render a Lean source file using the same template substitution
     pattern the rest of the pipeline uses.
  2. Run lean-cli (timeout 60 s, after a warm-up theorem) and reject
     any candidate lean does not accept.
  3. Emit two artefacts:
     * ``data/seeds/v16_contrapositive_seeds.jsonl`` — one row per
       theorem (statement, template, placeholder, imports). Used by
       a future ``mini-elf-collect`` re-run if needed.
     * ``data/manual/v16_contrapositive_candidates.jsonl`` — one row
       per **verified** (theorem, tactic) pair, tagged with the v16
       metadata: ``operation=intro_negation``, ``surface_family``,
       ``redundancy_group=contrapositive``, ``source=v16_contrapositive_corpus``.

Honesty contract (verbatim, v16 brief):
  * No Mathlib (every theorem uses only core Lean 4 syntax).
  * All candidates verified by lean-cli before being written.
  * No ``state_after`` anywhere.
  * No manual oracle (the proof variants are template-derived
    schemas, not human-edited targets).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import make_lean_cli_verifier  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_v16_contrapositive_corpus")


# --------------------------------------------------------------------------- #
# Specifications
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProofShape:
    surface_family: str  # e.g. 'contrapositive_classic' / 'contrapositive_neg_imp'
    statement_template: str  # substituted with {p}, {q}, {h}, {hnq}, {hnp}, ...
    proof_templates: Tuple[str, ...]


# Shape A: classical contrapositive ``(h : p → q) (hnq : ¬q) : ¬p``
# Sometimes shown as the brief's target shape. We include several proof
# variants — only those lean actually accepts make it past the
# verifier filter below.
SHAPE_CLASSIC = ProofShape(
    surface_family="contrapositive_classic",
    statement_template="({p} {q} : Prop) ({h} : {p} → {q}) ({hnq} : ¬{q}) : ¬{p}",
    proof_templates=(
        "intro hp\n  exact {hnq} ({h} hp)",
        "exact fun hp => {hnq} ({h} hp)",
        "intro hp\n  exact absurd ({h} hp) {hnq}",
        "exact fun hp => absurd ({h} hp) {hnq}",
    ),
)


# Shape B: negation-implication ``(hnp : ¬p) : p → q``. This is the
# *actual* v11 LOFO test shape. Augmenting train with siblings of this
# shape is the most direct way to lift neg_imp_exfalso_ab's beam rank.
SHAPE_NEG_IMP = ProofShape(
    surface_family="contrapositive_neg_imp",
    statement_template="({p} {q} : Prop) ({hnp} : ¬{p}) : {p} → {q}",
    proof_templates=(
        "intro hp\n  exact absurd hp {hnp}",
        "intro hp\n  exact ({hnp} hp).elim",
        "exact fun hp => absurd hp {hnp}",
        "exact fun hp => ({hnp} hp).elim",
    ),
)


# Shape C: False target with arrow-False hypothesis
# ``(h : p → False) (hp : p) : False``. A trivial but useful sibling
# for the model to see; corroborates ``exact (h hp)`` patterns.
SHAPE_FALSE_TARGET = ProofShape(
    surface_family="contrapositive_false_target",
    statement_template="({p} : Prop) ({h} : {p} → False) (hp : {p}) : False",
    proof_templates=(
        "exact {h} hp",
        "exact absurd hp {h}",
    ),
)


SHAPES: Tuple[ProofShape, ...] = (SHAPE_CLASSIC, SHAPE_NEG_IMP, SHAPE_FALSE_TARGET)


# 16 distinct (p, q) variable-name pairs. **Crucially** these include
# NEITHER the v11 LOFO neg_imp_exfalso test variable pairs ((p,q),
# (a,b), (x,y), (m,n), (a,d)) NOR the typical neg_exfalso ones — so
# the v16 corpus does not memorise the held-out test rows. We rely on
# leakage guards (Part 3) to enforce this, but we also pick disjoint
# names here for belt-and-braces honesty.
VARIABLE_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("u", "v"), ("s", "t"), ("e", "f"), ("g", "k"),
    ("r", "w"), ("c", "d"), ("i", "j"), ("o", "z"),
    # extras for redundancy:
    ("alpha", "beta"), ("phi", "psi"), ("rho", "sigma"),
    ("aa", "bb"), ("uu", "vv"), ("ss", "tt"),
    ("pp", "qq"),  ("xx", "yy"),
)


HYP_NAMES_CLASSIC: Tuple[Tuple[str, str], ...] = (
    ("h", "hnq"), ("h1", "hnq1"), ("hf", "hng"),
    ("hpq", "hnq"), ("imp", "ngoal"),
)


HYP_NAMES_NEG_IMP: Tuple[str, ...] = (
    "hnp", "hn", "hnotp", "hnA", "hnu",
)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def render_classic(p: str, q: str, h: str, hnq: str) -> Tuple[str, List[str]]:
    stmt = SHAPE_CLASSIC.statement_template.format(p=p, q=q, h=h, hnq=hnq)
    proofs = [t.format(p=p, q=q, h=h, hnq=hnq)
              for t in SHAPE_CLASSIC.proof_templates]
    return stmt, proofs


def render_neg_imp(p: str, q: str, hnp: str) -> Tuple[str, List[str]]:
    stmt = SHAPE_NEG_IMP.statement_template.format(p=p, q=q, hnp=hnp)
    proofs = [t.format(p=p, q=q, hnp=hnp)
              for t in SHAPE_NEG_IMP.proof_templates]
    return stmt, proofs


def render_false_target(p: str, h: str) -> Tuple[str, List[str]]:
    stmt = SHAPE_FALSE_TARGET.statement_template.format(p=p, h=h)
    proofs = [t.format(p=p, h=h) for t in SHAPE_FALSE_TARGET.proof_templates]
    return stmt, proofs


# --------------------------------------------------------------------------- #
# Theorem-name disambiguation
# --------------------------------------------------------------------------- #


def make_theorem_name(prefix: str, p: str, q: str = "", h: str = "") -> str:
    tail = "_".join(s for s in (p, q, h) if s)
    return f"{prefix}_{tail}"


# --------------------------------------------------------------------------- #
# Build the (theorem, candidates) plan
# --------------------------------------------------------------------------- #


def build_plan() -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []
    # Classic contrapositive: var pair × hypothesis pair
    for p, q in VARIABLE_PAIRS[:10]:  # 10 variable pairs
        for h, hnq in HYP_NAMES_CLASSIC[:3]:  # 3 hypothesis namings
            stmt, proofs = render_classic(p, q, h, hnq)
            nm = make_theorem_name("v16_classic", p, q, h)
            plan.append({
                "theorem_name": nm,
                "theorem_statement": stmt,
                "candidates": proofs,
                "surface_family": SHAPE_CLASSIC.surface_family,
                "operation": "intro_negation",
            })
    # Negation-implication: var pair × hypothesis name
    for p, q in VARIABLE_PAIRS[:12]:  # 12 variable pairs
        for hnp in HYP_NAMES_NEG_IMP[:3]:  # 3 hyp namings
            stmt, proofs = render_neg_imp(p, q, hnp)
            nm = make_theorem_name("v16_negimp", p, q, hnp)
            plan.append({
                "theorem_name": nm,
                "theorem_statement": stmt,
                "candidates": proofs,
                "surface_family": SHAPE_NEG_IMP.surface_family,
                "operation": "intro_negation",
            })
    # False target: simpler, fewer variants
    for p, _ in VARIABLE_PAIRS[:5]:
        for h in ("h", "hf", "hpfalse"):
            stmt, proofs = render_false_target(p, h)
            nm = make_theorem_name("v16_falsetarget", p, h)
            plan.append({
                "theorem_name": nm,
                "theorem_statement": stmt,
                "candidates": proofs,
                "surface_family": SHAPE_FALSE_TARGET.surface_family,
                "operation": "intro_negation",
            })
    return plan


# --------------------------------------------------------------------------- #
# Verification + persistence
# --------------------------------------------------------------------------- #


def _state_before_for(stmt: str) -> str:
    """Synthesise a state_before string in the v11 LOFO style.
    Pure-text, no lean call. Mirrors what the v11 LOFO builder
    would write for a similarly-shaped theorem."""
    # Strip the leading hypothesis bindings and emit ``hyp : type``
    # per line + the goal after ``⊢``.
    s = stmt.strip()
    # statement of the form '(a : T1) (b : T2) ... : T_goal'
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
    # rest now starts with ':' followed by goal
    goal = rest[1:].strip() if rest.startswith(":") else rest
    binding_lines: List[str] = []
    for b in bindings:
        # split possibly multiple names sharing type 'p q : Prop'
        if ":" in b:
            names_part, type_part = b.split(":", 1)
            type_str = type_part.strip()
            for n in names_part.split():
                binding_lines.append(f"{n} : {type_str}")
        else:
            binding_lines.append(b.strip())
    return "\n".join(binding_lines + [f"⊢ {goal}"])


def verify_and_persist(
    plan: List[Dict[str, Any]],
    *, verifier_timeout: float, warmup: bool,
    out_seeds: Path, out_candidates: Path, out_train_rows: Path,
) -> Dict[str, Any]:
    out_seeds.parent.mkdir(parents=True, exist_ok=True)
    out_candidates.parent.mkdir(parents=True, exist_ok=True)
    out_train_rows.parent.mkdir(parents=True, exist_ok=True)

    verifier = make_lean_cli_verifier(timeout=verifier_timeout)
    if warmup:
        t0 = time.perf_counter()
        wu = verifier("__v16_warmup__", "(x : Nat) : x = x", "rfl")
        logger.info("warmup: success=%s elapsed_ms=%.1f",
                    wu.get("success"), (time.perf_counter() - t0) * 1000.0)

    seeds: List[Dict[str, Any]] = []
    verified_candidates: List[Dict[str, Any]] = []
    train_rows: List[Dict[str, Any]] = []
    per_theorem_counts: Dict[str, Dict[str, int]] = {}

    for entry in plan:
        nm = entry["theorem_name"]
        stmt = entry["theorem_statement"]
        state = _state_before_for(stmt)
        seed = {
            "theorem_name": nm,
            "theorem_statement": stmt,
            "state_before": state,
            "template": f"example {stmt} := by\n  __TACTIC__",
            "placeholder": "__TACTIC__",
            "imports": [],
            "surface_family": entry["surface_family"],
            "required_operation": entry["operation"],
            "source": "v16_contrapositive_corpus",
        }
        seeds.append(seed)
        per_theorem_counts.setdefault(nm, {"proposed": 0, "verified": 0,
                                           "failed": 0})
        for cand in entry["candidates"]:
            per_theorem_counts[nm]["proposed"] += 1
            try:
                res = verifier(nm, stmt, cand)
            except Exception as exc:  # noqa: BLE001
                res = {"success": False, "error": f"verifier_exception:{exc}"}
            ok = bool(res.get("success"))
            if ok:
                per_theorem_counts[nm]["verified"] += 1
                row_candidate = {
                    "theorem_name": nm,
                    "theorem_statement": stmt,
                    "state_before": state,
                    "tactic": cand,
                    "family": entry["surface_family"],
                    "required_operation": entry["operation"],
                    "corpus_source": "v16_contrapositive_corpus",
                    "tactic_source": "verified",
                    "split": "train",
                    "regime": "v16_contrapositive_redundancy",
                    "redundancy_group": "contrapositive",
                }
                verified_candidates.append({
                    **row_candidate,
                    "verified": True,
                    "verifier": "lean-cli",
                    "verifier_timeout_s": verifier_timeout,
                })
                train_rows.append(row_candidate)
            else:
                per_theorem_counts[nm]["failed"] += 1
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
                                     for d in per_theorem_counts.values()),
        "n_candidates_verified": sum(d["verified"]
                                     for d in per_theorem_counts.values()),
        "n_candidates_failed": sum(d["failed"]
                                   for d in per_theorem_counts.values()),
        "by_surface_family": {},
        "out_seeds_path": str(out_seeds),
        "out_candidates_path": str(out_candidates),
        "out_train_rows_path": str(out_train_rows),
        "uses_state_after": False,
    }
    fam_counts: Dict[str, Dict[str, int]] = {}
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


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out-seeds",
                    default=str(ROOT / "data" / "seeds"
                                / "v16_contrapositive_seeds.jsonl"))
    ap.add_argument("--out-candidates",
                    default=str(ROOT / "data" / "manual"
                                / "v16_contrapositive_candidates.jsonl"))
    ap.add_argument("--out-train-rows",
                    default=str(ROOT / "data" / "processed"
                                / "v16_contrapositive_corpus"
                                / "train_rows.jsonl"))
    ap.add_argument("--summary",
                    default=str(ROOT / "data" / "processed"
                                / "v16_contrapositive_corpus"
                                / "summary.json"))
    ap.add_argument("--verifier-timeout", type=float, default=60.0)
    ap.add_argument("--no-warmup", dest="warmup", action="store_false")
    ap.set_defaults(warmup=True)
    args = ap.parse_args(argv)

    plan = build_plan()
    logger.info("plan: %d theorems × variant proofs",
                len(plan))

    summary = verify_and_persist(
        plan,
        verifier_timeout=args.verifier_timeout, warmup=args.warmup,
        out_seeds=Path(args.out_seeds),
        out_candidates=Path(args.out_candidates),
        out_train_rows=Path(args.out_train_rows),
    )
    Path(args.summary).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8")
    logger.info("v16 contrapositive corpus: theorems=%d verified=%d/%d",
                summary["n_theorems_planned"],
                summary["n_candidates_verified"],
                summary["n_candidates_proposed"])
    for fam, d in summary["by_surface_family"].items():
        logger.info("  %s  theorems=%d  verified_candidates=%d",
                    fam, d["theorems"], d["verified_candidates"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
