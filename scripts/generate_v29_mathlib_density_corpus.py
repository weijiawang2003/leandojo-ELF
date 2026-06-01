"""Mini-ELF v29 — Part 3: sibling-density Mathlib corpus.

v28 proved improvement comes from **within-family sibling density**, not generic
category transfer (Part-1 density law: held-out pass@10 rises 0.68 → 0.83 → 0.94 as
training siblings go 0 → 1-3 → 4-6). v29 therefore scales density **directly**: it
brings every weak / residual family (Part 2) to ~8 verified siblings by crossing a
**var-set menu** (s,t,u / a,b,c / p,q,r / u,v,w …) with a **proof-head menu** (named
lemma · intro;exact · simp · rintro · funext), so the small seq2seq sees the same
*shape* under many surface tokens and stops mis-binding the identifier/projection.

This is honest alpha-renamed augmentation: every sibling is a **distinct true
theorem independently Lean-verified** by the **TrustedMathlibVerifier**
(sentinel+confirm+rescue, sound & complete). Manual reference candidates are corpus
*targets verified by Lean*, never fed to a model as predictions.

Families (Part-2 driven):
  A. Finset projection + union/inter density   ([DecidableEq α])
  B. Set union_subset / inter_subset density
  C. order le_antisymm / le_trans density        (polymorphic [Preorder]/[PartialOrder]/…)
  D. function comp_assoc / comp_id (renamed vars, incl. φ ψ χ)
  E. nat / list lemma-name vocabulary density
  F. logic And/Or shape density

Leakage guards (drop a Lean-success that matches a benchmark — reported separately,
NOT a coverage gap): v18 broad-core name/triple; v25 held-out, v26 holdout, v27
holdout, **and v28 holdout** (statement,state) pairs & triples. All names are
``v29_*`` and distinct from prior versions.

Outputs:
  data/seeds/v29_mathlib_density_seeds.jsonl
  data/manual/v29_mathlib_density_candidates.jsonl        (verified targets)
  data/traces/v29_mathlib_density_verified.jsonl
  data/traces/v29_mathlib_density_failed.jsonl
  data/processed/v29_mathlib_specialist/density_train_rows.jsonl
  data/processed/v29_mathlib_specialist/density_summary.json

Honesty: real import-Mathlib typecheck (no mock), no state_after, no manual oracle
as predictions, Mathlib real & external, v18/v25/v26/v27/v28 leakage guards enforced.
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
from generate_v27_mathlib_expanded_corpus import _v18_sets, proof_head  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_v29_mathlib_density_corpus")
DEFAULT_SCRATCH = ROOT.parent / "mini_elf_mathlib_probe"

Entry = Dict[str, Any]

# ---- var / element / hypothesis menus (the surface-token axis of density) ---- #
SET3 = [("s", "t", "u"), ("a", "b", "c"), ("p", "q", "r"), ("u", "v", "w"), ("m", "n", "k")]
SET2 = [("s", "t"), ("a", "b"), ("p", "q"), ("u", "v"), ("c", "d")]
ELEM = [("x", "h"), ("y", "hy"), ("z", "hz"), ("w", "hw"), ("a", "ha")]
ORD3 = [("a", "b", "c"), ("x", "y", "z"), ("p", "q", "r")]
ORD2 = [("a", "b"), ("x", "y"), ("p", "q"), ("m", "n")]
FN3 = [("f", "g", "h"), ("p", "q", "r"), ("φ", "ψ", "χ")]
# Wider menus for the THIN v28-residual families so that — after the (f,g,h)/(p,q,r)
# and (a,b) var-sets collide with v28 benchmarks and are guard-dropped — enough NOVEL
# siblings remain in train to actually densify the family (fixing the v28 residual).
ASSOC3 = [("f", "g", "h"), ("p", "q", "r"), ("φ", "ψ", "χ"), ("k", "l", "m"),
          ("u", "v", "w"), ("F", "G", "H"), ("s", "t", "j"), ("a", "b", "c"), ("d", "e", "i")]
ANTI2 = [("a", "b"), ("x", "y"), ("p", "q"), ("m", "n"), ("c", "d"), ("u", "v")]
# dedicated, wider antisymm menu so >= ~5 novel siblings survive benchmark-drop + holdout
ANTISYMM2 = [("a", "b"), ("x", "y"), ("p", "q"), ("m", "n"), ("c", "d"), ("u", "v"),
             ("i", "j"), ("s", "t"), ("k", "l")]
TRANS3 = [("a", "b", "c"), ("x", "y", "z"), ("p", "q", "r"), ("m", "n", "k"), ("i", "j", "l")]


def _entry(name, stmt, cands, cat, skill, family, group) -> Entry:
    return {"theorem_name": f"v29_{name}", "theorem_statement": stmt,
            "candidates": cands, "category": cat, "expected_skill": skill,
            "theorem_family": family, "density_group": group}


# --------------------------------------------------------------------------- #
# A. FINSET projection + union/inter density ([DecidableEq α])
# --------------------------------------------------------------------------- #
def finset_families() -> List[Entry]:
    out: List[Entry] = []
    F = "(α : Type) [DecidableEq α]"
    for i in range(4):
        s, t = SET2[i]
        e, h = ELEM[i]
        # projection (both directions — the residual)
        out.append(_entry(f"fs_mem_inter_left_{i}",
                          f"{F} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {s}",
                          [f"exact (Finset.mem_inter.mp {h}).1", f"exact Finset.mem_of_mem_inter_left {h}",
                           f"exact (Finset.mem_inter.1 {h}).1"],
                          "finset", "finset", "mem_inter_proj", "dense_target"))
        out.append(_entry(f"fs_mem_inter_right_{i}",
                          f"{F} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {t}",
                          [f"exact (Finset.mem_inter.mp {h}).2", f"exact Finset.mem_of_mem_inter_right {h}",
                           f"exact (Finset.mem_inter.1 {h}).2"],
                          "finset", "finset", "mem_inter_proj", "dense_target"))
        out.append(_entry(f"fs_mem_union_left_{i}",
                          f"{F} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {s}) : {e} ∈ {s} ∪ {t}",
                          [f"exact Finset.mem_union.mpr (Or.inl {h})", f"exact Finset.mem_union_left {t} {h}",
                           f"simp [{h}]"],
                          "finset", "finset", "mem_union_intro", "dense_target"))
        out.append(_entry(f"fs_mem_union_right_{i}",
                          f"{F} ({s} {t} : Finset α) ({e} : α) ({h} : {e} ∈ {t}) : {e} ∈ {s} ∪ {t}",
                          [f"exact Finset.mem_union.mpr (Or.inr {h})", f"exact Finset.mem_union_right {s} {h}",
                           f"simp [{h}]"],
                          "finset", "finset", "mem_union_intro", "dense_target"))
        # subset projection
        out.append(_entry(f"fs_inter_subset_left_{i}", f"{F} ({s} {t} : Finset α) : {s} ∩ {t} ⊆ {s}",
                          ["exact Finset.inter_subset_left",
                           f"intro {e} {h}; exact (Finset.mem_inter.mp {h}).1"],
                          "finset", "finset", "inter_subset", "dense_target"))
        out.append(_entry(f"fs_inter_subset_right_{i}", f"{F} ({s} {t} : Finset α) : {s} ∩ {t} ⊆ {t}",
                          ["exact Finset.inter_subset_right",
                           f"intro {e} {h}; exact (Finset.mem_inter.mp {h}).2"],
                          "finset", "finset", "inter_subset", "dense_target"))
        out.append(_entry(f"fs_subset_union_left_{i}", f"{F} ({s} {t} : Finset α) : {s} ⊆ {s} ∪ {t}",
                          ["exact Finset.subset_union_left",
                           f"intro {e} {h}; exact Finset.mem_union.mpr (Or.inl {h})"],
                          "finset", "finset", "subset_union", "dense_target"))
        out.append(_entry(f"fs_subset_union_right_{i}", f"{F} ({s} {t} : Finset α) : {t} ⊆ {s} ∪ {t}",
                          ["exact Finset.subset_union_right",
                           f"intro {e} {h}; exact Finset.mem_union.mpr (Or.inr {h})"],
                          "finset", "finset", "subset_union", "dense_target"))
        # membership iff
        out.append(_entry(f"fs_mem_union_iff_{i}",
                          f"{F} ({s} {t} : Finset α) ({e} : α) : {e} ∈ {s} ∪ {t} ↔ {e} ∈ {s} ∨ {e} ∈ {t}",
                          ["exact Finset.mem_union", "simp [Finset.mem_union]"],
                          "finset", "finset", "mem_iff", "dense_target"))
        out.append(_entry(f"fs_mem_inter_iff_{i}",
                          f"{F} ({s} {t} : Finset α) ({e} : α) : {e} ∈ {s} ∩ {t} ↔ {e} ∈ {s} ∧ {e} ∈ {t}",
                          ["exact Finset.mem_inter", "simp [Finset.mem_inter]"],
                          "finset", "finset", "mem_iff", "dense_target"))
    # union_subset / subset_inter (3-var) + commutativity
    for i in range(3):
        s, t, u = SET3[i]
        out.append(_entry(f"fs_union_subset_{i}",
                          f"{F} ({s} {t} {u} : Finset α) (h1 : {s} ⊆ {u}) (h2 : {t} ⊆ {u}) : {s} ∪ {t} ⊆ {u}",
                          ["exact Finset.union_subset h1 h2"],
                          "finset", "finset", "union_subset", "dense_target"))
        out.append(_entry(f"fs_subset_inter_{i}",
                          f"{F} ({s} {t} {u} : Finset α) (h1 : {u} ⊆ {s}) (h2 : {u} ⊆ {t}) : {u} ⊆ {s} ∩ {t}",
                          ["exact Finset.subset_inter h1 h2",
                           "intro x hx; exact Finset.mem_inter.mpr ⟨h1 hx, h2 hx⟩"],
                          "finset", "finset", "subset_inter", "dense_target"))
    for i in range(3):
        s, t = SET2[i]
        out.append(_entry(f"fs_union_comm_{i}", f"{F} ({s} {t} : Finset α) : {s} ∪ {t} = {t} ∪ {s}",
                          [f"exact Finset.union_comm {s} {t}", "ext x; simp [Finset.mem_union, or_comm]"],
                          "finset", "finset", "union_comm", "dense_target"))
        out.append(_entry(f"fs_inter_comm_{i}", f"{F} ({s} {t} : Finset α) : {s} ∩ {t} = {t} ∩ {s}",
                          [f"exact Finset.inter_comm {s} {t}", "ext x; simp [Finset.mem_inter, and_comm]"],
                          "finset", "finset", "inter_comm", "dense_target"))
        out.append(_entry(f"fs_subset_refl_{i}", f"{F} ({s} : Finset α) : {s} ⊆ {s}",
                          [f"exact Finset.Subset.refl {s}", "intro x hx; exact hx", f"exact subset_refl {s}"],
                          "finset", "finset", "subset_refl", "support"))
    return out


# --------------------------------------------------------------------------- #
# B. SET union_subset / inter_subset / projection density
# --------------------------------------------------------------------------- #
def set_families() -> List[Entry]:
    out: List[Entry] = []
    for i in range(4):
        s, t, u = SET3[i]
        out.append(_entry(f"set_union_subset_{i}",
                          f"(α : Type) ({s} {t} {u} : Set α) (h1 : {s} ⊆ {u}) (h2 : {t} ⊆ {u}) : {s} ∪ {t} ⊆ {u}",
                          ["exact Set.union_subset h1 h2",
                           "intro x hx; exact hx.elim (fun h => h1 h) (fun h => h2 h)",
                           "rintro x (h | h); exact h1 h; exact h2 h"],
                          "set", "set", "union_subset", "dense_target"))
        out.append(_entry(f"set_subset_inter_{i}",
                          f"(α : Type) ({s} {t} {u} : Set α) (h1 : {u} ⊆ {s}) (h2 : {u} ⊆ {t}) : {u} ⊆ {s} ∩ {t}",
                          ["exact Set.subset_inter h1 h2", "intro x hx; exact ⟨h1 hx, h2 hx⟩"],
                          "set", "set", "subset_inter", "dense_target"))
        out.append(_entry(f"set_subset_trans_{i}",
                          f"(α : Type) ({s} {t} {u} : Set α) (h1 : {s} ⊆ {t}) (h2 : {t} ⊆ {u}) : {s} ⊆ {u}",
                          ["intro x hx; exact h2 (h1 hx)", "exact h1.trans h2", "exact Set.Subset.trans h1 h2"],
                          "set", "set", "subset_trans", "support"))
    for i in range(4):
        s, t = SET2[i]
        out.append(_entry(f"set_inter_subset_left_{i}", f"(α : Type) ({s} {t} : Set α) : {s} ∩ {t} ⊆ {s}",
                          ["intro x hx; exact hx.1", "exact Set.inter_subset_left", "exact fun x hx => hx.1"],
                          "set", "set", "inter_subset", "dense_target"))
        out.append(_entry(f"set_inter_subset_right_{i}", f"(α : Type) ({s} {t} : Set α) : {s} ∩ {t} ⊆ {t}",
                          ["intro x hx; exact hx.2", "exact Set.inter_subset_right", "exact fun x hx => hx.2"],
                          "set", "set", "inter_subset", "dense_target"))
        out.append(_entry(f"set_subset_union_left_{i}", f"(α : Type) ({s} {t} : Set α) : {s} ⊆ {s} ∪ {t}",
                          ["intro x hx; exact Or.inl hx", "exact Set.subset_union_left", "intro x hx; left; exact hx"],
                          "set", "set", "subset_union", "dense_target"))
        out.append(_entry(f"set_subset_union_right_{i}", f"(α : Type) ({s} {t} : Set α) : {t} ⊆ {s} ∪ {t}",
                          ["intro x hx; exact Or.inr hx", "exact Set.subset_union_right", "intro x hx; right; exact hx"],
                          "set", "set", "subset_union", "dense_target"))
        out.append(_entry(f"set_inter_comm_subset_{i}", f"(α : Type) ({s} {t} : Set α) : {s} ∩ {t} ⊆ {t} ∩ {s}",
                          ["intro x hx; exact ⟨hx.2, hx.1⟩", "exact fun x hx => ⟨hx.2, hx.1⟩"],
                          "set", "set", "inter_comm", "dense_target"))
        out.append(_entry(f"set_union_comm_subset_{i}", f"(α : Type) ({s} {t} : Set α) : {s} ∪ {t} ⊆ {t} ∪ {s}",
                          ["intro x hx; exact hx.elim Or.inr Or.inl", "exact fun x hx => hx.elim Or.inr Or.inl",
                           "rintro x (h | h); exact Or.inr h; exact Or.inl h"],
                          "set", "set", "union_comm", "dense_target"))
    # membership iff + projection + introduction (element/hyp varied)
    for i in range(4):
        s, t = SET2[i]
        e, h = ELEM[i]
        out.append(_entry(f"set_mem_inter_iff_{i}",
                          f"(α : Type) ({s} {t} : Set α) ({e} : α) : {e} ∈ {s} ∩ {t} ↔ {e} ∈ {s} ∧ {e} ∈ {t}",
                          [f"exact Set.mem_inter_iff {e} {s} {t}", "exact Iff.rfl", "rfl",
                           "constructor <;> intro hh <;> exact hh", "simp [Set.mem_inter_iff]"],
                          "set", "set", "mem_iff", "dense_target"))
        out.append(_entry(f"set_mem_union_iff_{i}",
                          f"(α : Type) ({s} {t} : Set α) ({e} : α) : {e} ∈ {s} ∪ {t} ↔ {e} ∈ {s} ∨ {e} ∈ {t}",
                          [f"exact Set.mem_union {e} {s} {t}", "exact Iff.rfl", "rfl", "simp [Set.mem_union]"],
                          "set", "set", "mem_iff", "dense_target"))
        out.append(_entry(f"set_mem_inter_left_{i}",
                          f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {s}",
                          [f"exact {h}.1", f"exact {h}.left"],
                          "set", "set", "mem_inter_proj", "dense_target"))
        out.append(_entry(f"set_mem_inter_right_{i}",
                          f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s} ∩ {t}) : {e} ∈ {t}",
                          [f"exact {h}.2", f"exact {h}.right"],
                          "set", "set", "mem_inter_proj", "dense_target"))
        out.append(_entry(f"set_mem_union_of_left_{i}",
                          f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {s}) : {e} ∈ {s} ∪ {t}",
                          [f"exact Or.inl {h}", f"left; exact {h}", f"exact Set.mem_union_left {t} {h}"],
                          "set", "set", "mem_union_intro", "dense_target"))
        out.append(_entry(f"set_mem_union_of_right_{i}",
                          f"(α : Type) ({s} {t} : Set α) ({e} : α) ({h} : {e} ∈ {t}) : {e} ∈ {s} ∪ {t}",
                          [f"exact Or.inr {h}", f"right; exact {h}", f"exact Set.mem_union_right {s} {h}"],
                          "set", "set", "mem_union_intro", "dense_target"))
    return out


# --------------------------------------------------------------------------- #
# C. ORDER le_antisymm / le_trans / le_of_eq density (polymorphic)
# --------------------------------------------------------------------------- #
def order_families() -> List[Entry]:
    out: List[Entry] = []
    for i, (a, b) in enumerate(ANTISYMM2):
        out.append(_entry(f"ord_antisymm_{i}",
                          f"(α : Type) [PartialOrder α] ({a} {b} : α) (h1 : {a} ≤ {b}) (h2 : {b} ≤ {a}) : {a} = {b}",
                          ["exact le_antisymm h1 h2"],
                          "order", "order", "antisymm", "dense_target"))
    for i, (a, b, c) in enumerate(TRANS3):
        out.append(_entry(f"ord_le_trans_pre_{i}",
                          f"(α : Type) [Preorder α] ({a} {b} {c} : α) (h1 : {a} ≤ {b}) (h2 : {b} ≤ {c}) : {a} ≤ {c}",
                          ["exact le_trans h1 h2", "exact h1.trans h2"],
                          "order", "order", "le_trans", "dense_target"))
    for i in range(5):
        a, b = ANTI2[i][0], ANTI2[i][1]
        out.append(_entry(f"ord_le_of_eq_pre_{i}",
                          f"(α : Type) [Preorder α] ({a} {b} : α) (h : {a} = {b}) : {a} ≤ {b}",
                          ["exact le_of_eq h", "exact h.le", "rw [h]"],
                          "order", "order", "le_of_eq", "dense_target"))
        out.append(_entry(f"ord_ge_of_eq_pre_{i}",
                          f"(α : Type) [Preorder α] ({a} {b} : α) (h : {a} = {b}) : {b} ≤ {a}",
                          ["exact le_of_eq h.symm", "exact h.ge", "rw [h]"],
                          "order", "order", "le_of_eq", "dense_target"))
    for i in range(3):
        a, b = ORD2[i]
        out.append(_entry(f"ord_le_refl_pre_{i}", f"(α : Type) [Preorder α] ({a} : α) : {a} ≤ {a}",
                          [f"exact le_refl {a}", "exact le_rfl"], "order", "order", "le_refl", "dense_target"))
        out.append(_entry(f"ord_le_total_{i}", f"(α : Type) [LinearOrder α] ({a} {b} : α) : {a} ≤ {b} ∨ {b} ≤ {a}",
                          [f"exact le_total {a} {b}"], "order", "order", "le_total", "dense_target"))
        out.append(_entry(f"ord_min_le_left_{i}", f"(α : Type) [LinearOrder α] ({a} {b} : α) : min {a} {b} ≤ {a}",
                          [f"exact min_le_left {a} {b}"], "order", "order", "min_max", "support"))
        out.append(_entry(f"ord_le_max_right_{i}", f"(α : Type) [LinearOrder α] ({a} {b} : α) : {b} ≤ max {a} {b}",
                          [f"exact le_max_right {a} {b}"], "order", "order", "min_max", "support"))
        out.append(_entry(f"ord_inf_le_left_{i}", f"(α : Type) [Lattice α] ({a} {b} : α) : {a} ⊓ {b} ≤ {a}",
                          ["exact inf_le_left"], "order", "order", "lattice_inf_sup", "support"))
        out.append(_entry(f"ord_le_sup_right_{i}", f"(α : Type) [Lattice α] ({a} {b} : α) : {b} ≤ {a} ⊔ {b}",
                          ["exact le_sup_right"], "order", "order", "lattice_inf_sup", "support"))
    # Nat-specific monotone (succ/add) — keeps the order skill anchored on Nat too
    for i, (n, m) in enumerate([("n", "m"), ("i", "j"), ("a", "b")]):
        out.append(_entry(f"ord_nat_succ_le_succ_{i}", f"({n} {m} : Nat) (h : {n} ≤ {m}) : {n} + 1 ≤ {m} + 1",
                          ["omega", "exact Nat.succ_le_succ h"], "order", "order", "nat_le", "support"))
        out.append(_entry(f"ord_nat_le_add_right_{i}", f"({n} {m} : Nat) : {n} ≤ {n} + {m}",
                          ["omega", f"exact Nat.le_add_right {n} {m}", "simp"], "order", "order", "nat_le", "support"))
    return out


# --------------------------------------------------------------------------- #
# D. FUNCTION comp_assoc / comp_id (renamed identifiers incl. φ ψ χ)
# --------------------------------------------------------------------------- #
def function_families() -> List[Entry]:
    out: List[Entry] = []
    for i, (f, g, h) in enumerate(ASSOC3):
        out.append(_entry(f"fun_comp_assoc_{i}",
                          f"(α β γ δ : Type) ({f} : α → β) ({g} : β → γ) ({h} : γ → δ) : ({h} ∘ {g}) ∘ {f} = {h} ∘ ({g} ∘ {f})",
                          ["rfl", "funext x; rfl", "ext x; rfl"],
                          "function", "function", "comp_assoc", "dense_target"))
    for i, (f, g, h) in enumerate(FN3):
        out.append(_entry(f"fun_comp_app_{i}",
                          f"(α β γ : Type) ({f} : β → γ) ({g} : α → β) (x : α) : ({f} ∘ {g}) x = {f} ({g} x)",
                          ["rfl", "simp"],
                          "function", "function", "comp_app", "dense_target"))
    for i, f in enumerate(["f", "g", "φ", "ψ"]):
        out.append(_entry(f"fun_comp_id_left_{i}", f"(α β : Type) ({f} : α → β) : id ∘ {f} = {f}",
                          ["rfl", "funext x; rfl", "simp", f"exact Function.id_comp {f}"],
                          "function", "function", "comp_id", "dense_target"))
        out.append(_entry(f"fun_comp_id_right_{i}", f"(α β : Type) ({f} : α → β) : {f} ∘ id = {f}",
                          ["rfl", "funext x; rfl", "simp", f"exact Function.comp_id {f}"],
                          "function", "function", "comp_id", "dense_target"))
    out.append(_entry("fun_id_apply", "(α : Type) (x : α) : id x = x", ["rfl", "simp"],
                      "function", "function", "id_apply", "support"))
    return out


# --------------------------------------------------------------------------- #
# E. NAT / LIST lemma-name vocabulary density
# --------------------------------------------------------------------------- #
def nat_list_families() -> List[Entry]:
    out: List[Entry] = []
    for i, (a, b, c) in enumerate([("a", "b", "c"), ("m", "n", "k"), ("i", "j", "l")]):
        out.append(_entry(f"nat_add_zero_{i}", f"({a} : Nat) : {a} + 0 = {a}",
                          ["rfl", "simp", "omega", f"exact Nat.add_zero {a}"], "nat", "arithmetic", "add_zero", "support"))
        out.append(_entry(f"nat_zero_add_{i}", f"({a} : Nat) : 0 + {a} = {a}",
                          ["simp", "omega", f"exact Nat.zero_add {a}"], "nat", "arithmetic", "zero_add", "support"))
        out.append(_entry(f"nat_add_comm_{i}", f"({a} {b} : Nat) : {a} + {b} = {b} + {a}",
                          ["omega", f"exact Nat.add_comm {a} {b}", "ring"], "nat", "arithmetic", "add_comm", "support"))
        out.append(_entry(f"nat_add_assoc_{i}", f"({a} {b} {c} : Nat) : {a} + {b} + {c} = {a} + ({b} + {c})",
                          ["omega", f"exact Nat.add_assoc {a} {b} {c}", "ring"], "nat", "arithmetic", "add_assoc", "support"))
        out.append(_entry(f"nat_mul_one_{i}", f"({a} : Nat) : {a} * 1 = {a}",
                          ["simp", f"exact Nat.mul_one {a}", "ring"], "nat", "arithmetic", "mul_one", "support"))
        out.append(_entry(f"nat_mul_comm_{i}", f"({a} {b} : Nat) : {a} * {b} = {b} * {a}",
                          [f"exact Nat.mul_comm {a} {b}", "ring", "ac_rfl"], "nat", "arithmetic", "mul_comm", "support"))
    for i, x in enumerate(["xs", "ys", "zs"]):
        out.append(_entry(f"list_append_nil_{i}", f"(α : Type) ({x} : List α) : {x} ++ [] = {x}",
                          ["simp", f"exact List.append_nil {x}"], "list", "list", "append_nil", "support"))
        out.append(_entry(f"list_nil_append_{i}", f"(α : Type) ({x} : List α) : [] ++ {x} = {x}",
                          ["rfl", "simp", f"exact List.nil_append {x}"], "list", "list", "nil_append", "support"))
        out.append(_entry(f"list_map_id_{i}", f"(α : Type) ({x} : List α) : {x}.map id = {x}",
                          ["simp", f"exact List.map_id {x}"], "list", "list", "map_id", "support"))
        out.append(_entry(f"list_reverse_reverse_{i}", f"(α : Type) ({x} : List α) : {x}.reverse.reverse = {x}",
                          ["simp", f"exact List.reverse_reverse {x}"], "list", "list", "reverse_reverse", "support"))
    return out


# --------------------------------------------------------------------------- #
# F. LOGIC And/Or shape density
# --------------------------------------------------------------------------- #
def logic_families() -> List[Entry]:
    out: List[Entry] = []
    for i, (p, q) in enumerate([("p", "q"), ("a", "b"), ("r", "s")]):
        out.append(_entry(f"logic_and_symm_{i}", f"({p} {q} : Prop) (h : {p} ∧ {q}) : {q} ∧ {p}",
                          ["exact ⟨h.2, h.1⟩", "exact h.symm", "tauto", "aesop"], "logic", "logic", "and_symm", "support"))
        out.append(_entry(f"logic_or_symm_{i}", f"({p} {q} : Prop) (h : {p} ∨ {q}) : {q} ∨ {p}",
                          ["exact h.symm", "exact Or.symm h", "tauto", "aesop"], "logic", "logic", "or_symm", "support"))
        out.append(_entry(f"logic_imp_trans_{i}",
                          f"({p} {q} c : Prop) (h1 : {p} → {q}) (h2 : {q} → c) : {p} → c",
                          ["intro hp; exact h2 (h1 hp)", "exact fun hp => h2 (h1 hp)", "tauto"],
                          "logic", "logic", "imp_trans", "support"))
        out.append(_entry(f"logic_contrapose_{i}", f"({p} {q} : Prop) (h : {p} → {q}) : ¬{q} → ¬{p}",
                          ["intro hq hp; exact hq (h hp)", "exact fun hq hp => hq (h hp)", "tauto"],
                          "logic", "logic", "contrapose", "support"))
        out.append(_entry(f"logic_false_elim_{i}", f"({p} : Prop) (h : False) : {p}",
                          ["exact False.elim h", "exact h.elim", "tauto"], "logic", "logic", "false_elim", "support"))
    return out


def build_plan() -> List[Entry]:
    plan: List[Entry] = []
    plan += finset_families()
    plan += set_families()
    plan += order_families()
    plan += function_families()
    plan += nat_list_families()
    plan += logic_families()
    return plan


# --------------------------------------------------------------------------- #
# leakage guard: v18 + v25/v26/v27/v28 held-out benchmarks
# --------------------------------------------------------------------------- #
def _read(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if p.exists() else []


def _heldout_guard() -> Tuple[Set, Set]:
    """(triples, stmt_state_pairs) for v25 + v26 + v27 + v28 held-out test benchmarks."""
    triples: Set = set()
    pairs: Set = set()

    def add_rows(rows):
        for r in rows:
            triples.add((r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", "")))
            pairs.add((r.get("theorem_statement", ""), r.get("state_before", "")))

    def add_seeds(rows):
        for s in rows:
            pairs.add((s.get("theorem_statement", ""), s.get("state_before", "")))

    v25 = ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"
    v25_names = {s["theorem_name"] for s in _read(v25)}
    add_seeds(_read(v25))
    add_rows([r for r in _read(ROOT / "data" / "traces" / "v25_mathlib_tierc_verified.jsonl")
              if r.get("theorem_name") in v25_names])
    for th in (ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout",
               ROOT / "data" / "processed" / "v27_mathlib_specialist" / "theorem_holdout",
               ROOT / "data" / "processed" / "v28_mathlib_specialist" / "theorem_holdout"):
        add_rows(_read(th / "test_rows.jsonl"))
        add_seeds(_read(th / "test_seeds.jsonl"))
    return triples, pairs


def _bool(s: str, sub: str) -> bool:
    return sub in (s or "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--lean-path-file", default=str(ROOT / ".tmp" / "v27_lean_path.txt"))
    ap.add_argument("--out-seeds", default=str(ROOT / "data" / "seeds" / "v29_mathlib_density_seeds.jsonl"))
    ap.add_argument("--out-candidates", default=str(ROOT / "data" / "manual" / "v29_mathlib_density_candidates.jsonl"))
    ap.add_argument("--out-verified", default=str(ROOT / "data" / "traces" / "v29_mathlib_density_verified.jsonl"))
    ap.add_argument("--out-failed", default=str(ROOT / "data" / "traces" / "v29_mathlib_density_failed.jsonl"))
    ap.add_argument("--out-train-rows", default=str(ROOT / "data" / "processed" / "v29_mathlib_specialist" / "density_train_rows.jsonl"))
    ap.add_argument("--summary", default=str(ROOT / "data" / "processed" / "v29_mathlib_specialist" / "density_summary.json"))
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--batch-size", type=int, default=80)
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    lean_path = Path(args.lean_path_file).read_text().strip() if Path(args.lean_path_file).exists() else None
    plan = build_plan()
    names = [e["theorem_name"] for e in plan]
    assert len(names) == len(set(names)), "duplicate v29 theorem names: " + \
        str([n for n in names if names.count(n) > 1][:5])
    logger.info("v29 density plan: %d theorems", len(plan))

    verifier = TrustedMathlibVerifier(scratch, lean_path=lean_path,
                                      timeout=args.timeout, batch_size=args.batch_size)
    logger.info("warming up import Mathlib ...")
    if not verifier.warmup():
        logger.error("Mathlib warmup FAILED — aborting")
        return 2
    logger.info("warmup ok")

    work: List[Tuple[str, str, str]] = []
    work_meta: List[Entry] = []
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

    for p in (args.out_seeds, args.out_candidates, args.out_verified, args.out_failed, args.out_train_rows):
        Path(p).parent.mkdir(parents=True, exist_ok=True)

    seeds = []
    for entry in plan:
        nm, stmt = entry["theorem_name"], entry["theorem_statement"]
        seeds.append({"theorem_name": nm, "theorem_statement": stmt,
                      "state_before": state_before(stmt),
                      "template": f"example {stmt} := by\n  __TACTIC__",
                      "placeholder": "__TACTIC__", "imports": [MATHLIB_IMPORT],
                      "category": entry["category"], "expected_skill": entry["expected_skill"],
                      "theorem_family": entry["theorem_family"], "density_group": entry["density_group"],
                      "transfer": "mathlib", "source": "v29_mathlib_density", "mathlib": True})

    verified, failed, train_rows = [], [], []
    per_cat: Dict[str, Dict[str, int]] = defaultdict(lambda: {"theorems": 0, "proposed": 0, "verified": 0, "failed": 0})
    per_fam: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"theorems": set(), "verified_rows": 0})
    for e in plan:
        per_cat[e["category"]]["theorems"] += 1
        per_fam[e["theorem_family"]]["theorems"].add(e["theorem_name"])
    lean_ok: Dict[str, bool] = {e["theorem_name"]: False for e in plan}
    has_row: Dict[str, bool] = {e["theorem_name"]: False for e in plan}
    n_timeout = n_rejected = dn = dt = dpair = 0

    for vd, entry in zip(verdicts, work_meta):
        nm, stmt, cand = vd.theorem_name, vd.statement, vd.tactic
        cat = entry["category"]
        fam = entry["theorem_family"]
        st = state_before(stmt)
        per_cat[cat]["proposed"] += 1
        rec = {"theorem_name": nm, "theorem_statement": stmt, "state_before": st,
               "tactic": cand, "category": cat, "expected_skill": entry["expected_skill"],
               "theorem_family": fam, "density_group": entry["density_group"], "transfer": "mathlib",
               "imports": [MATHLIB_IMPORT], "corpus_source": "v29_mathlib_density",
               "verifier": "TrustedMathlibVerifier (sentinel+confirm+rescue, import Mathlib)",
               "proof_head": proof_head(cand),
               "uses_simp": _bool(cand, "simp"), "uses_ext": _bool(cand, "ext") or _bool(cand, "funext"),
               "uses_aesop": _bool(cand, "aesop"), "uses_omega": _bool(cand, "omega"),
               "uses_set": cat == "set", "uses_finset": cat == "finset",
               "uses_order": cat == "order", "uses_function": cat == "function",
               "uses_mathlib_lemma": ("." in cand and "exact" in cand),
               "mathlib": True, "source": "v29_mathlib_density"}
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
        per_fam[fam]["verified_rows"] += 1
        has_row[nm] = True
        verified.append({**rec, "verified": True})
        train_rows.append({"theorem_name": nm, "theorem_statement": stmt, "state_before": st,
                           "tactic": cand, "category": cat, "family": cat,
                           "expected_skill": entry["expected_skill"],
                           "required_operation": entry["expected_skill"],
                           "theorem_family": fam, "density_group": entry["density_group"],
                           "corpus_source": "v29_mathlib_density", "tactic_source": "verified",
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

    fam_density = {f: {"n_theorems": len(d["theorems"]), "n_verified_rows": d["verified_rows"]}
                   for f, d in sorted(per_fam.items())}
    summary = {
        "config": "v29_mathlib_density", "mathlib_available": True,
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
        "by_family": fam_density,
        "verified_proof_heads": dict(Counter(r["proof_head"] for r in verified).most_common()),
        "n_lean_invocations": verifier.n_invocations,
        "total_lean_seconds": round(verifier.total_lean_seconds, 1),
        "uses_state_after": False, "uses_manual_oracle": False, "uses_mathlib": True,
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("v29 density corpus: theorems=%d verified_rows=%d lean_rejected=%d "
                "thms_with_rows=%d drops v18name/v18triple/heldout=%d/%d/%d",
                len(plan), len(verified), n_rejected, len(thms_with_rows), dn, dt, dpair)
    for cat, d in sorted(per_cat.items()):
        logger.info("  %-10s train_rows=%d/%d theorems=%d failed=%d", cat, d["verified"], d["proposed"], d["theorems"], d["failed"])
    if zero_lean:
        logger.warning("TRUE coverage gaps (Lean rejected ALL candidates): %s", zero_lean)
    if stripped:
        logger.info("verified-but-benchmark (stripped by guards, NOT gaps): %d", len(stripped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
