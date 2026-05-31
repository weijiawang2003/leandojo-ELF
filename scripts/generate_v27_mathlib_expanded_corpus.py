"""Mini-ELF v27 — Part 4: expanded Mathlib specialist corpus + verification.

Builds an expanded, **Set-heavy** set of tiny Mathlib-tier theorems (categories
A–F from the v27 plan: Set, order/≤, Nat arithmetic/simp, List, Logic, and
Option/Bool/Function), each with several concrete candidate tactics, and verifies
**every** candidate by whole-file ``import Mathlib`` typecheck using the **trusted**
batched verifier (`mini_elf_lean.mathlib_batched_verifier.TrustedMathlibVerifier`:
sentinel + confirm + rescue — sound and complete, see V27 Part 1).

Only Lean-accepted candidates become training positives; failed candidates are
kept for the taxonomy but never used as positives. The manual reference candidates
are corpus *targets verified by Lean*, never fed to a model as predictions.

Leakage guards (every v27 train row must be clean):
  * drop any candidate matching a v18 broad-core theorem name or triple;
  * drop any candidate whose (statement, state_before, tactic) triple OR whose
    (statement, state_before) matches a v25 held-out test or v26 theorem-holdout
    test row (so the established benchmarks stay clean even when a v27 statement
    shape coincides);
  * all v27 theorem names are ``v27_*`` and distinct from v25/v26 names.
A candidate dropped by a guard still counts as a Lean success (not a coverage
gap) — reported separately, exactly as in v26.

Outputs:
  data/seeds/v27_mathlib_expanded_seeds.jsonl
  data/manual/v27_mathlib_expanded_candidates.jsonl     (verified targets)
  data/traces/v27_mathlib_expanded_verified.jsonl
  data/traces/v27_mathlib_expanded_failed.jsonl
  data/processed/v27_mathlib_specialist/expanded_train_rows.jsonl
  data/processed/v27_mathlib_specialist/expanded_summary.json

Honesty: real Mathlib typecheck (no mock), no state_after, no manual oracle as
predictions, Mathlib real & external, v18/v25/v26 leakage guards enforced.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from mini_elf_lean.mathlib_batched_verifier import TrustedMathlibVerifier, MATHLIB_IMPORT  # noqa: E402
from generate_v25_mathlib_tierc_corpus import state_before  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_v27_mathlib_expanded_corpus")
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"


# --------------------------------------------------------------------------- #
# Corpus plan (concrete tactics; the verifier filters to Lean-accepted ones)
# --------------------------------------------------------------------------- #
def build_plan() -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []

    def add(name, stmt, cands, cat, skill, family):
        plan.append({"theorem_name": f"v27_{name}", "theorem_statement": stmt,
                     "candidates": cands, "category": cat, "expected_skill": skill,
                     "theorem_family": family})

    # ===== A. SET (primary gap — membership iff, inter/union, subset) ===== #
    add("set_subset_refl", "(α : Type) (s : Set α) : s ⊆ s",
        ["intro x hx; exact hx", "exact fun x hx => hx", "exact Set.Subset.refl s",
         "exact subset_refl s", "exact le_refl s"], "set", "set", "subset_refl")
    add("set_inter_subset_left", "(α : Type) (s t : Set α) : s ∩ t ⊆ s",
        ["intro x hx; exact hx.1", "exact Set.inter_subset_left",
         "exact fun x hx => hx.1"], "set", "set", "inter_subset")
    add("set_inter_subset_right", "(α : Type) (s t : Set α) : s ∩ t ⊆ t",
        ["intro x hx; exact hx.2", "exact Set.inter_subset_right",
         "exact fun x hx => hx.2"], "set", "set", "inter_subset")
    add("set_subset_union_left", "(α : Type) (s t : Set α) : s ⊆ s ∪ t",
        ["intro x hx; exact Or.inl hx", "exact Set.subset_union_left",
         "intro x hx; left; exact hx"], "set", "set", "subset_union")
    add("set_subset_union_right", "(α : Type) (s t : Set α) : t ⊆ s ∪ t",
        ["intro x hx; exact Or.inr hx", "exact Set.subset_union_right",
         "intro x hx; right; exact hx"], "set", "set", "subset_union")
    add("set_union_subset", "(α : Type) (s t u : Set α) (h1 : s ⊆ u) (h2 : t ⊆ u) : s ∪ t ⊆ u",
        ["exact Set.union_subset h1 h2",
         "intro x hx; exact hx.elim (fun h => h1 h) (fun h => h2 h)"], "set", "set", "union_subset")
    add("set_subset_inter", "(α : Type) (s t u : Set α) (h1 : u ⊆ s) (h2 : u ⊆ t) : u ⊆ s ∩ t",
        ["exact Set.subset_inter h1 h2",
         "intro x hx; exact ⟨h1 hx, h2 hx⟩"], "set", "set", "subset_inter")
    add("set_mem_inter_iff", "(α : Type) (s t : Set α) (x : α) : x ∈ s ∩ t ↔ x ∈ s ∧ x ∈ t",
        ["exact Set.mem_inter_iff x s t", "exact Iff.rfl", "rfl",
         "constructor <;> intro h <;> exact h", "simp [Set.mem_inter_iff]"], "set", "set", "mem_iff")
    add("set_mem_union_iff", "(α : Type) (s t : Set α) (x : α) : x ∈ s ∪ t ↔ x ∈ s ∨ x ∈ t",
        ["exact Set.mem_union x s t", "exact Iff.rfl", "rfl",
         "simp [Set.mem_union]"], "set", "set", "mem_iff")
    add("set_mem_singleton", "(α : Type) (a : α) : a ∈ ({a} : Set α)",
        ["rfl", "exact rfl", "exact Set.mem_singleton a", "simp",
         "exact Set.mem_singleton_iff.mpr rfl"], "set", "set", "mem_singleton")
    add("set_mem_union_of_mem_left", "(α : Type) (s t : Set α) (x : α) (h : x ∈ s) : x ∈ s ∪ t",
        ["exact Or.inl h", "left; exact h", "exact Set.mem_union_left t h",
         "simp [h]"], "set", "set", "mem_union")
    add("set_mem_union_of_mem_right", "(α : Type) (s t : Set α) (x : α) (h : x ∈ t) : x ∈ s ∪ t",
        ["exact Or.inr h", "right; exact h", "exact Set.mem_union_right s h",
         "simp [h]"], "set", "set", "mem_union")
    # extra Set diversity (commutativity / assoc subset / diff / trans)
    add("set_inter_comm_subset", "(α : Type) (s t : Set α) : s ∩ t ⊆ t ∩ s",
        ["intro x hx; exact ⟨hx.2, hx.1⟩", "exact fun x hx => ⟨hx.2, hx.1⟩"], "set", "set", "inter_comm")
    add("set_union_comm_subset", "(α : Type) (s t : Set α) : s ∪ t ⊆ t ∪ s",
        ["intro x hx; exact hx.elim Or.inr Or.inl",
         "exact fun x hx => hx.elim Or.inr Or.inl"], "set", "set", "union_comm")
    add("set_mem_inter_left", "(α : Type) (s t : Set α) (x : α) (h : x ∈ s ∩ t) : x ∈ s",
        ["exact h.1", "exact h.left", "exact (Set.mem_inter_iff x s t).mp h |>.1"], "set", "set", "mem_inter_proj")
    add("set_mem_inter_right", "(α : Type) (s t : Set α) (x : α) (h : x ∈ s ∩ t) : x ∈ t",
        ["exact h.2", "exact h.right"], "set", "set", "mem_inter_proj")
    add("set_diff_subset", "(α : Type) (s t : Set α) : s \\ t ⊆ s",
        ["intro x hx; exact hx.1", "exact Set.diff_subset", "exact fun x hx => hx.1"], "set", "set", "diff_subset")
    add("set_subset_trans", "(α : Type) (s t u : Set α) (h1 : s ⊆ t) (h2 : t ⊆ u) : s ⊆ u",
        ["intro x hx; exact h2 (h1 hx)", "exact h1.trans h2",
         "exact Set.Subset.trans h1 h2"], "set", "set", "subset_trans")
    add("set_subset_inter_self", "(α : Type) (s : Set α) : s ⊆ s ∩ s",
        ["intro x hx; exact ⟨hx, hx⟩", "exact fun x hx => ⟨hx, hx⟩", "simp"], "set", "set", "inter_self")
    add("set_inter_self_subset", "(α : Type) (s : Set α) : s ∩ s ⊆ s",
        ["intro x hx; exact hx.1", "exact Set.inter_subset_left"], "set", "set", "inter_self")
    add("set_empty_subset", "(α : Type) (s : Set α) : (∅ : Set α) ⊆ s",
        ["exact Set.empty_subset s", "intro x hx; exact absurd hx (by simp)", "simp"], "set", "set", "empty_subset")
    add("set_subset_univ", "(α : Type) (s : Set α) : s ⊆ (Set.univ : Set α)",
        ["exact Set.subset_univ s", "intro x _; trivial", "simp"], "set", "set", "subset_univ")
    add("set_mem_univ", "(α : Type) (a : α) : a ∈ (Set.univ : Set α)",
        ["trivial", "exact Set.mem_univ a", "simp"], "set", "set", "mem_univ")

    # ===== B. ORDER / ≤ ===== #
    add("ord_le_refl", "(n : Nat) : n ≤ n",
        ["exact le_rfl", "exact Nat.le_refl n", "omega", "simp", "exact le_refl n"], "order", "order", "le_refl")
    add("ord_le_succ", "(n : Nat) : n ≤ n + 1",
        ["omega", "exact Nat.le_succ n", "simp", "exact Nat.le.intro rfl"], "order", "order", "le_succ")
    add("ord_le_add_right", "(n k : Nat) : n ≤ n + k",
        ["omega", "exact Nat.le_add_right n k", "simp"], "order", "order", "le_add")
    add("ord_le_add_left", "(n k : Nat) : n ≤ k + n",
        ["omega", "exact Nat.le_add_left n k", "simp"], "order", "order", "le_add")
    add("ord_le_succ_of_le", "(n m : Nat) (h : n ≤ m) : n ≤ m + 1",
        ["omega", "exact Nat.le_succ_of_le h", "exact le_trans h (Nat.le_succ m)"], "order", "order", "le_succ_of_le")
    add("ord_le_of_eq", "(n m : Nat) (h : n = m) : n ≤ m",
        ["omega", "exact h.le", "rw [h]", "exact Nat.le_of_eq h"], "order", "order", "le_of_eq")
    add("ord_le_trans", "(a b c : Nat) (h1 : a ≤ b) (h2 : b ≤ c) : a ≤ c",
        ["exact Nat.le_trans h1 h2", "omega", "exact le_trans h1 h2"], "order", "order", "le_trans")
    add("ord_succ_le_succ", "(n m : Nat) (h : n ≤ m) : Nat.succ n ≤ Nat.succ m",
        ["exact Nat.succ_le_succ h", "omega", "simp [h]"], "order", "order", "succ_le_succ")
    add("ord_zero_le", "(n : Nat) : 0 ≤ n",
        ["omega", "exact Nat.zero_le n", "simp"], "order", "order", "zero_le")
    add("ord_lt_succ_self", "(n : Nat) : n < n + 1",
        ["omega", "exact Nat.lt_succ_self n", "simp"], "order", "order", "lt_succ")
    add("ord_succ_pos", "(n : Nat) : 0 < n + 1",
        ["omega", "exact Nat.succ_pos n", "simp"], "order", "order", "succ_pos")
    add("ord_min_le_left", "(a b : Nat) : min a b ≤ a",
        ["exact Nat.min_le_left a b", "omega", "simp"], "order", "order", "min_max")
    add("ord_le_max_right", "(a b : Nat) : b ≤ max a b",
        ["exact Nat.le_max_right a b", "omega", "simp"], "order", "order", "min_max")

    # ===== C. NAT arithmetic / simp ===== #
    add("nat_add_zero", "(n : Nat) : n + 0 = n", ["rfl", "simp", "omega", "exact Nat.add_zero n"], "nat", "arithmetic", "add_zero")
    add("nat_zero_add", "(n : Nat) : 0 + n = n", ["simp", "omega", "exact Nat.zero_add n"], "nat", "arithmetic", "zero_add")
    add("nat_mul_one", "(n : Nat) : n * 1 = n", ["simp", "exact Nat.mul_one n", "ring", "omega"], "nat", "arithmetic", "mul_one")
    add("nat_one_mul", "(n : Nat) : 1 * n = n", ["simp", "exact Nat.one_mul n", "ring", "omega"], "nat", "arithmetic", "one_mul")
    add("nat_add_comm", "(a b : Nat) : a + b = b + a", ["omega", "exact Nat.add_comm a b", "ring"], "nat", "arithmetic", "add_comm")
    add("nat_add_assoc", "(a b c : Nat) : a + b + c = a + (b + c)", ["omega", "exact Nat.add_assoc a b c", "ring"], "nat", "arithmetic", "add_assoc")
    add("nat_add_assoc_rev", "(a b c : Nat) : a + (b + c) = a + b + c", ["omega", "exact (Nat.add_assoc a b c).symm", "ring"], "nat", "arithmetic", "add_assoc")
    add("nat_mul_comm", "(a b : Nat) : a * b = b * a", ["exact Nat.mul_comm a b", "ring", "ac_rfl"], "nat", "arithmetic", "mul_comm")
    add("nat_two_mul", "(n : Nat) : 2 * n = n + n", ["omega", "ring", "exact Nat.two_mul n"], "nat", "arithmetic", "two_mul")
    add("nat_succ_eq", "(n : Nat) : Nat.succ n = n + 1", ["rfl", "simp", "omega"], "nat", "arithmetic", "succ_eq")
    add("nat_add_sub_cancel", "(n m : Nat) : n + m - m = n", ["omega", "simp", "exact Nat.add_sub_cancel"], "nat", "arithmetic", "add_sub")
    add("nat_mul_zero", "(n : Nat) : n * 0 = 0", ["rfl", "simp", "exact Nat.mul_zero n"], "nat", "arithmetic", "mul_zero")

    # ===== D. LIST (prefer simp / arity-free lemma forms) ===== #
    add("list_append_nil", "(α : Type) (xs : List α) : xs ++ [] = xs", ["simp", "exact List.append_nil xs"], "list", "list", "append_nil")
    add("list_nil_append", "(α : Type) (xs : List α) : [] ++ xs = xs", ["rfl", "simp", "exact List.nil_append xs"], "list", "list", "nil_append")
    add("list_length_cons", "(α : Type) (x : α) (xs : List α) : (x :: xs).length = xs.length + 1",
        ["rfl", "simp", "exact List.length_cons"], "list", "list", "length_cons")
    add("list_length_append", "(α : Type) (xs ys : List α) : (xs ++ ys).length = xs.length + ys.length",
        ["simp", "rw [List.length_append]", "exact List.length_append xs ys"], "list", "list", "length_append")
    add("list_map_id", "(α : Type) (xs : List α) : xs.map id = xs", ["simp", "exact List.map_id xs"], "list", "list", "map_id")
    add("list_reverse_reverse", "(α : Type) (xs : List α) : xs.reverse.reverse = xs", ["simp", "exact List.reverse_reverse xs"], "list", "list", "reverse_reverse")
    add("list_append_assoc", "(α : Type) (xs ys zs : List α) : (xs ++ ys) ++ zs = xs ++ (ys ++ zs)",
        ["simp", "rw [List.append_assoc]", "exact List.append_assoc xs ys zs"], "list", "list", "append_assoc")
    add("list_map_map", "(α β γ : Type) (f : α → β) (g : β → γ) (xs : List α) : (xs.map f).map g = xs.map (g ∘ f)",
        ["simp", "rw [List.map_map]", "exact List.map_map g f xs"], "list", "list", "map_map")
    add("list_mem_cons_self", "(α : Type) (x : α) (xs : List α) : x ∈ x :: xs",
        ["simp", "exact List.mem_cons_self x xs", "exact List.mem_cons_self .."], "list", "list", "mem_cons")
    add("list_mem_append_left", "(α : Type) (x : α) (xs ys : List α) (h : x ∈ xs) : x ∈ xs ++ ys",
        ["exact List.mem_append_left ys h", "simp [h]", "exact List.mem_append.mpr (Or.inl h)"], "list", "list", "mem_append")
    add("list_length_nil", "(α : Type) : ([] : List α).length = 0", ["rfl", "simp"], "list", "list", "length_nil")
    add("list_map_nil", "(α β : Type) (f : α → β) : [].map f = []", ["rfl", "simp"], "list", "list", "map_nil")

    # ===== E. LOGIC (aesop / tauto / manual) ===== #
    add("logic_and_symm", "(p q : Prop) (h : p ∧ q) : q ∧ p", ["exact ⟨h.2, h.1⟩", "exact h.symm", "tauto", "aesop"], "logic", "logic", "and_symm")
    add("logic_or_symm", "(p q : Prop) (h : p ∨ q) : q ∨ p", ["exact h.symm", "exact Or.symm h", "tauto", "aesop"], "logic", "logic", "or_symm")
    add("logic_contrapose", "(p q : Prop) (h : p → q) : ¬q → ¬p", ["intro hq hp; exact hq (h hp)", "exact fun hq hp => hq (h hp)", "tauto"], "logic", "logic", "contrapose")
    add("logic_not_not_intro", "(p : Prop) (h : p) : ¬¬p", ["intro hn; exact hn h", "exact fun hn => hn h", "tauto", "exact not_not_intro h"], "logic", "logic", "not_not")
    add("logic_false_elim", "(p : Prop) (h : False) : p", ["exact h.elim", "exact absurd h (by simp)", "cases h", "tauto"], "logic", "logic", "false_elim")
    add("logic_and_self_iff", "(p : Prop) : p ∧ p ↔ p", ["tauto", "exact and_self_iff", "simp"], "logic", "logic", "and_self")
    add("logic_or_self_iff", "(p : Prop) : p ∨ p ↔ p", ["tauto", "exact or_self_iff", "simp"], "logic", "logic", "or_self")
    add("logic_imp_trans", "(p q r : Prop) (h1 : p → q) (h2 : q → r) : p → r",
        ["intro hp; exact h2 (h1 hp)", "exact fun hp => h2 (h1 hp)", "tauto"], "logic", "logic", "imp_trans")
    add("logic_curry", "(p q r : Prop) (h : p ∧ q → r) (hp : p) (hq : q) : r", ["exact h ⟨hp, hq⟩", "apply h; exact ⟨hp, hq⟩", "tauto"], "logic", "logic", "curry")
    add("logic_em", "(p : Prop) : p ∨ ¬p", ["exact Classical.em p", "exact em p", "tauto", "by_cases h : p <;> simp [h]"], "logic", "logic", "em")
    add("logic_demorgan_notor", "(p q : Prop) (h : ¬(p ∨ q)) : ¬p", ["intro hp; exact h (Or.inl hp)", "exact fun hp => h (Or.inl hp)", "tauto"], "logic", "logic", "demorgan")
    add("logic_iff_refl", "(p : Prop) : p ↔ p", ["exact Iff.rfl", "rfl", "tauto"], "logic", "logic", "iff_refl")

    # ===== F. OPTION / BOOL / FUNCTION ===== #
    add("opt_map_id", "(α : Type) (o : Option α) : o.map id = o", ["simp", "cases o <;> simp", "cases o <;> rfl"], "bool_option", "bool/option", "option_map_id")
    add("opt_getD_some", "(α : Type) (a d : α) : (some a).getD d = a", ["rfl", "simp"], "bool_option", "bool/option", "option_getD")
    add("opt_some_isSome", "(α : Type) (a : α) : (some a).isSome = true", ["rfl", "simp"], "bool_option", "bool/option", "option_isSome")
    add("bool_and_true", "(b : Bool) : (b && true) = b", ["simp", "exact Bool.and_true b", "cases b <;> rfl"], "bool_option", "bool/option", "and_true")
    add("bool_true_and", "(b : Bool) : (true && b) = b", ["rfl", "simp"], "bool_option", "bool/option", "true_and")
    add("bool_and_self", "(b : Bool) : (b && b) = b", ["cases b <;> rfl", "simp", "exact Bool.and_self b"], "bool_option", "bool/option", "and_self")
    add("bool_or_false", "(b : Bool) : (b || false) = b", ["simp", "exact Bool.or_false b", "cases b <;> rfl"], "bool_option", "bool/option", "or_false")
    add("bool_or_self", "(b : Bool) : (b || b) = b", ["cases b <;> rfl", "simp", "exact Bool.or_self b"], "bool_option", "bool/option", "or_self")
    add("bool_not_not", "(b : Bool) : (!!b) = b", ["simp", "exact Bool.not_not b", "cases b <;> rfl"], "bool_option", "bool/option", "not_not")
    add("bool_dichotomy", "(b : Bool) : b = true ∨ b = false", ["cases b <;> simp", "cases b <;> tauto", "by_cases h : b <;> simp [h]"], "bool_option", "bool/option", "dichotomy")
    add("fun_id_apply", "(α : Type) (x : α) : id x = x", ["rfl", "simp"], "function", "function", "id_apply")
    add("fun_comp_id_left", "(α β : Type) (f : α → β) : id ∘ f = f", ["rfl", "funext x; rfl", "simp", "exact Function.id_comp f"], "function", "function", "comp_id")
    add("fun_comp_id_right", "(α β : Type) (f : α → β) : f ∘ id = f", ["rfl", "funext x; rfl", "simp", "exact Function.comp_id f"], "function", "function", "comp_id")
    add("fun_comp_assoc", "(α β γ δ : Type) (f : α → β) (g : β → γ) (h : γ → δ) : (h ∘ g) ∘ f = h ∘ (g ∘ f)",
        ["rfl", "funext x; rfl", "simp"], "function", "function", "comp_assoc")
    add("fun_const_apply", "(α β : Type) (b : β) (a : α) : (Function.const α b) a = b", ["rfl", "simp"], "function", "function", "const_apply")

    return plan


# --------------------------------------------------------------------------- #
# leakage guard sets
# --------------------------------------------------------------------------- #
def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _v18_sets() -> Tuple[Set[str], Set]:
    names: Set[str] = set()
    triples: Set = set()
    v18 = ROOT / "data" / "processed" / "v18_broad_core"
    for fn in ("train.jsonl", "val.jsonl", "test.jsonl"):
        for r in _read(v18 / fn):
            if r.get("theorem_name"):
                names.add(r["theorem_name"])
            triples.add((r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", "")))
    return names, triples


def _heldout_guard() -> Tuple[Set, Set]:
    """(triples, stmt_state_pairs) of v25 held-out test + v26 theorem-holdout test."""
    triples: Set = set()
    pairs: Set = set()
    # v25 held-out test seeds (statements/states) + verified rows (full triples)
    v25_test = {s["theorem_name"] for s in _read(ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl")}
    for s in _read(ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"):
        pairs.add((s["theorem_statement"], s["state_before"]))
    for r in _read(ROOT / "data" / "traces" / "v25_mathlib_tierc_verified.jsonl"):
        if r.get("theorem_name") in v25_test:
            triples.add((r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", "")))
            pairs.add((r.get("theorem_statement", ""), r.get("state_before", "")))
    # v26 theorem-holdout test
    th = ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout"
    for r in _read(th / "test_rows.jsonl"):
        triples.add((r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", "")))
        pairs.add((r.get("theorem_statement", ""), r.get("state_before", "")))
    for s in _read(th / "test_seeds.jsonl"):
        pairs.add((s["theorem_statement"], s["state_before"]))
    return triples, pairs


def proof_head(tactic: str) -> str:
    t = (tactic or "").strip()
    return t.split()[0].split(";")[0] if t else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--out-seeds", default=str(ROOT / "data" / "seeds" / "v27_mathlib_expanded_seeds.jsonl"))
    ap.add_argument("--out-candidates", default=str(ROOT / "data" / "manual" / "v27_mathlib_expanded_candidates.jsonl"))
    ap.add_argument("--out-verified", default=str(ROOT / "data" / "traces" / "v27_mathlib_expanded_verified.jsonl"))
    ap.add_argument("--out-failed", default=str(ROOT / "data" / "traces" / "v27_mathlib_expanded_failed.jsonl"))
    ap.add_argument("--out-train-rows", default=str(ROOT / "data" / "processed" / "v27_mathlib_specialist" / "expanded_train_rows.jsonl"))
    ap.add_argument("--summary", default=str(ROOT / "data" / "processed" / "v27_mathlib_specialist" / "expanded_summary.json"))
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--batch-size", type=int, default=80)
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    plan = build_plan()
    logger.info("v27 expanded plan: %d theorems", len(plan))

    verifier = TrustedMathlibVerifier(scratch, lean_path=lean_path,
                                      timeout=args.timeout, batch_size=args.batch_size)
    logger.info("warming up import Mathlib ...")
    if not verifier.warmup():
        logger.error("Mathlib warmup FAILED — aborting")
        return 2
    logger.info("warmup ok")

    work: List[Tuple[str, str, str]] = []
    work_meta: List[Dict[str, Any]] = []
    for entry in plan:
        nm, stmt = entry["theorem_name"], entry["theorem_statement"]
        seen_c: Set[str] = set()
        for cand in entry["candidates"]:
            c = cand.strip()
            if c in seen_c:
                continue
            seen_c.add(c)
            work.append((nm, stmt, c))
            work_meta.append(entry)
    logger.info("verifying %d candidate rows (trusted verifier) ...", len(work))
    verdicts = verifier.verify_many(work, confirm=True)
    logger.info("verification done: %d invocations, %.1fs total lean",
                verifier.n_invocations, verifier.total_lean_seconds)

    v18_names, v18_triples = _v18_sets()
    ho_triples, ho_pairs = _heldout_guard()

    for p in (args.out_seeds, args.out_candidates, args.out_verified,
              args.out_failed, args.out_train_rows):
        Path(p).parent.mkdir(parents=True, exist_ok=True)

    seeds = []
    for entry in plan:
        nm, stmt = entry["theorem_name"], entry["theorem_statement"]
        seeds.append({"theorem_name": nm, "theorem_statement": stmt,
                      "state_before": state_before(stmt),
                      "template": f"example {stmt} := by\n  __TACTIC__",
                      "placeholder": "__TACTIC__", "imports": [MATHLIB_IMPORT],
                      "category": entry["category"], "expected_skill": entry["expected_skill"],
                      "theorem_family": entry["theorem_family"], "transfer": "mathlib",
                      "source": "v27_mathlib_expanded", "mathlib": True})

    verified, failed, train_rows = [], [], []
    per_cat: Dict[str, Dict[str, int]] = defaultdict(lambda: {"theorems": 0, "proposed": 0, "verified": 0, "failed": 0})
    for e in plan:
        per_cat[e["category"]]["theorems"] += 1
    lean_ok: Dict[str, bool] = {e["theorem_name"]: False for e in plan}
    has_row: Dict[str, bool] = {e["theorem_name"]: False for e in plan}
    n_timeout = n_rejected = dn = dt = dpair = 0

    for vd, entry in zip(verdicts, work_meta):
        nm, stmt, cand = vd.theorem_name, vd.statement, vd.tactic
        cat = entry["category"]
        st = state_before(stmt)
        per_cat[cat]["proposed"] += 1
        rec = {"theorem_name": nm, "theorem_statement": stmt, "state_before": st,
               "tactic": cand, "category": cat, "expected_skill": entry["expected_skill"],
               "theorem_family": entry["theorem_family"], "transfer": "mathlib",
               "imports": [MATHLIB_IMPORT], "corpus_source": "v27_mathlib_expanded",
               "verifier": "TrustedMathlibVerifier (sentinel+confirm+rescue, import Mathlib)",
               "proof_head": proof_head(cand),
               "uses_simp": "simp" in cand, "uses_aesop": "aesop" in cand,
               "uses_omega": "omega" in cand, "uses_set": cat == "set",
               "uses_order": entry["expected_skill"] == "order",
               "uses_mathlib_lemma": ("." in cand and "exact" in cand),
               "mathlib": True, "source": "v27_mathlib_expanded"}
        if not vd.success:
            per_cat[cat]["failed"] += 1
            n_rejected += 1
            if vd.error and "timeout" in vd.error:
                n_timeout += 1
            failed.append({**rec, "verified": False, "error_head": (vd.error or "")[:120]})
            continue
        lean_ok[nm] = True
        if nm in v18_names:
            dn += 1
            continue
        triple = (stmt, st, cand)
        if triple in v18_triples:
            dt += 1
            continue
        if triple in ho_triples or (stmt, st) in ho_pairs:
            dpair += 1
            continue
        per_cat[cat]["verified"] += 1
        has_row[nm] = True
        verified.append({**rec, "verified": True})
        train_rows.append({"theorem_name": nm, "theorem_statement": stmt, "state_before": st,
                           "tactic": cand, "category": cat, "family": cat,
                           "expected_skill": entry["expected_skill"],
                           "required_operation": entry["expected_skill"],
                           "theorem_family": entry["theorem_family"],
                           "corpus_source": "v27_mathlib_expanded", "tactic_source": "verified",
                           "split": "train", "transfer": "mathlib",
                           "proof_head": proof_head(cand), "mathlib": True})

    zero_lean = sorted(nm for nm, ok in lean_ok.items() if not ok)
    stripped = sorted(nm for nm in lean_ok if lean_ok[nm] and not has_row[nm])
    thms_with_rows = sorted(nm for nm, ok in has_row.items() if ok)

    def _dump(path, rows):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    _dump(args.out_seeds, seeds)
    _dump(args.out_candidates, verified)
    _dump(args.out_verified, verified)
    _dump(args.out_failed, failed)
    _dump(args.out_train_rows, train_rows)

    summary = {
        "config": "v27_mathlib_expanded", "mathlib_available": True,
        "lean_verifier": "TrustedMathlibVerifier (sentinel+confirm+rescue, import Mathlib)",
        "imports_used": [MATHLIB_IMPORT],
        "n_theorems": len(plan), "n_candidates_proposed": len(work),
        "n_candidates_verified": len(verified), "n_candidates_lean_rejected": n_rejected,
        "n_candidates_failed": len(failed), "n_timeout": n_timeout,
        "n_theorems_with_training_rows": len(thms_with_rows),
        "n_zero_lean_success_theorems": len(zero_lean), "zero_lean_success_theorems": zero_lean,
        "n_theorems_stripped_to_zero_by_guards": len(stripped),
        "theorems_stripped_to_zero_by_guards": stripped,
        "dropped_v18_name": dn, "dropped_v18_triple": dt, "dropped_heldout": dpair,
        "by_category": {k: dict(v) for k, v in per_cat.items()},
        "categories": sorted(per_cat),
        "verified_proof_heads": dict(Counter(r["proof_head"] for r in verified).most_common()),
        "n_lean_invocations": verifier.n_invocations,
        "total_lean_seconds": round(verifier.total_lean_seconds, 1),
        "uses_state_after": False, "uses_manual_oracle": False, "uses_mathlib": True,
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("v27 expanded corpus: theorems=%d verified_rows=%d lean_rejected=%d "
                "thms_with_rows=%d drops v18name/v18triple/heldout=%d/%d/%d",
                len(plan), len(verified), n_rejected, len(thms_with_rows), dn, dt, dpair)
    for cat, d in sorted(per_cat.items()):
        logger.info("  %-12s train_rows=%d/%d theorems=%d failed=%d", cat, d["verified"], d["proposed"], d["theorems"], d["failed"])
    if zero_lean:
        logger.warning("TRUE coverage gaps (Lean rejected ALL candidates): %s", zero_lean)
    if stripped:
        logger.info("verified-but-benchmark (stripped by guards, NOT gaps): %d %s", len(stripped), stripped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
