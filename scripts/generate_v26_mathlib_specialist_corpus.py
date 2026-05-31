"""Mini-ELF v26 — Parts 2/3: expanded Mathlib specialist corpus + verification.

Builds ~55–65 tiny Mathlib-tier theorems across 6 categories (Nat arithmetic,
Set, List, Function/identity, Logic, Bool/Option), each with 3–6 candidate
tactics, and verifies **every** candidate by whole-file ``import Mathlib``
typecheck. Verification uses the **batched** direct-binary verifier
(:class:`mini_elf_lean.mathlib_verifier.BatchMathlibVerifier`) so hundreds of
candidates are checked in a handful of Lean invocations — the v25 path paid the
~4.7 s import cost per candidate.

Only Lean-accepted candidates become training positives. Failed candidates are
kept for the failure taxonomy but never used as positives. The manual reference
candidates are corpus *targets verified by Lean* — never fed to a model as
predictions.

Leakage guards:
  * drop anything matching a v18 broad-core theorem name or
    (statement, state_before, tactic) triple;
  * drop anything matching a v25 **held-out test** triple (so v26 training never
    contains a v25 eval row);
  * theorem names are all ``v26_*`` and distinct from v25 names.

Outputs:
  data/seeds/v26_mathlib_specialist_seeds.jsonl
  data/manual/v26_mathlib_specialist_candidates.jsonl     (verified targets)
  data/traces/v26_mathlib_specialist_verified.jsonl
  data/traces/v26_mathlib_specialist_failed.jsonl
  data/processed/v26_mathlib_specialist/{train_rows.jsonl,summary.json}

Honesty: real Mathlib typecheck (no mock), no state_after, no manual oracle as
predictions, Mathlib real & external. v18 + v25 leakage guards enforced.
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

from mini_elf_lean.mathlib_verifier import BatchMathlibVerifier, MATHLIB_IMPORT  # noqa: E402
from generate_v25_mathlib_tierc_corpus import state_before  # noqa: E402  (binder->state)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_v26_mathlib_specialist_corpus")

DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"


# --------------------------------------------------------------------------- #
# Corpus plan
# --------------------------------------------------------------------------- #
def build_plan() -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []

    def add(name, stmt, cands, cat, skill, op, transfer):
        plan.append({"theorem_name": f"v26_{name}", "theorem_statement": stmt,
                     "candidates": cands, "category": cat, "expected_skill": skill,
                     "required_operation": op, "transfer": transfer})

    # ---- A. Nat arithmetic / simp / rw --------------------------------- #
    add("nat_add_zero_r", "(n : Nat) : n + 0 = n",
        ["rfl", "simp", "exact Nat.add_zero n", "omega"], "nat", "arithmetic", "rewrite", "core")
    add("nat_zero_add_l", "(n : Nat) : 0 + n = n",
        ["simp", "omega", "exact Nat.zero_add n"], "nat", "arithmetic", "rewrite", "mathlib")
    add("nat_mul_one_r", "(n : Nat) : n * 1 = n",
        ["simp", "exact Nat.mul_one n", "ring", "omega"], "nat", "arithmetic", "rewrite", "mathlib")
    add("nat_one_mul_l", "(n : Nat) : 1 * n = n",
        ["simp", "exact Nat.one_mul n", "ring", "omega"], "nat", "arithmetic", "rewrite", "mathlib")
    add("nat_mul_zero_r", "(n : Nat) : n * 0 = 0",
        ["rfl", "simp", "exact Nat.mul_zero n"], "nat", "arithmetic", "rewrite", "core")
    add("nat_zero_mul_l", "(n : Nat) : 0 * n = 0",
        ["simp", "exact Nat.zero_mul n", "omega"], "nat", "arithmetic", "rewrite", "mathlib")
    add("nat_add_comm2", "(a b : Nat) : a + b = b + a",
        ["omega", "exact Nat.add_comm a b", "ring", "simp [Nat.add_comm]"], "nat", "arithmetic", "rewrite", "mathlib")
    add("nat_add_assoc2", "(a b c : Nat) : a + b + c = a + (b + c)",
        ["omega", "exact Nat.add_assoc a b c", "ring"], "nat", "arithmetic", "rewrite", "mathlib")
    add("nat_mul_comm2", "(a b : Nat) : a * b = b * a",
        ["exact Nat.mul_comm a b", "ring", "ac_rfl"], "nat", "arithmetic", "rewrite", "mathlib")
    add("nat_succ_eq2", "(n : Nat) : Nat.succ n = n + 1",
        ["rfl", "simp", "omega"], "nat", "arithmetic", "rewrite", "core")
    add("nat_le_refl2", "(n : Nat) : n ≤ n",
        ["exact Nat.le_refl n", "omega", "exact le_refl n", "exact le_rfl", "simp"], "nat", "order", "order", "mathlib")
    add("nat_le_succ2", "(n : Nat) : n ≤ n + 1",
        ["omega", "exact Nat.le_succ n", "simp", "exact Nat.le.intro rfl"], "nat", "order", "order", "mathlib")
    add("nat_zero_le", "(n : Nat) : 0 ≤ n",
        ["omega", "exact Nat.zero_le n", "simp"], "nat", "order", "order", "mathlib")
    add("nat_le_add_right2", "(a b : Nat) : a ≤ a + b",
        ["omega", "exact Nat.le_add_right a b", "simp"], "nat", "order", "order", "mathlib")
    add("nat_add_one_cong", "(a b : Nat) (h : a = b) : a + 1 = b + 1",
        ["omega", "rw [h]", "exact congrArg (· + 1) h", "simp [h]"], "nat", "core-shaped", "rewrite", "core")

    # ---- B. Set basics -------------------------------------------------- #
    add("set_subset_refl2", "(α : Type) (s : Set α) : s ⊆ s",
        ["exact subset_refl s", "exact le_refl s", "intro x h; exact h",
         "exact fun x h => h", "exact Set.Subset.refl s"], "set", "set", "intro", "mathlib")
    add("set_mem_imp_self", "(α : Type) (s : Set α) (x : α) (h : x ∈ s) : x ∈ s",
        ["exact h", "assumption", "simp [h]"], "set", "set", "intro", "core")
    add("set_inter_subset_left2", "(α : Type) (s t : Set α) : s ∩ t ⊆ s",
        ["exact Set.inter_subset_left", "intro x h; exact h.1", "exact fun x h => h.1"], "set", "set", "intro", "mathlib")
    add("set_inter_subset_right2", "(α : Type) (s t : Set α) : s ∩ t ⊆ t",
        ["exact Set.inter_subset_right", "intro x h; exact h.2", "exact fun x h => h.2"], "set", "set", "intro", "mathlib")
    add("set_subset_union_left2", "(α : Type) (s t : Set α) : s ⊆ s ∪ t",
        ["exact Set.subset_union_left", "intro x h; exact Or.inl h", "exact fun x h => Or.inl h"], "set", "set", "intro", "mathlib")
    add("set_subset_union_right2", "(α : Type) (s t : Set α) : t ⊆ s ∪ t",
        ["exact Set.subset_union_right", "intro x h; exact Or.inr h", "exact fun x h => Or.inr h"], "set", "set", "intro", "mathlib")
    add("set_mem_inter_left", "(α : Type) (s t : Set α) (x : α) (h : x ∈ s ∩ t) : x ∈ s",
        ["exact h.1", "exact h.left", "exact (Set.mem_inter_iff x s t).mp h |>.1"], "set", "set", "destruct", "mathlib")
    add("set_mem_singleton2", "(α : Type) (a : α) : a ∈ ({a} : Set α)",
        ["rfl", "simp", "exact Set.mem_singleton a", "exact rfl", "exact Set.mem_singleton_iff.mpr rfl"], "set", "set", "destruct", "mathlib")
    add("set_mem_univ2", "(α : Type) (a : α) : a ∈ (Set.univ : Set α)",
        ["trivial", "simp", "exact Set.mem_univ a"], "set", "set", "destruct", "mathlib")
    add("set_empty_subset2", "(α : Type) (s : Set α) : (∅ : Set α) ⊆ s",
        ["exact Set.empty_subset s", "intro x h; exact absurd h (by simp)", "simp"], "set", "set", "intro", "mathlib")
    add("set_subset_univ2", "(α : Type) (s : Set α) : s ⊆ (Set.univ : Set α)",
        ["exact Set.subset_univ s", "intro x _; trivial", "simp"], "set", "set", "intro", "mathlib")

    # ---- C. List -------------------------------------------------------- #
    add("list_append_nil2", "(α : Type) (xs : List α) : xs ++ [] = xs",
        ["simp", "exact List.append_nil xs"], "list", "list", "rewrite", "mathlib")
    add("list_nil_append2", "(α : Type) (xs : List α) : [] ++ xs = xs",
        ["rfl", "simp", "exact List.nil_append xs"], "list", "core-shaped", "rewrite", "core")
    add("list_length_cons2", "(α : Type) (x : α) (xs : List α) : (x :: xs).length = xs.length + 1",
        ["rfl", "simp", "exact List.length_cons x xs"], "list", "list", "rewrite", "mathlib")
    add("list_length_append2",
        "(α : Type) (xs ys : List α) : (xs ++ ys).length = xs.length + ys.length",
        ["simp", "rw [List.length_append]", "exact List.length_append xs ys"], "list", "list", "rewrite", "mathlib")
    add("list_reverse_nil2", "(α : Type) : ([] : List α).reverse = []",
        ["rfl", "simp"], "list", "core-shaped", "rewrite", "core")
    add("list_length_reverse2", "(α : Type) (xs : List α) : xs.reverse.length = xs.length",
        ["simp", "exact List.length_reverse xs"], "list", "list", "rewrite", "mathlib")
    add("list_map_id2", "(α : Type) (xs : List α) : xs.map id = xs",
        ["simp", "exact List.map_id xs"], "list", "list", "rewrite", "mathlib")
    add("list_mem_cons_self2", "(α : Type) (x : α) (xs : List α) : x ∈ x :: xs",
        ["simp", "exact List.mem_cons_self x xs", "exact List.mem_cons_self ..", "left; rfl"], "list", "list", "destruct", "mathlib")
    add("list_map_nil", "(α β : Type) (f : α → β) : [].map f = []",
        ["rfl", "simp"], "list", "core-shaped", "rewrite", "core")

    # ---- D. Function / identity ---------------------------------------- #
    add("fun_id_apply", "(α : Type) (x : α) : id x = x",
        ["rfl", "simp"], "function", "core-shaped", "rewrite", "core")
    add("fun_comp_id_left", "(α β : Type) (f : α → β) : id ∘ f = f",
        ["rfl", "funext x; rfl", "simp", "exact Function.id_comp f"], "function", "function", "rewrite", "mathlib")
    add("fun_comp_id_right", "(α β : Type) (f : α → β) : f ∘ id = f",
        ["rfl", "funext x; rfl", "simp", "exact Function.comp_id f"], "function", "function", "rewrite", "mathlib")
    add("fun_const_apply", "(α β : Type) (b : β) (a : α) : (Function.const α b) a = b",
        ["rfl", "simp"], "function", "function", "rewrite", "core")

    # ---- E. Logic (simp / tauto / aesop / manual) ---------------------- #
    add("logic_and_symm2", "(p q : Prop) (h : p ∧ q) : q ∧ p",
        ["exact ⟨h.2, h.1⟩", "exact And.symm h", "exact h.symm", "tauto"], "logic", "core-shaped", "project_conjunction", "core")
    add("logic_or_symm2", "(p q : Prop) (h : p ∨ q) : q ∨ p",
        ["exact h.symm", "exact Or.symm h", "tauto"], "logic", "core-shaped", "disjunction_cases", "core")
    add("logic_not_not2", "(p : Prop) (h : ¬¬p) : p",
        ["exact Classical.not_not.mp h", "tauto", "exact not_not.mp h", "by_contra hp; exact h hp"], "logic", "mathlib-lemma", "intro", "mathlib")
    add("logic_em2", "(p : Prop) : p ∨ ¬p",
        ["exact Classical.em p", "exact em p", "tauto", "by_cases h : p <;> simp [h]"], "logic", "mathlib-lemma", "disjunction_cases", "mathlib")
    add("logic_imp_self2", "(p : Prop) : p → p",
        ["exact id", "intro h; exact h", "exact fun h => h", "tauto"], "logic", "core-shaped", "intro", "core")
    add("logic_and_intro2", "(p q : Prop) (hp : p) (hq : q) : p ∧ q",
        ["exact ⟨hp, hq⟩", "exact And.intro hp hq", "constructor <;> assumption", "tauto"], "logic", "core-shaped", "project_conjunction", "core")
    add("logic_mp2", "(p q : Prop) (hpq : p → q) (hp : p) : q",
        ["exact hpq hp", "apply hpq; exact hp", "tauto"], "logic", "core-shaped", "intro", "core")
    add("logic_iff_refl2", "(p : Prop) : p ↔ p",
        ["exact Iff.rfl", "rfl", "tauto", "constructor <;> intro h <;> exact h"], "logic", "core-shaped", "intro", "core")
    add("logic_const_imp", "(p q : Prop) (hp : p) : q → p",
        ["intro _; exact hp", "exact fun _ => hp", "tauto"], "logic", "core-shaped", "intro", "core")
    add("logic_and_self_iff", "(p : Prop) : p ∧ p ↔ p",
        ["tauto", "exact and_self_iff", "constructor <;> intro h <;> simp_all"], "logic", "mathlib-lemma", "intro", "mathlib")
    add("logic_or_self_iff", "(p : Prop) : p ∨ p ↔ p",
        ["tauto", "exact or_self_iff", "simp"], "logic", "mathlib-lemma", "intro", "mathlib")
    add("logic_imp_trans", "(p q r : Prop) (h1 : p → q) (h2 : q → r) : p → r",
        ["intro hp; exact h2 (h1 hp)", "exact fun hp => h2 (h1 hp)", "tauto"], "logic", "core-shaped", "intro", "core")

    # ---- F. Option / Bool ---------------------------------------------- #
    add("bool_true_and2", "(b : Bool) : (true && b) = b",
        ["rfl", "simp"], "bool_option", "core-shaped", "rewrite", "core")
    add("bool_and_true2", "(b : Bool) : (b && true) = b",
        ["simp", "exact Bool.and_true b", "cases b <;> rfl"], "bool_option", "bool/option", "rewrite", "mathlib")
    add("bool_and_self2", "(b : Bool) : (b && b) = b",
        ["cases b <;> rfl", "simp", "exact Bool.and_self b"], "bool_option", "bool/option", "rewrite", "mathlib")
    add("bool_or_false2", "(b : Bool) : (b || false) = b",
        ["simp", "exact Bool.or_false b", "cases b <;> rfl"], "bool_option", "bool/option", "rewrite", "mathlib")
    add("bool_not_not2", "(b : Bool) : (!!b) = b",
        ["simp", "exact Bool.not_not b", "cases b <;> rfl"], "bool_option", "bool/option", "rewrite", "mathlib")
    add("bool_dichotomy2", "(b : Bool) : b = true ∨ b = false",
        ["cases b <;> simp", "exact Bool.eq_false_or_eq_true b", "cases b <;> tauto", "by_cases h : b <;> simp [h]"], "bool_option", "bool/option", "disjunction_cases", "mathlib")
    add("option_map_id2", "(α : Type) (o : Option α) : o.map id = o",
        ["simp", "cases o <;> simp", "cases o <;> rfl", "exact Option.map_id_fun' ▸ rfl"], "bool_option", "bool/option", "rewrite", "mathlib")
    add("option_some_isSome2", "(α : Type) (a : α) : (some a).isSome = true",
        ["rfl", "simp"], "bool_option", "core-shaped", "rewrite", "core")
    add("option_getD_some", "(α : Type) (a d : α) : (some a).getD d = a",
        ["rfl", "simp"], "bool_option", "core-shaped", "rewrite", "core")

    # ---- Extra DISTINCT theorems (no v18 / v25 overlap) to grow the corpus
    #      and strengthen list / order / set coverage. -------------------- #
    # Set (the key gap category):
    add("set_inter_subset_inter_self", "(α : Type) (s : Set α) : s ∩ s ⊆ s",
        ["intro x h; exact h.1", "exact Set.inter_subset_left", "intro x h; exact h.2"], "set", "set", "intro", "mathlib")
    add("set_subset_inter_self", "(α : Type) (s : Set α) : s ⊆ s ∩ s",
        ["intro x h; exact ⟨h, h⟩", "exact fun x h => ⟨h, h⟩", "simp"], "set", "set", "intro", "mathlib")
    add("set_mem_union_left2", "(α : Type) (s t : Set α) (x : α) (h : x ∈ s) : x ∈ s ∪ t",
        ["exact Or.inl h", "left; exact h", "exact Set.mem_union_left t h"], "set", "set", "destruct", "mathlib")
    add("set_mem_union_right2", "(α : Type) (s t : Set α) (x : α) (h : x ∈ t) : x ∈ s ∪ t",
        ["exact Or.inr h", "right; exact h", "exact Set.mem_union_right s h"], "set", "set", "destruct", "mathlib")
    add("set_inter_comm_subset", "(α : Type) (s t : Set α) : s ∩ t ⊆ t ∩ s",
        ["intro x h; exact ⟨h.2, h.1⟩", "exact fun x h => ⟨h.2, h.1⟩"], "set", "set", "intro", "mathlib")
    add("set_subset_trans2", "(α : Type) (s t u : Set α) (h1 : s ⊆ t) (h2 : t ⊆ u) : s ⊆ u",
        ["intro x hx; exact h2 (h1 hx)", "exact h1.trans h2", "exact fun x hx => h2 (h1 hx)"], "set", "set", "intro", "mathlib")
    add("set_diff_subset2", "(α : Type) (s t : Set α) : s \\ t ⊆ s",
        ["intro x h; exact h.1", "exact Set.diff_subset", "exact fun x h => h.1"], "set", "set", "intro", "mathlib")
    add("set_empty_inter_subset", "(α : Type) (s : Set α) : (∅ : Set α) ∩ s ⊆ ∅",
        ["intro x h; exact h.1", "exact Set.inter_subset_left", "simp"], "set", "set", "intro", "mathlib")
    # Order:
    add("nat_le_trans2", "(a b c : Nat) (h1 : a ≤ b) (h2 : b ≤ c) : a ≤ c",
        ["exact Nat.le_trans h1 h2", "omega", "exact le_trans h1 h2"], "nat", "order", "order", "mathlib")
    add("nat_le_add_left2", "(a b : Nat) : b ≤ a + b",
        ["omega", "exact Nat.le_add_left b a", "simp"], "nat", "order", "order", "mathlib")
    add("nat_lt_succ_self2", "(n : Nat) : n < n + 1",
        ["omega", "exact Nat.lt_succ_self n", "simp"], "nat", "order", "order", "mathlib")
    add("nat_le_of_eq2", "(a b : Nat) (h : a = b) : a ≤ b",
        ["omega", "exact h.le", "rw [h]", "exact Nat.le_of_eq h"], "nat", "order", "order", "mathlib")
    add("nat_min_le_left2", "(a b : Nat) : min a b ≤ a",
        ["exact Nat.min_le_left a b", "omega", "simp"], "nat", "order", "order", "mathlib")
    add("nat_le_max_left2", "(a b : Nat) : a ≤ max a b",
        ["exact Nat.le_max_left a b", "omega", "simp"], "nat", "order", "order", "mathlib")
    # List (weak category — boost):
    add("list_cons_ne_nil2", "(α : Type) (x : α) (xs : List α) : x :: xs ≠ []",
        ["simp", "exact List.cons_ne_nil x xs", "intro h; cases h"], "list", "list", "rewrite", "mathlib")
    add("list_append_assoc2", "(α : Type) (xs ys zs : List α) : (xs ++ ys) ++ zs = xs ++ (ys ++ zs)",
        ["simp", "rw [List.append_assoc]", "exact List.append_assoc xs ys zs"], "list", "list", "rewrite", "mathlib")
    add("list_length_nil2", "(α : Type) : ([] : List α).length = 0",
        ["rfl", "simp"], "list", "core-shaped", "rewrite", "core")
    add("list_reverse_reverse2", "(α : Type) (xs : List α) : xs.reverse.reverse = xs",
        ["simp", "exact List.reverse_reverse xs"], "list", "list", "rewrite", "mathlib")
    add("list_mem_append_left2", "(α : Type) (x : α) (xs ys : List α) (h : x ∈ xs) : x ∈ xs ++ ys",
        ["exact List.mem_append_left ys h", "simp [h]", "exact List.mem_append.mpr (Or.inl h)"], "list", "list", "destruct", "mathlib")
    add("list_map_map2", "(α β γ : Type) (f : α → β) (g : β → γ) (xs : List α) : (xs.map f).map g = xs.map (g ∘ f)",
        ["simp", "rw [List.map_map]", "exact (List.map_map g f xs)"], "list", "list", "rewrite", "mathlib")
    add("list_head_cons2", "(α : Type) (x : α) (xs : List α) : (x :: xs).head? = some x",
        ["rfl", "simp"], "list", "core-shaped", "rewrite", "core")
    # Logic (distinct):
    add("logic_curry2", "(p q r : Prop) (h : p ∧ q → r) (hp : p) (hq : q) : r",
        ["exact h ⟨hp, hq⟩", "apply h; exact ⟨hp, hq⟩", "tauto"], "logic", "core-shaped", "intro", "core")
    add("logic_contrapose2", "(p q : Prop) (h : p → q) (hnq : ¬q) (hp : p) : False",
        ["exact hnq (h hp)", "tauto", "apply hnq; exact h hp"], "logic", "core-shaped", "intro", "core")
    add("logic_demorgan_notor", "(p q : Prop) (h : ¬(p ∨ q)) : ¬p",
        ["intro hp; exact h (Or.inl hp)", "exact fun hp => h (Or.inl hp)", "tauto"], "logic", "core-shaped", "intro_negation", "core")
    add("logic_or_intro_left2", "(p q : Prop) (hp : p) : p ∨ q",
        ["exact Or.inl hp", "left; exact hp", "tauto"], "logic", "core-shaped", "disjunction_cases", "core")
    add("logic_and_left2", "(p q : Prop) (h : p ∧ q) : p",
        ["exact h.1", "exact h.left", "tauto"], "logic", "core-shaped", "project_conjunction", "core")
    # Function / Bool (distinct):
    add("fun_comp_assoc2", "(α β γ δ : Type) (f : α → β) (g : β → γ) (h : γ → δ) : (h ∘ g) ∘ f = h ∘ (g ∘ f)",
        ["rfl", "funext x; rfl", "simp"], "function", "function", "rewrite", "core")
    add("bool_false_or2", "(b : Bool) : (false || b) = b",
        ["rfl", "simp"], "bool_option", "core-shaped", "rewrite", "core")
    add("bool_or_self2", "(b : Bool) : (b || b) = b",
        ["cases b <;> rfl", "simp", "exact Bool.or_self b"], "bool_option", "bool/option", "rewrite", "mathlib")
    add("bool_not_true2", ": (!true) = false",
        ["rfl", "decide", "simp"], "bool_option", "core-shaped", "rewrite", "core")
    # Nat (distinct):
    add("nat_two_mul2", "(n : Nat) : 2 * n = n + n",
        ["omega", "ring", "exact Nat.two_mul n"], "nat", "arithmetic", "rewrite", "mathlib")
    add("nat_succ_pos2", "(n : Nat) : 0 < n + 1",
        ["omega", "exact Nat.succ_pos n", "simp"], "nat", "order", "order", "mathlib")
    add("nat_add_sub_cancel2", "(n m : Nat) : n + m - m = n",
        ["omega", "simp", "exact Nat.add_sub_cancel"], "nat", "arithmetic", "rewrite", "mathlib")

    return plan


# --------------------------------------------------------------------------- #
# leakage guard sets
# --------------------------------------------------------------------------- #
def _read(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


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


def _v25_test_triples() -> Set:
    """(statement, state, tactic) triples of the v25 held-out TEST theorems."""
    tt_path = ROOT / "data" / "processed" / "v25_tierc_augmented" / "test_theorems.json"
    if not tt_path.exists():
        return set()
    test_set = set(json.loads(tt_path.read_text()).get("test_theorems", []))
    triples: Set = set()
    for r in _read(ROOT / "data" / "traces" / "v25_mathlib_tierc_verified.jsonl"):
        if r.get("theorem_name") in test_set:
            triples.add((r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", "")))
    return triples


def proof_head(tactic: str) -> str:
    t = tactic.strip()
    return t.split()[0].split(";")[0] if t else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path", default=None, help="precomputed Mathlib LEAN_PATH (else lake env)")
    ap.add_argument("--out-seeds", default=str(ROOT / "data" / "seeds" / "v26_mathlib_specialist_seeds.jsonl"))
    ap.add_argument("--out-candidates", default=str(ROOT / "data" / "manual" / "v26_mathlib_specialist_candidates.jsonl"))
    ap.add_argument("--out-verified", default=str(ROOT / "data" / "traces" / "v26_mathlib_specialist_verified.jsonl"))
    ap.add_argument("--out-failed", default=str(ROOT / "data" / "traces" / "v26_mathlib_specialist_failed.jsonl"))
    ap.add_argument("--out-train-rows", default=str(ROOT / "data" / "processed" / "v26_mathlib_specialist" / "train_rows.jsonl"))
    ap.add_argument("--summary", default=str(ROOT / "data" / "processed" / "v26_mathlib_specialist" / "summary.json"))
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--batch-size", type=int, default=80)
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    plan = build_plan()
    logger.info("v26 specialist plan: %d theorems", len(plan))

    verifier = BatchMathlibVerifier(scratch, lean_path=args.lean_path,
                                    timeout=args.timeout, batch_size=args.batch_size)
    logger.info("LEAN_PATH resolved; warming up import Mathlib ...")
    if not verifier.warmup():
        logger.error("Mathlib warmup FAILED — aborting")
        return 2
    logger.info("warmup ok")

    # Build the flat (theorem, candidate) work list (dedup candidates per theorem).
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
    logger.info("verifying %d candidate rows in batches of %d ...", len(work), args.batch_size)
    verdicts = verifier.verify_many(work)
    logger.info("verification done: %d invocations, %.1fs total lean (%.2fs/cand amortized)",
                verifier.n_invocations, verifier.total_lean_seconds,
                verifier.total_lean_seconds / max(len(work), 1))

    v18_names, v18_triples = _v18_sets()
    v25_test_triples = _v25_test_triples()

    for p in (args.out_seeds, args.out_candidates, args.out_verified,
              args.out_failed, args.out_train_rows):
        Path(p).parent.mkdir(parents=True, exist_ok=True)

    # seeds (one per theorem)
    seeds = []
    for entry in plan:
        nm, stmt = entry["theorem_name"], entry["theorem_statement"]
        seeds.append({"theorem_name": nm, "theorem_statement": stmt,
                      "state_before": state_before(stmt),
                      "template": f"example {stmt} := by\n  __TACTIC__",
                      "placeholder": "__TACTIC__", "imports": [MATHLIB_IMPORT],
                      "category": entry["category"], "expected_skill": entry["expected_skill"],
                      "transfer": entry["transfer"], "required_operation": entry["required_operation"],
                      "source": "v26_mathlib_specialist", "mathlib": True})

    verified, failed, train_rows = [], [], []
    per_cat: Dict[str, Dict[str, int]] = defaultdict(lambda: {"theorems": 0, "proposed": 0, "verified": 0, "failed": 0})
    for e in plan:
        per_cat[e["category"]]["theorems"] += 1
    lean_ok_per_thm: Dict[str, bool] = {e["theorem_name"]: False for e in plan}
    trainrow_per_thm: Dict[str, bool] = {e["theorem_name"]: False for e in plan}
    n_timeout = n_lean_rejected = dn = dt = d25 = 0

    for vd, entry in zip(verdicts, work_meta):
        nm, stmt, cand = vd.theorem_name, vd.statement, vd.tactic
        cat = entry["category"]
        st = state_before(stmt)
        per_cat[cat]["proposed"] += 1
        rec = {"theorem_name": nm, "theorem_statement": stmt, "state_before": st,
               "tactic": cand, "category": cat, "expected_skill": entry["expected_skill"],
               "transfer": entry["transfer"], "required_operation": entry["required_operation"],
               "imports": [MATHLIB_IMPORT], "corpus_source": "v26_mathlib_specialist",
               "verifier": "batch direct-binary lean (import Mathlib)",
               "proof_head": proof_head(cand),
               "uses_simp": "simp" in cand, "uses_mathlib_lemma": entry["transfer"] == "mathlib",
               "uses_set": cat == "set", "uses_order": entry["expected_skill"] == "order",
               "mathlib": True}
        if not vd.success:
            per_cat[cat]["failed"] += 1
            n_lean_rejected += 1
            if vd.error and "timeout" in vd.error:
                n_timeout += 1
            failed.append({**rec, "verified": False, "error_head": (vd.error or "")[:120]})
            continue
        # Lean accepted this candidate (before benchmark-hygiene leakage guards).
        lean_ok_per_thm[nm] = True
        # leakage guards: keep the verified row OUT of training, but it still
        # counts as Lean-success above (so it is not a real coverage gap).
        if nm in v18_names:
            dn += 1
            continue
        triple = (stmt, st, cand)
        if triple in v18_triples:
            dt += 1
            continue
        if triple in v25_test_triples:
            d25 += 1
            continue
        per_cat[cat]["verified"] += 1
        trainrow_per_thm[nm] = True
        verified.append({**rec, "verified": True})
        train_rows.append({"theorem_name": nm, "theorem_statement": stmt, "state_before": st,
                           "tactic": cand, "category": cat, "family": cat,
                           "expected_skill": entry["expected_skill"],
                           "required_operation": entry["required_operation"],
                           "corpus_source": "v26_mathlib_specialist", "tactic_source": "verified",
                           "split": "train", "transfer": entry["transfer"],
                           "proof_head": proof_head(cand), "mathlib": True})

    # A "zero Lean-success" theorem is a real coverage gap (Lean rejected every
    # candidate). A "stripped to zero by guards" theorem verified in Lean but
    # had all rows removed for benchmark hygiene (NOT a coverage gap).
    zero_lean_success = sorted(nm for nm, ok in lean_ok_per_thm.items() if not ok)
    stripped_by_guards = sorted(nm for nm in lean_ok_per_thm
                                if lean_ok_per_thm[nm] and not trainrow_per_thm[nm])
    thms_with_rows = sorted(nm for nm, ok in trainrow_per_thm.items() if ok)

    def _dump(path, rows):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    _dump(args.out_seeds, seeds)
    _dump(args.out_candidates, verified)
    _dump(args.out_verified, verified)
    _dump(args.out_failed, failed)
    _dump(args.out_train_rows, train_rows)

    head_counts = Counter(r["proof_head"] for r in verified)
    summary = {
        "config": "v26_mathlib_specialist", "mathlib_available": True,
        "lean_verifier": "BatchMathlibVerifier (direct binary + LEAN_PATH, import Mathlib)",
        "imports_used": [MATHLIB_IMPORT],
        "n_theorems": len(plan),
        "n_candidates_proposed": len(work),
        "n_candidates_verified": len(verified),
        "n_candidates_lean_rejected": n_lean_rejected,
        "n_candidates_failed": len(failed),
        "n_timeout": n_timeout,
        "n_theorems_with_training_rows": len(thms_with_rows),
        "n_zero_lean_success_theorems": len(zero_lean_success),
        "zero_lean_success_theorems": zero_lean_success,
        "n_theorems_stripped_to_zero_by_guards": len(stripped_by_guards),
        "theorems_stripped_to_zero_by_guards": stripped_by_guards,
        "dropped_v18_name": dn, "dropped_v18_triple": dt, "dropped_v25_test_triple": d25,
        "by_category": {k: dict(v) for k, v in per_cat.items()},
        "categories": sorted(per_cat),
        "verified_proof_heads": dict(head_counts.most_common()),
        "n_lean_invocations": verifier.n_invocations,
        "total_lean_seconds": round(verifier.total_lean_seconds, 1),
        "avg_verify_seconds_per_candidate": round(verifier.total_lean_seconds / max(len(work), 1), 3),
        "uses_state_after": False, "uses_manual_oracle": False, "uses_mathlib": True,
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("v26 specialist corpus: theorems=%d train_rows=%d lean_rejected=%d "
                "thms_with_rows=%d drops v18name/v18triple/v25test=%d/%d/%d",
                len(plan), len(verified), n_lean_rejected, len(thms_with_rows), dn, dt, d25)
    for cat, d in sorted(per_cat.items()):
        logger.info("  %-12s train_rows=%d/%d theorems=%d", cat, d["verified"], d["proposed"], d["theorems"])
    if zero_lean_success:
        logger.warning("TRUE coverage gaps (Lean rejected ALL candidates): %s", zero_lean_success)
    if stripped_by_guards:
        logger.info("verified-but-benchmark (stripped by leakage guards, NOT gaps): %d theorems %s",
                    len(stripped_by_guards), stripped_by_guards)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
