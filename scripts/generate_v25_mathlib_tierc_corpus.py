"""Mini-ELF v25 — Parts 2/3: tiny Mathlib tier-C benchmark + verification.

Builds 20–50 *tiny* Mathlib-tier theorems (Nat / List / Bool-Option /
Set / Logic), each with 2–5 reference candidate tactics, and verifies
every candidate by whole-file typecheck **inside the external Mathlib
scratch project** (`lake env lean`, `import Mathlib`). Only Lean-accepted
candidates are written to the verified trace; the rest go to the failed
trace. This is the real-Mathlib path (Part 2A): the env probe
([`V25_MATHLIB_ENV_REPORT.md`]) confirmed Mathlib v4.30.0 imports.

Outputs:
  * `data/seeds/v25_mathlib_tierc_seeds.jsonl`       (Part 2 benchmark)
  * `data/manual/v25_mathlib_tierc_candidates.jsonl` (Part 2 reference, verified)
  * `data/traces/v25_mathlib_tierc_verified.jsonl`   (Part 3)
  * `data/traces/v25_mathlib_tierc_failed.jsonl`     (Part 3)
  * `data/processed/v25_mathlib_tierc_corpus/{train_rows.jsonl,summary.json}`

Honesty: real `lake env lean` typecheck (no mock); the manual candidates
are **corpus targets verified by Lean, never used as model predictions**;
no state_after; no Mathlib faked; v18/v25 leakage guards. The `import
Mathlib` line is the fixed *environment* supplied to every candidate — it
is not something the model predicts.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.lean_runner import LeanCliRunner  # noqa: E402
from mini_elf_lean.schemas import TheoremSeed  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_v25_mathlib_tierc_corpus")

DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"
MATHLIB_IMPORT = "import Mathlib"


# --------------------------------------------------------------------------
# benchmark plan: tiny Mathlib-tier theorems
# --------------------------------------------------------------------------
def build_plan() -> List[Dict[str, Any]]:
    """Each entry: name, statement (binders + `:` + goal), candidate
    tactics, category, and ``transfer`` ('core' = a broad-core-style
    tactic should suffice; 'mathlib' = expected to need a Mathlib
    lemma/tactic)."""
    plan: List[Dict[str, Any]] = []

    def add(name, stmt, cands, cat, transfer, op):
        plan.append({"theorem_name": name, "theorem_statement": stmt,
                     "candidates": cands, "category": cat,
                     "transfer": transfer, "required_operation": op})

    # ---- 1. Nat arithmetic ----
    add("v25_nat_add_zero", "(n : Nat) : n + 0 = n",
        ["rfl", "simp", "exact Nat.add_zero n", "omega"],
        "nat", "core", "rewrite")
    add("v25_nat_zero_add", "(n : Nat) : 0 + n = n",
        ["simp", "omega", "exact Nat.zero_add n"],
        "nat", "mathlib", "rewrite")
    add("v25_nat_succ_eq", "(n : Nat) : Nat.succ n = n + 1",
        ["rfl", "simp", "omega"],
        "nat", "core", "rewrite")
    add("v25_nat_add_comm", "(a b : Nat) : a + b = b + a",
        ["omega", "exact Nat.add_comm a b", "ring", "simp [Nat.add_comm]"],
        "nat", "mathlib", "rewrite")
    add("v25_nat_add_assoc", "(a b c : Nat) : a + b + c = a + (b + c)",
        ["omega", "exact Nat.add_assoc a b c", "ring"],
        "nat", "mathlib", "rewrite")
    add("v25_nat_mul_one", "(n : Nat) : n * 1 = n",
        ["simp", "exact Nat.mul_one n", "ring", "omega"],
        "nat", "mathlib", "rewrite")
    add("v25_nat_mul_zero", "(n : Nat) : n * 0 = 0",
        ["rfl", "simp", "exact Nat.mul_zero n"],
        "nat", "core", "rewrite")
    add("v25_nat_le_refl", "(n : Nat) : n ≤ n",
        ["exact Nat.le_refl n", "omega", "exact le_refl n", "simp"],
        "nat", "mathlib", "rewrite")
    add("v25_nat_le_succ", "(n : Nat) : n ≤ n + 1",
        ["omega", "exact Nat.le_succ n", "simp"],
        "nat", "mathlib", "rewrite")
    add("v25_nat_add_one_eq", "(a b : Nat) (h : a = b) : a + 1 = b + 1",
        ["omega", "rw [h]", "exact congrArg (· + 1) h", "simp [h]"],
        "nat", "core", "rewrite")

    # ---- 2. List ----
    add("v25_list_append_nil", "(α : Type) (xs : List α) : xs ++ [] = xs",
        ["simp", "exact List.append_nil xs"],
        "list", "mathlib", "rewrite")
    add("v25_list_nil_append", "(α : Type) (xs : List α) : [] ++ xs = xs",
        ["rfl", "simp", "exact List.nil_append xs"],
        "list", "core", "rewrite")
    # NB: a plain `(x :: xs).length = xs.length + 1` is identical to a v18
    # core-Lean theorem (same statement/state/rfl/simp triple), so the v18
    # leakage guard would drop it entirely. Use the distinct append-length
    # shape instead so this benchmark item is genuinely novel vs v18.
    add("v25_list_length_append",
        "(α : Type) (xs ys : List α) : (xs ++ ys).length = xs.length + ys.length",
        ["simp", "rw [List.length_append]", "exact List.length_append xs ys"],
        "list", "mathlib", "rewrite")
    add("v25_list_reverse_nil", "(α : Type) : ([] : List α).reverse = []",
        ["rfl", "simp"],
        "list", "core", "rewrite")
    add("v25_list_length_reverse",
        "(α : Type) (xs : List α) : xs.reverse.length = xs.length",
        ["simp", "exact List.length_reverse xs"],
        "list", "mathlib", "rewrite")
    add("v25_list_map_id", "(α : Type) (xs : List α) : xs.map id = xs",
        ["simp", "exact List.map_id xs"],
        "list", "mathlib", "rewrite")
    add("v25_list_mem_cons_self",
        "(α : Type) (x : α) (xs : List α) : x ∈ x :: xs",
        ["simp", "exact List.mem_cons_self x xs"],
        "list", "mathlib", "destruct")

    # ---- 3. Bool / Option ----
    add("v25_bool_true_and", "(b : Bool) : (true && b) = b",
        ["rfl", "simp"],
        "bool_option", "core", "rewrite")
    add("v25_bool_and_true", "(b : Bool) : (b && true) = b",
        ["simp", "exact Bool.and_true b", "cases b <;> rfl"],
        "bool_option", "mathlib", "rewrite")
    add("v25_bool_not_not", "(b : Bool) : (!!b) = b",
        ["simp", "exact Bool.not_not b", "cases b <;> rfl"],
        "bool_option", "mathlib", "rewrite")
    add("v25_option_map_id", "(α : Type) (o : Option α) : o.map id = o",
        ["simp", "exact Option.map_id_fun' ▸ rfl", "cases o <;> rfl"],
        "bool_option", "mathlib", "rewrite")
    add("v25_option_some_isSome", "(α : Type) (a : α) : (some a).isSome = true",
        ["rfl", "simp"],
        "bool_option", "core", "rewrite")
    add("v25_bool_decide_true", ": (true = true)",
        ["rfl", "decide", "simp"],
        "bool_option", "core", "rewrite")

    # ---- 4. Set ----
    add("v25_set_mem_singleton", "(α : Type) (a : α) : a ∈ ({a} : Set α)",
        ["rfl", "simp", "exact Set.mem_singleton a", "exact rfl"],
        "set", "mathlib", "destruct")
    add("v25_set_subset_refl", "(α : Type) (s : Set α) : s ⊆ s",
        ["exact subset_refl s", "exact le_refl s", "intro x h; exact h",
         "exact fun x h => h"],
        "set", "mathlib", "intro")
    add("v25_set_mem_univ", "(α : Type) (a : α) : a ∈ (Set.univ : Set α)",
        ["trivial", "simp", "exact Set.mem_univ a"],
        "set", "mathlib", "destruct")
    add("v25_set_empty_subset", "(α : Type) (s : Set α) : (∅ : Set α) ⊆ s",
        ["intro x h; exact absurd h (by simp)", "exact Set.empty_subset s",
         "simp"],
        "set", "mathlib", "intro")
    add("v25_set_inter_subset_left",
        "(α : Type) (s t : Set α) : s ∩ t ⊆ s",
        ["exact Set.inter_subset_left", "intro x h; exact h.1",
         "exact fun x h => h.1"],
        "set", "mathlib", "intro")

    # ---- 5. Logic (broad-core-shaped + Mathlib tactics) ----
    add("v25_logic_imp_self", "(p : Prop) : p → p",
        ["exact id", "intro h; exact h", "exact fun h => h", "tauto"],
        "logic", "core", "intro")
    add("v25_logic_and_symm", "(p q : Prop) (h : p ∧ q) : q ∧ p",
        ["exact ⟨h.2, h.1⟩", "exact And.symm h", "exact h.symm", "tauto"],
        "logic", "core", "project_conjunction")
    add("v25_logic_or_symm", "(p q : Prop) (h : p ∨ q) : q ∨ p",
        ["exact h.symm", "exact Or.symm h", "tauto",
         "rcases h with hp | hq\n  · exact Or.inr hp\n  · exact Or.inl hq"],
        "logic", "core", "disjunction_cases")
    add("v25_logic_em", "(p : Prop) : p ∨ ¬p",
        ["exact Classical.em p", "exact em p", "tauto", "by_cases h : p <;> simp [h]"],
        "logic", "mathlib", "disjunction_cases")
    add("v25_logic_and_imp", "(p q : Prop) (hp : p) (hq : q) : p ∧ q",
        ["exact ⟨hp, hq⟩", "exact And.intro hp hq", "constructor <;> assumption",
         "tauto"],
        "logic", "core", "project_conjunction")
    add("v25_logic_modus_ponens", "(p q : Prop) (hpq : p → q) (hp : p) : q",
        ["exact hpq hp", "apply hpq; exact hp", "tauto"],
        "logic", "core", "intro")
    add("v25_logic_iff_refl", "(p : Prop) : p ↔ p",
        ["exact Iff.rfl", "rfl", "tauto", "constructor <;> intro h <;> exact h"],
        "logic", "core", "intro")
    add("v25_logic_not_intro", "(p : Prop) (h : p → False) : ¬p",
        ["exact h", "intro hp; exact h hp", "exact fun hp => h hp"],
        "logic", "core", "intro_negation")

    return plan


# --------------------------------------------------------------------------
# state_before reconstruction (generic binder brackets)
# --------------------------------------------------------------------------
_CLOSE = {"(": ")", "{": "}", "[": "]", "⦃": "⦄"}


def state_before(stmt: str) -> str:
    """Reconstruct a Lean-style goal state from a `binders : goal` statement.

    Handles `(...)`, `{...}`, `[...]`, `⦃...⦄` binder groups. Implicit/instance
    binders are shown with their brackets so the state mirrors Lean's pp."""
    s = stmt.strip()
    bindings: List[Tuple[str, str]] = []  # (open_bracket, inner)
    rest = s
    while rest and rest[0] in _CLOSE:
        opener = rest[0]
        closer = _CLOSE[opener]
        depth = 0
        for i, c in enumerate(rest):
            if c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    bindings.append((opener, rest[1:i]))
                    rest = rest[i + 1:].lstrip()
                    break
        else:
            break
    goal = rest[1:].strip() if rest.startswith(":") else rest
    lines: List[str] = []
    for opener, inner in bindings:
        if ":" in inner:
            names_part, type_part = inner.split(":", 1)
            tp = type_part.strip()
            names = names_part.split()
            joined = " ".join(names)
            if opener == "(":
                lines.append(f"{joined} : {tp}")
            elif opener == "{":
                lines.append(f"{{{joined} : {tp}}}")
            elif opener == "[":
                lines.append(f"[{joined} : {tp}]")
            else:
                lines.append(f"⦃{joined} : {tp}⦄")
        else:
            lines.append(inner.strip())
    return "\n".join(lines + [f"⊢ {goal}"])


