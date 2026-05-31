"""Mini-ELF v18 — Part 2/3: generate + verify the broad core-Lean corpus.

Hand-authored (parameterised) theorem set spanning 10 categories,
deliberately less templated than v11 LOFO. The corpus is a
single Python source file because the v18 brief asks for **varied,
not Cartesian-templated** statements.

Honesty contract (verbatim, v18 brief):
  * Do not use state_after.
  * Do not use manual oracle outputs as model predictions.
    (These rows ARE manual templates; they are *gold labels* for
    training/verification, not model predictions.)
  * Do not revive leaked v10 metrics.
  * No Mathlib.

The script:
  1. Builds a plan of (theorem_statement, category,
     candidate_tactics, expected_tactic_head) tuples.
  2. Runs each candidate through lean-cli (timeout 60 s) after a
     warm-up theorem.
  3. Writes:
     * ``data/seeds/v18_broad_core_seeds.jsonl``  — 1 row / theorem.
     * ``data/manual/v18_broad_core_candidates.jsonl`` — 1 row /
        candidate-with-verify-result.
     * ``data/traces/v18_broad_core_verified.jsonl``  — verified
       (theorem, tactic) pairs (positive labels).
     * ``data/traces/v18_broad_core_failed.jsonl``  — failed
       candidates (for failure-taxonomy in Part 7).
     * ``data/processed/v18_broad_core/{train,test}.jsonl``  — a
       theorem-level 80/20 split, used by Part 6 if fine-tuning.
     * ``data/processed/v18_broad_core/summary.json``  — counts.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import make_lean_cli_verifier  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_v18_broad_core_corpus")


# --------------------------------------------------------------------------- #
# Theorem specifications
# --------------------------------------------------------------------------- #


# Each entry: (theorem_name, category, statement, [candidate_tactics],
#              expected_tactic_head, difficulty)
# All statements are core Lean 4, no Mathlib imports.
PLAN: List[Tuple[str, str, str, List[str], str, str]] = [
    # ---------------- 1. implication / intro ---------------------------------
    ("v18_imp_p_self",          "implication", "(p : Prop) (hp : p) : p",
        ["exact hp", "exact hp.elim", "trivial"], "exact", "trivial"),
    ("v18_imp_intro_basic",     "implication", "(p q : Prop) (hp : p) : q → p",
        ["intro hq\n  exact hp", "intro _\n  exact hp", "exact fun _ => hp"], "intro", "easy"),
    ("v18_imp_chain",           "implication",
        "(p q r : Prop) (hpq : p → q) (hqr : q → r) (hp : p) : r",
        ["exact hqr (hpq hp)", "apply hqr; exact hpq hp",
         "intro _\n  exact hqr (hpq hp)"], "exact", "easy"),
    ("v18_imp_swap_args",       "implication",
        "(p q r : Prop) (h : p → q → r) (hq : q) (hp : p) : r",
        ["exact h hp hq", "exact (h hp) hq", "apply h; exact hp; exact hq"],
        "exact", "easy"),
    ("v18_imp_compose",         "implication",
        "(α β γ : Type) (f : α → β) (g : β → γ) (a : α) : γ",
        ["exact g (f a)", "exact (g ∘ f) a", "apply g; exact f a"],
        "exact", "easy"),
    ("v18_imp_arrow_arrow",     "implication",
        "(p q : Prop) (h : (p → q) → p) (hpq : p → q) : p",
        ["exact h hpq", "apply h; exact hpq"], "exact", "easy"),

    # ---------------- 2. conjunction intro/elimination -----------------------
    ("v18_and_intro",           "conjunction",
        "(p q : Prop) (hp : p) (hq : q) : p ∧ q",
        ["exact ⟨hp, hq⟩", "exact And.intro hp hq", "constructor; exact hp; exact hq",
         "And.intro hp hq"], "exact", "trivial"),
    ("v18_and_left",            "conjunction",
        "(p q : Prop) (h : p ∧ q) : p",
        ["exact h.1", "exact h.left", "cases h with | intro hp _ => exact hp",
         "exact And.left h"], "exact", "trivial"),
    ("v18_and_right",           "conjunction",
        "(p q : Prop) (h : p ∧ q) : q",
        ["exact h.2", "exact h.right", "cases h with | intro _ hq => exact hq"],
        "exact", "trivial"),
    ("v18_and_swap",            "conjunction",
        "(p q : Prop) (h : p ∧ q) : q ∧ p",
        ["exact ⟨h.2, h.1⟩", "exact ⟨h.right, h.left⟩",
         "cases h with | intro hp hq => exact ⟨hq, hp⟩"], "exact", "easy"),
    ("v18_and_assoc_one",       "conjunction",
        "(p q r : Prop) (h : p ∧ q ∧ r) : (p ∧ q) ∧ r",
        ["exact ⟨⟨h.1, h.2.1⟩, h.2.2⟩",
         "cases h with | intro hp hqr => exact ⟨⟨hp, hqr.1⟩, hqr.2⟩"],
        "exact", "moderate"),
    ("v18_and_proj_3rd",        "conjunction",
        "(p q r : Prop) (h : p ∧ q ∧ r) : r",
        ["exact h.2.2", "exact h.right.right",
         "cases h with | intro _ hqr => exact hqr.2"], "exact", "easy"),

    # ---------------- 3. disjunction cases -----------------------------------
    ("v18_or_inl",              "disjunction",
        "(p q : Prop) (hp : p) : p ∨ q",
        ["exact Or.inl hp", "left; exact hp", "exact .inl hp"],
        "exact", "trivial"),
    ("v18_or_inr",              "disjunction",
        "(p q : Prop) (hq : q) : p ∨ q",
        ["exact Or.inr hq", "right; exact hq", "exact .inr hq"],
        "exact", "trivial"),
    ("v18_or_swap",             "disjunction",
        "(p q : Prop) (h : p ∨ q) : q ∨ p",
        ["cases h with | inl hp => exact Or.inr hp | inr hq => exact Or.inl hq",
         "exact h.elim (fun hp => Or.inr hp) (fun hq => Or.inl hq)"],
        "cases", "easy"),
    ("v18_or_elim_to_common",   "disjunction",
        "(p q r : Prop) (h : p ∨ q) (hpr : p → r) (hqr : q → r) : r",
        ["exact h.elim hpr hqr",
         "cases h with | inl hp => exact hpr hp | inr hq => exact hqr hq"],
        "exact", "easy"),
    ("v18_or_constant",         "disjunction",
        "(p : Prop) (h : p ∨ p) : p",
        ["exact h.elim id id", "cases h with | inl hp => exact hp | inr hp => exact hp"],
        "exact", "easy"),

    # ---------------- 4. negation / contradiction ----------------------------
    ("v18_neg_not_intro",       "negation",
        "(p : Prop) (h : p → False) : ¬p",
        ["exact h", "intro hp\n  exact h hp", "exact fun hp => h hp"],
        "exact", "trivial"),
    ("v18_neg_absurd",          "negation",
        "(p : Prop) (hp : p) (hnp : ¬p) : False",
        ["exact hnp hp", "exact absurd hp hnp", "contradiction"],
        "exact", "trivial"),
    ("v18_neg_double_in",       "negation",
        "(p : Prop) (hp : p) : ¬¬p",
        ["intro hnp\n  exact hnp hp", "exact fun hnp => hnp hp"],
        "intro", "easy"),
    ("v18_neg_modus_tollens",   "negation",
        "(p q : Prop) (h : p → q) (hnq : ¬q) : ¬p",
        ["intro hp\n  exact hnq (h hp)", "exact fun hp => hnq (h hp)"],
        "intro", "easy"),
    ("v18_neg_or_left",         "negation",
        "(p q : Prop) (h : ¬(p ∨ q)) : ¬p",
        ["intro hp\n  exact h (Or.inl hp)",
         "exact fun hp => h (Or.inl hp)"], "intro", "moderate"),

    # ---------------- 5. equality rewrite ------------------------------------
    ("v18_eq_refl_nat",         "equality_rewrite",
        "(n : Nat) : n = n", ["rfl", "exact rfl"], "rfl", "trivial"),
    ("v18_eq_symm",             "equality_rewrite",
        "(n m : Nat) (h : n = m) : m = n",
        ["exact h.symm", "rw [h]", "exact Eq.symm h"], "exact", "easy"),
    ("v18_eq_trans",            "equality_rewrite",
        "(a b c : Nat) (h1 : a = b) (h2 : b = c) : a = c",
        ["exact h1.trans h2", "rw [h1]; exact h2",
         "exact Eq.trans h1 h2", "exact h1 ▸ h2"], "exact", "easy"),
    ("v18_eq_subst_lhs",        "equality_rewrite",
        "(n m k : Nat) (h : n = m) : n + k = m + k",
        ["rw [h]", "exact h ▸ rfl", "exact congrArg (· + k) h"],
        "rw", "easy"),
    ("v18_eq_subst_rhs",        "equality_rewrite",
        "(n m k : Nat) (h : n = m) : k + n = k + m",
        ["rw [h]", "exact h ▸ rfl",
         "exact congrArg (k + ·) h"], "rw", "easy"),
    ("v18_eq_double_apply",     "equality_rewrite",
        "(n m : Nat) (h : n = m) (f : Nat → Nat) : f n = f m",
        ["rw [h]", "exact congrArg f h"], "rw", "moderate"),

    # ---------------- 6. exists intro / elimination --------------------------
    ("v18_exists_intro_nat",    "exists",
        "(p : Nat → Prop) (h : p 3) : ∃ n, p n",
        ["exact ⟨3, h⟩", "exact Exists.intro 3 h", "use 3; exact h"],
        "exact", "trivial"),
    ("v18_exists_intro_eq",     "exists",
        "(n : Nat) : ∃ m, n = m", ["exact ⟨n, rfl⟩", "use n"], "exact", "easy"),
    ("v18_exists_relabel",      "exists",
        "(p : Nat → Prop) (h : ∃ n, p n) : ∃ m, p m",
        ["exact h", "cases h with | intro n hn => exact ⟨n, hn⟩"],
        "exact", "easy"),
    ("v18_exists_compose",      "exists",
        "(p q : Nat → Prop) (h : ∃ n, p n) (hpq : ∀ n, p n → q n) : ∃ n, q n",
        ["cases h with | intro n hn => exact ⟨n, hpq n hn⟩",
         "exact h.elim (fun n hn => ⟨n, hpq n hn⟩)"], "cases", "moderate"),

    # ---------------- 7. forall instantiation --------------------------------
    ("v18_forall_inst_at_7",    "forall",
        "(p : Nat → Prop) (h : ∀ n, p n) : p 7",
        ["exact h 7", "apply h"], "exact", "trivial"),
    ("v18_forall_inst_compose", "forall",
        "(p q : Nat → Prop) (h : ∀ n, p n → q n) (hp : p 5) : q 5",
        ["exact h 5 hp", "apply h; exact hp"], "exact", "easy"),
    ("v18_forall_to_arrow",     "forall",
        "(p q : Nat → Prop) (h : ∀ n, p n → q n) : p 3 → q 3",
        ["exact h 3", "intro hp\n  exact h 3 hp"], "exact", "easy"),

    # ---------------- 8. Nat equality / succ / zero --------------------------
    ("v18_nat_succ_unfold",     "nat_succ",
        "(n : Nat) : n.succ = n + 1", ["rfl"], "rfl", "trivial"),
    ("v18_nat_zero_add",        "nat_succ",
        "(n : Nat) : 0 + n = n", ["exact Nat.zero_add n", "simp",
                                  "induction n with | zero => rfl | succ k ih => simp [ih]"],
        "exact", "easy"),
    ("v18_nat_add_zero",        "nat_succ",
        "(n : Nat) : n + 0 = n", ["rfl", "exact Nat.add_zero n"], "rfl", "trivial"),
    ("v18_nat_succ_inj",        "nat_succ",
        "(n m : Nat) (h : n.succ = m.succ) : n = m",
        ["exact Nat.succ.inj h", "injection h", "cases h; rfl"],
        "exact", "moderate"),
    ("v18_nat_add_one_eq_succ", "nat_succ",
        "(n : Nat) : n + 1 = n.succ", ["rfl"], "rfl", "trivial"),

    # ---------------- 9. Bool cases ------------------------------------------
    ("v18_bool_true_or_false",  "bool",
        "(b : Bool) : b = true ∨ b = false",
        ["cases b with | true => exact Or.inl rfl | false => exact Or.inr rfl",
         "cases b\n  · exact Or.inl rfl\n  · exact Or.inr rfl"], "cases", "easy"),
    ("v18_bool_and_left",       "bool",
        "(b : Bool) (h : (b && true) = true) : b = true",
        ["rw [Bool.and_true] at h; exact h", "simp at h; exact h"],
        "rw", "moderate"),
    ("v18_bool_not_not",        "bool",
        "(b : Bool) : !!b = b",
        ["cases b <;> rfl",
         "cases b with | true => rfl | false => rfl"], "cases", "easy"),

    # ---------------- 10. List simple ----------------------------------------
    ("v18_list_append_nil",     "list",
        "(α : Type) (xs : List α) : xs ++ [] = xs",
        ["exact List.append_nil xs",
         "induction xs with | nil => rfl | cons _ _ ih => simp [ih]"],
        "exact", "easy"),
    ("v18_list_nil_append",     "list",
        "(α : Type) (xs : List α) : [] ++ xs = xs", ["rfl"], "rfl", "trivial"),
    ("v18_list_length_cons",    "list",
        "(α : Type) (x : α) (xs : List α) : (x :: xs).length = xs.length + 1",
        ["rfl", "simp"], "rfl", "trivial"),
    ("v18_list_singleton_len",  "list",
        "(α : Type) (x : α) : [x].length = 1", ["rfl"], "rfl", "trivial"),
    ("v18_list_head_some",      "list",
        "(α : Type) (x : α) (xs : List α) : (x :: xs).head? = some x",
        ["rfl"], "rfl", "trivial"),
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _state_before(stmt: str) -> str:
    """Mirror v16/v17 state-rendering. Pure-text."""
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


def _theorem_split(plan: List[Any], *, seed: int = 0,
                   test_frac: float = 0.15, val_frac: float = 0.15,
                   ) -> Dict[str, set]:
    """Theorem-level split by name, stratified by category for v18.
    Returns {'train': set, 'val': set, 'test': set} of theorem_names."""
    rng = random.Random(seed)
    by_cat: Dict[str, List[str]] = {}
    for nm, cat, *_ in plan:
        by_cat.setdefault(cat, []).append(nm)
    splits = {"train": set(), "val": set(), "test": set()}
    for cat, names in by_cat.items():
        rng.shuffle(names)
        n = len(names)
        n_test = max(1, int(n * test_frac))
        n_val = max(1, int(n * val_frac))
        splits["test"].update(names[:n_test])
        splits["val"].update(names[n_test:n_test + n_val])
        splits["train"].update(names[n_test + n_val:])
    return splits


def _classify_error(err: Optional[str]) -> str:
    """Categorize lean error messages for the v18 failure taxonomy."""
    if err is None:
        return "ok"
    s = err.lower()
    if "timeout" in s:
        return "timeout"
    if "type mismatch" in s or "expected to have type" in s:
        return "type_mismatch"
    if "unknown identifier" in s:
        return "unknown_identifier"
    if "unknown tactic" in s:
        return "unknown_tactic"
    if "unknown constant" in s or "unknown module" in s:
        return "environment_or_import_issue"
    if ("simp_lemmas" in s or "simp made no progress" in s):
        return "simp_no_progress"
    if "unexpected" in s or "expected " in s or "unexpected end" in s:
        return "parse_error"
    if "unsolved goals" in s:
        return "unsolved_goals"
    if "invalid" in s:
        return "invalid"
    return "other"


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out-seeds",
                    default=str(ROOT / "data" / "seeds"
                                / "v18_broad_core_seeds.jsonl"))
    ap.add_argument("--out-candidates",
                    default=str(ROOT / "data" / "manual"
                                / "v18_broad_core_candidates.jsonl"))
    ap.add_argument("--out-verified",
                    default=str(ROOT / "data" / "traces"
                                / "v18_broad_core_verified.jsonl"))
    ap.add_argument("--out-failed",
                    default=str(ROOT / "data" / "traces"
                                / "v18_broad_core_failed.jsonl"))
    ap.add_argument("--out-processed-root",
                    default=str(ROOT / "data" / "processed"
                                / "v18_broad_core"))
    ap.add_argument("--verifier-timeout", type=float, default=60.0)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    # Set up output paths.
    out_seeds = Path(args.out_seeds)
    out_cands = Path(args.out_candidates)
    out_verif = Path(args.out_verified)
    out_fail = Path(args.out_failed)
    out_proc = Path(args.out_processed_root)
    for p in (out_seeds, out_cands, out_verif, out_fail):
        p.parent.mkdir(parents=True, exist_ok=True)
    out_proc.mkdir(parents=True, exist_ok=True)

    # Verifier.
    verifier = make_lean_cli_verifier(timeout=args.verifier_timeout)
    t0 = time.perf_counter()
    wu = verifier("__v18_warmup__", "(x : Nat) : x = x", "rfl")
    logger.info("warmup: success=%s elapsed_ms=%.1f",
                wu.get("success"), (time.perf_counter() - t0) * 1000.0)

    # Theorem-level split.
    splits = _theorem_split(PLAN, seed=args.seed)
    name_to_split = {nm: split
                     for split, names in splits.items() for nm in names}

    seeds: List[Dict[str, Any]] = []
    candidates_all: List[Dict[str, Any]] = []
    verified: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    by_category: Dict[str, Dict[str, int]] = {}
    by_error_class: Dict[str, int] = {}
    zero_success: List[str] = []
    n_timeout = 0

    for nm, cat, stmt, cands, expected_head, difficulty in PLAN:
        state = _state_before(stmt)
        split = name_to_split.get(nm, "train")
        seed = {
            "theorem_name": nm,
            "theorem_statement": stmt,
            "state_before": state,
            "template": f"example {stmt} := by\n  __TACTIC__",
            "placeholder": "__TACTIC__",
            "imports": [],
            "category": cat,
            "difficulty": difficulty,
            "expected_tactic_head": expected_head,
            "source": "v18_broad_core",
            "uses_mathlib": False,
            "split": split,
        }
        seeds.append(seed)
        per_cat = by_category.setdefault(cat, {
            "theorems": 0, "candidates_proposed": 0,
            "candidates_verified": 0, "theorems_with_verified": 0,
        })
        per_cat["theorems"] += 1
        any_verified = False
        for cand in cands:
            per_cat["candidates_proposed"] += 1
            try:
                res = verifier(nm, stmt, cand)
            except Exception as exc:  # noqa: BLE001
                res = {"success": False, "error": f"verifier_exception:{exc}"}
            ok = bool(res.get("success"))
            err_class = _classify_error(res.get("error"))
            by_error_class[err_class] = by_error_class.get(err_class, 0) + 1
            if err_class == "timeout":
                n_timeout += 1
            row = {
                "theorem_name": nm,
                "theorem_statement": stmt,
                "state_before": state,
                "tactic": cand,
                "category": cat,
                "difficulty": difficulty,
                "required_operation": cat,
                "expected_tactic_head": expected_head,
                "corpus_source": "v18_broad_core",
                "tactic_source": "verified" if ok else "failed",
                "uses_mathlib": False,
                "verified": ok,
                "error_class": err_class,
                "error": (res.get("error") or "").splitlines()[0][:200]
                          if res.get("error") else None,
                "split": split,
                "regime": "v18_broad_core",
            }
            candidates_all.append(row)
            if ok:
                per_cat["candidates_verified"] += 1
                verified.append(row)
                any_verified = True
            else:
                failed.append(row)
        if any_verified:
            per_cat["theorems_with_verified"] += 1
        else:
            zero_success.append(nm)
            logger.warning("ZERO_SUCCESS %s (%s): %s",
                           nm, cat, " | ".join(cands[:2])[:120])

    # Persist.
    def _write(rows, p: Path):
        with p.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    _write(seeds, out_seeds)
    _write(candidates_all, out_cands)
    _write(verified, out_verif)
    _write(failed, out_fail)

    # Per-split jsonl files (theorem-level train/val/test split).
    train_rows = [r for r in verified if r["split"] == "train"]
    val_rows = [r for r in verified if r["split"] == "val"]
    test_rows = [r for r in verified if r["split"] == "test"]
    _write(train_rows, out_proc / "train.jsonl")
    _write(val_rows, out_proc / "val.jsonl")
    _write(test_rows, out_proc / "test.jsonl")

    summary = {
        "n_theorems_planned": len(PLAN),
        "n_categories": len(by_category),
        "by_category": by_category,
        "by_error_class": by_error_class,
        "n_candidates_proposed": len(candidates_all),
        "n_candidates_verified": len(verified),
        "n_candidates_failed": len(failed),
        "n_timeout_candidates": n_timeout,
        "n_zero_success_theorems": len(zero_success),
        "zero_success_theorems": zero_success,
        "splits": {
            "train_theorems": len(splits["train"]),
            "val_theorems": len(splits["val"]),
            "test_theorems": len(splits["test"]),
            "train_candidate_rows": len(train_rows),
            "val_candidate_rows": len(val_rows),
            "test_candidate_rows": len(test_rows),
        },
        "uses_state_after": False,
        "uses_mathlib": False,
        "verifier_timeout_seconds": args.verifier_timeout,
    }
    (out_proc / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("v18 corpus done: theorems=%d candidates=%d verified=%d "
                "failed=%d timeout=%d zero_success_theorems=%d",
                len(PLAN), len(candidates_all), len(verified),
                len(failed), n_timeout, len(zero_success))
    for cat, d in sorted(by_category.items()):
        logger.info("  cat=%-22s theorems=%-3d verified_cands=%-3d "
                    "(theorems_with_verified=%d)",
                    cat, d["theorems"], d["candidates_verified"],
                    d["theorems_with_verified"])
    logger.info("error classes: %s",
                {k: v for k, v in sorted(by_error_class.items())})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
