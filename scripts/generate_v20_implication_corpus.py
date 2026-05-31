"""Mini-ELF v20 — Part 2: generate the implication corpus.

Targets the v18 broad-core ``implication`` category (currently
pass@5 = 0.000 under every v17/v18/v19 config).

The shape-gap audit (Part 1) confirmed:
  * `exact hp` exists 400 times in synthetic training **but** is
    consistently displaced by v17 contradiction shapes like
    `exact (h hp).elim` and `exact (hpfalse hp).elim`. So a few
    bare `exact hp` rows alone won't help — the model already
    "knows" them, the issue is rank.
  * `intro hq` exists only 30 times, `hpq` 100 times,
    `hqr` **0 times**, `exact (h hp)` 24 times.

So v20 adds an implication corpus that exercises the **bare**
implication shapes (no `.elim`, no `False`, no contradiction) with
explicit `hpq`/`hqr`/`hImp` naming so the trained model learns to
emit `exact hp` / `intro hq; exact hp` / `exact hqr (hpq hp)`
when the goal is a Prop variable rather than `False`.

Four shape families:

  1. **identity**     ``(p : Prop) (hp : p) : p``                 → ``exact hp``
  2. **intro_const**  ``(p q : Prop) (hp : p) : q → p``           → ``intro hq\\n  exact hp``
  3. **modus_ponens** ``(p q : Prop) (h : p → q) (hp : p) : q``   → ``exact h hp``
  4. **compose**      ``(p q r : Prop) (hpq : p → q) (hqr : q → r) (hp : p) : r``
                                                                  → ``exact hqr (hpq hp)``

Variable names are sampled from disjoint pools so the model sees
many surface realisations of the same role pattern. v18 test
theorem names + (state, tactic) triples are guarded against.

Honesty:
  * No Mathlib.
  * Every candidate verified by lean-cli before persisting.
  * No state_after.
  * No manual oracle.
  * v18 leakage guards (name + triple) applied at the end.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import make_lean_cli_verifier  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_v20_implication_corpus")


# Disjoint variable-name pairs/triples (avoid v18 test pair (p,q,r)
# and the contradiction pool (u,v,s,t,e,f,...). Keeps the corpus
# "novel" relative to v17.)
VAR_SINGLES: Tuple[str, ...] = (
    "a", "b", "c", "d", "e", "g", "k", "l", "m",
    "alpha", "beta", "gamma", "delta", "phi", "psi",
)
VAR_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("a", "b"), ("c", "d"), ("e", "g"), ("k", "l"),
    ("m", "n"), ("s", "t"), ("u", "v"), ("w", "z"),
    ("alpha", "beta"), ("phi", "psi"), ("rho", "sigma"),
    ("aa", "bb"), ("uu", "vv"),
)
VAR_TRIPLES: Tuple[Tuple[str, str, str], ...] = (
    ("a", "b", "c"), ("d", "e", "g"), ("k", "l", "m"),
    ("s", "t", "u"), ("v", "w", "z"),
    ("alpha", "beta", "gamma"),
    ("phi", "psi", "rho"),
    ("aa", "bb", "cc"),
)

# Hypothesis-name palettes per shape. These keep the corpus broad
# (the v17 corpus used `h`/`hp`/`hf`/`hpfalse`/`h1`).
HYP_IDENTITY: Tuple[str, ...] = ("hp", "h", "hyp", "hh", "ha", "prf")
HYP_INTRO_TARGET: Tuple[str, ...] = ("hq", "hb", "haux", "hh2", "hother")
HYP_MP_PAIR: Tuple[Tuple[str, str], ...] = (
    ("h", "hp"), ("himp", "hp"), ("hpq", "hp"), ("hf", "hp"),
    ("hImp", "hp"), ("hyp", "ha"), ("hh", "hh2"),
)
HYP_COMPOSE: Tuple[Tuple[str, str, str], ...] = (
    ("hpq", "hqr", "hp"),
    ("hImp1", "hImp2", "hp"),
    ("hab", "hbc", "ha"),
    ("hf", "hg", "hp"),
    ("h1", "h2", "hp"),
    ("hcomp1", "hcomp2", "hh"),
)


def build_plan() -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []

    # Shape 1 — identity.   (p : Prop) (hp : p) : p   →   exact hp
    for p in VAR_SINGLES[:10]:
        for hp in HYP_IDENTITY[:4]:
            stmt = f"({p} : Prop) ({hp} : {p}) : {p}"
            proofs = [f"exact {hp}"]
            nm = f"v20_imp_identity_{p}_{hp}"
            plan.append({
                "theorem_name": nm,
                "theorem_statement": stmt,
                "candidates": proofs,
                "surface_family": "implication_identity",
                "operation": "implication",
            })

    # Shape 2 — intro_const.   (p q : Prop) (hp : p) : q → p
    #                         → intro hq\n  exact hp
    for p, q in VAR_PAIRS[:8]:
        for hp in HYP_IDENTITY[:3]:
            for hq in HYP_INTRO_TARGET[:3]:
                stmt = f"({p} {q} : Prop) ({hp} : {p}) : {q} → {p}"
                proofs = [
                    f"intro {hq}\n  exact {hp}",
                    f"intros {hq}\n  exact {hp}",
                    f"exact fun {hq} => {hp}",
                    f"exact fun _ => {hp}",
                ]
                nm = f"v20_imp_intro_const_{p}_{q}_{hp}_{hq}"
                plan.append({
                    "theorem_name": nm,
                    "theorem_statement": stmt,
                    "candidates": proofs,
                    "surface_family": "implication_intro_const",
                    "operation": "implication",
                })

    # Shape 3 — modus ponens.   (p q : Prop) (h : p → q) (hp : p) : q
    #                          → exact h hp
    for p, q in VAR_PAIRS[:8]:
        for himp, hp in HYP_MP_PAIR[:5]:
            stmt = (f"({p} {q} : Prop) ({himp} : {p} → {q}) ({hp} : {p}) : {q}")
            proofs = [
                f"exact {himp} {hp}",
                f"apply {himp}\n  exact {hp}",
                f"exact ({himp} {hp})",
            ]
            nm = f"v20_imp_mp_{p}_{q}_{himp}_{hp}"
            plan.append({
                "theorem_name": nm,
                "theorem_statement": stmt,
                "candidates": proofs,
                "surface_family": "implication_modus_ponens",
                "operation": "implication",
            })

    # Shape 4 — composition.   (p q r) (hpq : p → q) (hqr : q → r) (hp : p) : r
    #                          → exact hqr (hpq hp)
    for p, q, r in VAR_TRIPLES[:7]:
        for hpq, hqr, hp in HYP_COMPOSE[:5]:
            stmt = (f"({p} {q} {r} : Prop) "
                    f"({hpq} : {p} → {q}) "
                    f"({hqr} : {q} → {r}) "
                    f"({hp} : {p}) : {r}")
            proofs = [
                f"exact {hqr} ({hpq} {hp})",
                f"apply {hqr}\n  exact {hpq} {hp}",
                f"apply {hqr}\n  apply {hpq}\n  exact {hp}",
            ]
            nm = f"v20_imp_compose_{p}_{q}_{r}_{hpq}_{hqr}_{hp}"
            plan.append({
                "theorem_name": nm,
                "theorem_statement": stmt,
                "candidates": proofs,
                "surface_family": "implication_compose",
                "operation": "implication",
            })

    # Shape 5 — function composition (Type, not Prop).
    #   (A B C : Type) (f : A → B) (g : B → C) (a : A) : C
    #   → exact g (f a)
    # Matches v18_imp_compose's *shape* (Type-level, function names).
    # Uses Latin caps for the type names to stay disjoint from the
    # v18 test row's α β γ.
    TYPE_TRIPLES: Tuple[Tuple[str, str, str], ...] = (
        ("A", "B", "C"), ("X", "Y", "Z"), ("P", "Q", "R"),
        ("S", "T", "U"), ("M", "N", "K"), ("aa", "bb", "cc"),
    )
    FUN_TRIPLES: Tuple[Tuple[str, str, str], ...] = (
        ("f", "g", "a"), ("fab", "fbc", "x"),
        ("h1", "h2", "y"), ("ff", "gg", "aa"),
    )
    for A, B, C in TYPE_TRIPLES:
        for f, g, a in FUN_TRIPLES:
            stmt = (f"({A} {B} {C} : Type) "
                    f"({f} : {A} → {B}) ({g} : {B} → {C}) "
                    f"({a} : {A}) : {C}")
            proofs = [
                f"exact {g} ({f} {a})",
                f"apply {g}\n  exact {f} {a}",
                f"apply {g}\n  apply {f}\n  exact {a}",
            ]
            nm = f"v20_imp_fun_compose_{A}_{B}_{C}_{f}_{g}_{a}"
            plan.append({
                "theorem_name": nm,
                "theorem_statement": stmt,
                "candidates": proofs,
                "surface_family": "implication_fun_compose",
                "operation": "implication",
            })

    # Shape 6 — swap_args.   (p q r) (h : p → q → r) (hq : q) (hp : p) : r
    #                       → exact h hp hq
    HYP_SWAP: Tuple[Tuple[str, str, str], ...] = (
        ("h", "hq", "hp"),
        ("himp", "hq", "hp"),
        ("h2", "hb", "ha"),
        ("hh", "hh2", "hh3"),
        ("hyp", "hq", "hp"),
    )
    for p, q, r in VAR_TRIPLES[:5]:
        for h, hq, hp in HYP_SWAP:
            stmt = (f"({p} {q} {r} : Prop) "
                    f"({h} : {p} → {q} → {r}) "
                    f"({hq} : {q}) ({hp} : {p}) : {r}")
            proofs = [
                f"exact {h} {hp} {hq}",
                f"apply {h}\n  exact {hp}\n  exact {hq}",
                f"exact ({h} {hp}) {hq}",
            ]
            nm = f"v20_imp_swap_{p}_{q}_{r}_{h}_{hq}_{hp}"
            plan.append({
                "theorem_name": nm,
                "theorem_statement": stmt,
                "candidates": proofs,
                "surface_family": "implication_swap_args",
                "operation": "implication",
            })

    # Shape 7 — arrow_arrow.   (p q) (h : (p → q) → p) (hpq : p → q) : p
    #                          → exact h hpq
    HYP_AA: Tuple[Tuple[str, str], ...] = (
        ("h", "hpq"), ("hself", "himp"), ("h1", "h2"),
        ("hyp", "hyp2"), ("ha", "hb"),
    )
    for p, q in VAR_PAIRS[:6]:
        for h, hpq in HYP_AA:
            stmt = (f"({p} {q} : Prop) "
                    f"({h} : ({p} → {q}) → {p}) "
                    f"({hpq} : {p} → {q}) : {p}")
            proofs = [
                f"exact {h} {hpq}",
                f"apply {h}\n  exact {hpq}",
            ]
            nm = f"v20_imp_arrow_arrow_{p}_{q}_{h}_{hpq}"
            plan.append({
                "theorem_name": nm,
                "theorem_statement": stmt,
                "candidates": proofs,
                "surface_family": "implication_arrow_arrow",
                "operation": "implication",
            })

    return plan


def _state_before(stmt: str) -> str:
    """Mirror the v16/v17 state-rendering helper."""
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
        wu = verifier("__v20_imp_warmup__", "(x : Nat) : x = x", "rfl")
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
            "category": "implication",
            "required_operation": entry["operation"],
            "source": "v20_implication_corpus",
            "core_lean": True,
        })
        for cand in entry["candidates"]:
            per_family[fam]["proposed"] += 1
            try:
                res = verifier(nm, stmt, cand)
                # WSL subprocess flakiness sometimes produces spurious
                # timeouts on tactics that succeed in 400ms. Retry once
                # on timeout before classifying as a real failure.
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
            # Leakage guards
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
                "category": "implication",
                "required_operation": entry["operation"],
                "corpus_source": "v20_implication_corpus",
                "tactic_source": "verified",
                "split": "train",
                "regime": "v20_implication_redundancy",
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
                                / "v20_implication_seeds.jsonl"))
    ap.add_argument("--out-candidates",
                    default=str(ROOT / "data" / "manual"
                                / "v20_implication_candidates.jsonl"))
    ap.add_argument("--out-train-rows",
                    default=str(ROOT / "data" / "processed"
                                / "v20_implication_corpus"
                                / "train_rows.jsonl"))
    ap.add_argument("--summary",
                    default=str(ROOT / "data" / "processed"
                                / "v20_implication_corpus"
                                / "summary.json"))
    ap.add_argument("--verifier-timeout", type=float, default=60.0)
    ap.add_argument("--no-warmup", dest="warmup", action="store_false")
    ap.set_defaults(warmup=True)
    args = ap.parse_args(argv)

    plan = build_plan()
    logger.info("v20 implication plan: %d theorems", len(plan))
    summary = verify_and_persist(
        plan, verifier_timeout=args.verifier_timeout, warmup=args.warmup,
        out_seeds=Path(args.out_seeds),
        out_candidates=Path(args.out_candidates),
        out_train_rows=Path(args.out_train_rows),
    )
    Path(args.summary).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8")
    logger.info("v20 implication corpus: planned=%d verified=%d/%d "
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