# --------------------------------------------------------------------------
# Mathlib verifier (whole-file typecheck inside the scratch project)
# --------------------------------------------------------------------------
def make_mathlib_verifier(scratch: Path, timeout: float):
    runner = LeanCliRunner(command="lake env lean", working_dir=scratch)

    def verify(theorem_name: str, statement: str, tactic: str) -> Dict[str, Any]:
        seed = TheoremSeed(
            theorem_name=theorem_name,
            theorem_statement=statement,
            template=f"example {statement} := by\n  __TACTIC__",
            placeholder="__TACTIC__",
            imports=[MATHLIB_IMPORT],
        )
        state0 = runner.start(seed)
        t0 = time.perf_counter()
        try:
            res = runner.run_tactic(state0, tactic, timeout=timeout)
        finally:
            runner.close()
        return {"success": bool(res.success), "error": res.error,
                "elapsed_ms": (time.perf_counter() - t0) * 1000.0}

    return verify


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
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--out-seeds", default=str(ROOT / "data" / "seeds"
                                               / "v25_mathlib_tierc_seeds.jsonl"))
    ap.add_argument("--out-candidates", default=str(ROOT / "data" / "manual"
                                                    / "v25_mathlib_tierc_candidates.jsonl"))
    ap.add_argument("--out-verified", default=str(ROOT / "data" / "traces"
                                                  / "v25_mathlib_tierc_verified.jsonl"))
    ap.add_argument("--out-failed", default=str(ROOT / "data" / "traces"
                                                / "v25_mathlib_tierc_failed.jsonl"))
    ap.add_argument("--out-train-rows", default=str(ROOT / "data" / "processed"
                                                    / "v25_mathlib_tierc_corpus" / "train_rows.jsonl"))
    ap.add_argument("--summary", default=str(ROOT / "data" / "processed"
                                             / "v25_mathlib_tierc_corpus" / "summary.json"))
    ap.add_argument("--verifier-timeout", type=float, default=60.0)
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    plan = build_plan()
    logger.info("v25 tier-C plan: %d theorems", len(plan))
    verifier = make_mathlib_verifier(scratch, args.verifier_timeout)
    wu = verifier("__v25_warmup__", "(n : Nat) : n + 0 = n", "rfl")
    logger.info("warmup (import Mathlib) success=%s", wu.get("success"))
    if not wu.get("success"):
        logger.error("Mathlib warmup FAILED: %s", (wu.get("error") or "")[:200])
        return 2
    v18_names, v18_triples = _v18_sets()

    for p in (args.out_seeds, args.out_candidates, args.out_verified,
              args.out_failed, args.out_train_rows):
        Path(p).parent.mkdir(parents=True, exist_ok=True)

    seeds, verified, failed, train_rows = [], [], [], []
    per_cat: Dict[str, Dict[str, int]] = {}
    n_timeout = dn = dt = 0
    zero_success: List[str] = []

    for entry in plan:
        nm, stmt = entry["theorem_name"], entry["theorem_statement"]
        cat = entry["category"]
        st = state_before(stmt)
        d = per_cat.setdefault(cat, {"theorems": 0, "proposed": 0,
                                     "verified": 0, "failed": 0})
        d["theorems"] += 1
        seeds.append({"theorem_name": nm, "theorem_statement": stmt,
                      "state_before": st,
                      "template": f"example {stmt} := by\n  __TACTIC__",
                      "placeholder": "__TACTIC__", "imports": [MATHLIB_IMPORT],
                      "category": cat, "transfer": entry["transfer"],
                      "required_operation": entry["required_operation"],
                      "source": "v25_mathlib_tierc", "mathlib": True})
        any_ok = False
        for cand in entry["candidates"]:
            d["proposed"] += 1
            res = verifier(nm, stmt, cand)
            if (not res.get("success")) and (res.get("error") or "").startswith("timeout"):
                res2 = verifier(nm, stmt, cand)
                if res2.get("success"):
                    res = res2
            ok = bool(res.get("success"))
            err1 = ((res.get("error") or "").splitlines() or [""])[0][:90]
            rec = {"theorem_name": nm, "theorem_statement": stmt,
                   "state_before": st, "tactic": cand, "category": cat,
                   "transfer": entry["transfer"],
                   "required_operation": entry["required_operation"],
                   "imports": [MATHLIB_IMPORT], "corpus_source": "v25_mathlib_tierc",
                   "verifier": "lean-cli (lake env lean, import Mathlib)",
                   "verifier_timeout_s": args.verifier_timeout, "mathlib": True}
            if not ok:
                d["failed"] += 1
                if (res.get("error") or "").startswith("timeout"):
                    n_timeout += 1
                failed.append({**rec, "verified": False, "error_head": err1})
                logger.info("  FAIL %s :: %r err=%s", nm, cand, err1)
                continue
            # leakage guards vs v18
            if nm in v18_names:
                dn += 1
                continue
            if (stmt, st, cand) in v18_triples:
                dt += 1
                continue
            any_ok = True
            d["verified"] += 1
            verified.append({**rec, "verified": True})
            train_rows.append({"theorem_name": nm, "theorem_statement": stmt,
                               "state_before": st, "tactic": cand,
                               "category": cat, "family": cat,
                               "required_operation": entry["required_operation"],
                               "corpus_source": "v25_mathlib_tierc",
                               "tactic_source": "verified", "split": "train",
                               "transfer": entry["transfer"], "mathlib": True})
            logger.info("  OK   %s :: %r (%.1fs)", nm, cand,
                        res.get("elapsed_ms", 0) / 1000.0)
        if not any_ok:
            zero_success.append(nm)

    def _dump(path, rows):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    _dump(args.out_seeds, seeds)
    _dump(args.out_candidates, verified)  # manual reference = verified targets
    _dump(args.out_verified, verified)
    _dump(args.out_failed, failed)
    _dump(args.out_train_rows, train_rows)

    summary = {
        "mathlib_available": True,
        "lean_command": "lake env lean (import Mathlib) in " + str(scratch),
        "imports_used": [MATHLIB_IMPORT],
        "n_theorems": len(plan),
        "n_candidates_proposed": sum(d["proposed"] for d in per_cat.values()),
        "n_candidates_verified": len(verified),
        "n_candidates_failed": len(failed),
        "n_timeout": n_timeout,
        "n_zero_success_theorems": len(zero_success),
        "zero_success_theorems": zero_success,
        "n_dropped_by_v18_name_guard": dn,
        "n_dropped_by_v18_triple_guard": dt,
        "by_category": per_cat,
        "categories": sorted(per_cat),
        "uses_state_after": False, "uses_manual_oracle": False,
        "uses_mathlib": True}
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
    logger.info("v25 tier-C: theorems=%d verified=%d/%d failed=%d timeout=%d "
                "zero_success=%d v18 drops name/triple=%d/%d",
                len(plan), len(verified), summary["n_candidates_proposed"],
                len(failed), n_timeout, len(zero_success), dn, dt)
    for cat, d in sorted(per_cat.items()):
        logger.info("  %-12s verified=%d/%d (theorems=%d, zero_succ_in_cat=%d)",
                    cat, d["verified"], d["proposed"], d["theorems"],
                    sum(1 for z in zero_success if any(
                        e["theorem_name"] == z and e["category"] == cat for e in plan)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
