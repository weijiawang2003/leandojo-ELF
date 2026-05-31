"""Generator for the **planner-blind** Lean corpus (Mini-ELF v4).

v3 saturated the hard corpus (`difficulty_holdout` `pass@5` 0.06 → 1.00) — but
the V4 coverage audit (`scripts/audit_planner_coverage.py`,
`docs/V4_PLANNER_COVERAGE_AUDIT.md`) shows that lift is **engineered symbolic
coverage**: the planner constructs only a *closed* catalog of proof shapes. This
corpus is built from proof families the planner is provably **blind** to —
negation / contradiction, contrapositive `¬`-goals, `∃`-elimination,
`∀`-instantiation, rewrite / substitution, and negation inside a case split — so
that *unchanged* v3 has to fall back on its learned generator + witness-copy.
That fallback is the real robustness test (`docs/V4_PLANNER_BLIND_REPORT.md`).

Emits (never overwriting basic/hard):

  data/seeds/planner_blind_seeds.jsonl
  data/manual/planner_blind_candidates.jsonl

Core Lean 4 only (`imports=[]`); intuitionistic (no `¬¬p → p`, no classical
`by_contra`). Confirmed-accepted tactics: `absurd`, `False.elim`, `(h x).elim`,
`contradiction`, `rcases`/`obtain`/`⟨⟩` destructuring, `rw [h]`,
`congrArg`, `subst`, `▸`, and `∀`-instantiation `h x` (verified against the
toolchain before commit). Every theorem carries the v4 capability flags
(`requires_negation` / `requires_exists_elim` / `requires_forall` /
`requires_rewrite`) and `planner_blind=true`.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

SOURCE = "planner-blind-manual-corpus"


@dataclass(frozen=True)
class Entry:
    name: str
    pattern_family: str
    statement_fragment: str
    initial_state: str
    correct: Tuple[str, ...]
    wrong: Tuple[str, ...] = ()
    difficulty: str = "hard"
    requires_negation: bool = False
    requires_exists_elim: bool = False
    requires_forall: bool = False
    requires_rewrite: bool = False

    @property
    def candidates(self) -> List[str]:
        out: List[str] = []
        for t in (*self.correct, *self.wrong):
            if t not in out:
                out.append(t)
        return out


def _state(hyps: Sequence[str], goal: str) -> str:
    return "\n".join([*hyps, f"⊢ {goal}"])


# ---------------- 1. negation: ex falso (¬p + p ⊢ q) ----------------


def fam_neg_exfalso() -> List[Entry]:
    fam = "neg_exfalso"
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("x", "y"), ("p", "r"), ("a", "c")]:
        out.append(Entry(
            f"neg_exfalso_{a}{b}", fam,
            f"({a} {b} : Prop) (hp : {a}) (hnp : ¬{a}) : {b}",
            _state([f"{a} {b} : Prop", f"hp : {a}", f"hnp : ¬{a}"], b),
            ("exact absurd hp hnp", "exact (hnp hp).elim", "exact False.elim (hnp hp)",
             "contradiction"),
            ("exact hp", "assumption", "exact hnp"),
            difficulty="medium", requires_negation=True,
        ))
    # explicit `p → False` form
    for a, b in [("p", "q"), ("a", "b"), ("x", "y")]:
        out.append(Entry(
            f"neg_exfalso_arrow_{a}{b}", fam,
            f"({a} {b} : Prop) (h : {a} → False) (hp : {a}) : {b}",
            _state([f"{a} {b} : Prop", f"h : {a} → False", f"hp : {a}"], b),
            ("exact (h hp).elim", "exact False.elim (h hp)", "exact absurd hp h",
             "contradiction"),
            ("exact hp", "exact h"),
            difficulty="medium", requires_negation=True,
        ))
    return out


# ---------------- 2. contrapositive ( ⊢ ¬p ) ----------------


def fam_neg_contrapositive() -> List[Entry]:
    fam = "neg_contrapositive"
    correct = ("intro hp\n  exact hnq (h hp)", "exact fun hp => hnq (h hp)")
    wrong = ("exact h", "intro hp\n  exact hp", "exact hnq")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("x", "y"), ("p", "r"), ("a", "c"), ("m", "n")]:
        out.append(Entry(
            f"neg_contrapositive_{a}{b}", fam,
            f"({a} {b} : Prop) (h : {a} → {b}) (hnq : ¬{b}) : ¬{a}",
            _state([f"{a} {b} : Prop", f"h : {a} → {b}", f"hnq : ¬{b}"], f"¬{a}"),
            correct, wrong, difficulty="hard", requires_negation=True,
        ))
    return out


# ---------------- 3. ex falso inside an implication ( ¬p ⊢ p → q ) ----------------


def fam_neg_imp_exfalso() -> List[Entry]:
    fam = "neg_imp_exfalso"
    correct = ("intro hp\n  exact absurd hp hnp", "intro hp\n  exact (hnp hp).elim",
               "exact fun hp => (hnp hp).elim")
    wrong = ("intro hp\n  exact hp", "exact hnp", "exact id")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("x", "y"), ("p", "s"), ("a", "d")]:
        out.append(Entry(
            f"neg_imp_exfalso_{a}{b}", fam,
            f"({a} {b} : Prop) (hnp : ¬{a}) : {a} → {b}",
            _state([f"{a} {b} : Prop", f"hnp : ¬{a}"], f"{a} → {b}"),
            correct, wrong, difficulty="hard", requires_negation=True,
        ))
    return out


# ---------------- 4. double-negation introduction ( p ⊢ ¬¬p ) ----------------


def fam_neg_double_intro() -> List[Entry]:
    fam = "neg_double_intro"
    correct = ("intro hnp\n  exact hnp hp", "exact fun hnp => hnp hp")
    wrong = ("exact hp", "intro hnp\n  exact hp", "exact hp hp")
    out: List[Entry] = []
    for a in ("p", "q", "r", "s", "a"):
        out.append(Entry(
            f"neg_double_intro_{a}", fam,
            f"({a} : Prop) (hp : {a}) : ¬¬{a}",
            _state([f"{a} : Prop", f"hp : {a}"], f"¬¬{a}"),
            correct, wrong, difficulty="hard", requires_negation=True,
        ))
    return out


# ---------------- 5. negation inside a case split ( p ∨ q, ¬p ⊢ q ) ----------------


def fam_neg_or_cases() -> List[Entry]:
    fam = "neg_or_cases"
    correct = (
        "cases h with\n  | inl hp => exact absurd hp hnp\n  | inr hq => exact hq",
        "rcases h with hp | hq\n  exact absurd hp hnp\n  exact hq",
    )
    wrong = ("exact h", "exact hq",
             "cases h with\n  | inl hp => exact hp\n  | inr hq => exact hq")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("x", "y"), ("p", "s"), ("a", "d"), ("m", "n")]:
        out.append(Entry(
            f"neg_or_cases_{a}{b}", fam,
            f"({a} {b} : Prop) (h : {a} ∨ {b}) (hnp : ¬{a}) : {b}",
            _state([f"{a} {b} : Prop", f"h : {a} ∨ {b}", f"hnp : ¬{a}"], b),
            correct, wrong, difficulty="hard", requires_negation=True,
        ))
    return out


# ---------------- 6. exists-elimination ( ∃ _ : Nat, p ⊢ p ) ----------------


def fam_exists_elim_prop() -> List[Entry]:
    fam = "exists_elim_prop"
    correct = ("rcases h with ⟨n, hp⟩\n  exact hp", "obtain ⟨n, hp⟩ := h\n  exact hp",
               "exact h.elim fun _ hp => hp")
    wrong = ("exact h", "exact h.2", "exact h.1")
    out: List[Entry] = []
    for a in ("p", "q", "r", "s", "a", "b"):
        out.append(Entry(
            f"exists_elim_prop_{a}", fam,
            f"({a} : Prop) (h : ∃ _ : Nat, {a}) : {a}",
            _state([f"{a} : Prop", f"h : ∃ _ : Nat, {a}"], a),
            correct, wrong, difficulty="hard", requires_exists_elim=True,
        ))
    return out


# ---------------- 7. exists-elimination with conjunction body ----------------


def fam_exists_elim_conj() -> List[Entry]:
    fam = "exists_elim_conj"
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("x", "y"), ("p", "s")]:
        out.append(Entry(
            f"exists_elim_conj_l_{a}{b}", fam,
            f"({a} {b} : Prop) (h : ∃ _ : Nat, {a} ∧ {b}) : {a}",
            _state([f"{a} {b} : Prop", f"h : ∃ _ : Nat, {a} ∧ {b}"], a),
            ("rcases h with ⟨n, hp, hq⟩\n  exact hp", "obtain ⟨n, hpq⟩ := h\n  exact hpq.1"),
            ("exact h", "exact h.1"),
            difficulty="hard", requires_exists_elim=True,
        ))
        out.append(Entry(
            f"exists_elim_conj_r_{a}{b}", fam,
            f"({a} {b} : Prop) (h : ∃ _ : Nat, {a} ∧ {b}) : {b}",
            _state([f"{a} {b} : Prop", f"h : ∃ _ : Nat, {a} ∧ {b}"], b),
            ("rcases h with ⟨n, hp, hq⟩\n  exact hq", "obtain ⟨n, hpq⟩ := h\n  exact hpq.2"),
            ("exact h", "exact h.2"),
            difficulty="hard", requires_exists_elim=True,
        ))
    return out


# ---------------- 8. forall-instantiation ( ∀ x, x = c ⊢ k = c ) ----------------


def fam_forall_inst() -> List[Entry]:
    fam = "forall_inst"
    out: List[Entry] = []
    for k, c in [(7, 0), (3, 0), (5, 2), (9, 4), (13, 6)]:
        out.append(Entry(
            f"forall_inst_{k}_{c}", fam,
            f"(h : ∀ x : Nat, x = {c}) : {k} = {c}",
            _state([f"h : ∀ x : Nat, x = {c}"], f"{k} = {c}"),
            (f"exact h {k}",),
            ("rfl", "exact h", f"exact h {c}"),
            difficulty="medium", requires_forall=True,
        ))
    # forall over a variable target
    for v in ("m", "k"):
        out.append(Entry(
            f"forall_inst_var_{v}", fam,
            f"({v} : Nat) (h : ∀ x : Nat, x = {v}) : 8 = {v}",
            _state([f"{v} : Nat", f"h : ∀ x : Nat, x = {v}"], f"8 = {v}"),
            ("exact h 8",),
            ("rfl", "exact h", f"exact h {v}"),
            difficulty="medium", requires_forall=True,
        ))
    return out


# ---------------- 9. rewrite / substitution ( n = m ⊢ n.succ = m.succ ) ----------------


def fam_rewrite_succ() -> List[Entry]:
    fam = "rewrite_succ"
    correct = ("rw [h]", "exact congrArg Nat.succ h", "subst h\n  rfl", "exact h ▸ rfl")
    wrong = ("exact h", "rfl", "exact h.symm")
    out: List[Entry] = []
    for n, m in [("n", "m"), ("a", "b"), ("x", "y"), ("i", "j"), ("k", "l")]:
        out.append(Entry(
            f"rewrite_succ_{n}{m}", fam,
            f"({n} {m} : Nat) (h : {n} = {m}) : {n}.succ = {m}.succ",
            _state([f"{n} {m} : Nat", f"h : {n} = {m}"], f"{n}.succ = {m}.succ"),
            correct, wrong, difficulty="hard", requires_rewrite=True,
        ))
    return out


# ---------------- 10. exists-elim that witness-copy can shortcut (honest control) ----------------


def fam_exists_reconstruct() -> List[Entry]:
    # ∃ n, n = k ⊢ ∃ m, m = k.  Intended proof eliminates h, but `exact h`
    # (alpha-equiv) and witness-copy `⟨k, rfl⟩` both also close it — included to
    # measure how much the *non-planner* sources rescue ∃-elimination.
    fam = "exists_reconstruct"
    out: List[Entry] = []
    for k in (3, 7, 11, 20, 100):
        out.append(Entry(
            f"exists_reconstruct_{k}", fam,
            f"(h : ∃ n : Nat, n = {k}) : ∃ m : Nat, m = {k}",
            _state([f"h : ∃ n : Nat, n = {k}"], f"∃ m : Nat, m = {k}"),
            ("rcases h with ⟨n, hn⟩\n  exact ⟨n, hn⟩", "exact h", f"exact ⟨{k}, rfl⟩"),
            ("exact h.1", "rfl"),
            difficulty="medium", requires_exists_elim=True,
        ))
    return out


BLIND_FAMILY_BUILDERS = (
    fam_neg_exfalso, fam_neg_contrapositive, fam_neg_imp_exfalso,
    fam_neg_double_intro, fam_neg_or_cases,
    fam_exists_elim_prop, fam_exists_elim_conj,
    fam_forall_inst, fam_rewrite_succ, fam_exists_reconstruct,
)


def all_entries() -> List[Entry]:
    out: List[Entry] = []
    seen: set = set()
    for build in BLIND_FAMILY_BUILDERS:
        for e in build():
            if e.name in seen:
                raise ValueError(f"duplicate theorem name: {e.name}")
            seen.add(e.name)
            out.append(e)
    return out


def _meta(e: Entry) -> dict:
    return {
        "pattern_family": e.pattern_family,
        "difficulty": e.difficulty,
        "requires_negation": e.requires_negation,
        "requires_exists_elim": e.requires_exists_elim,
        "requires_forall": e.requires_forall,
        "requires_rewrite": e.requires_rewrite,
        "planner_blind": True,
        "expected_success_tactics": list(e.correct),
    }


def _seed_row(e: Entry) -> dict:
    return {
        "theorem_name": e.name,
        "theorem_statement": e.statement_fragment,
        "initial_state": e.initial_state,
        "imports": [],
        "template": f"example {e.statement_fragment} := by\n  __TACTIC__",
        "placeholder": "__TACTIC__",
        "metadata": _meta(e),
    }


def _candidate_row(e: Entry) -> dict:
    return {
        "theorem_name": e.name,
        "state_before": e.initial_state,
        "candidates": e.candidates,
        "source": SOURCE,
        "prompt_style": "diverse",
        "metadata": _meta(e),
    }


def write_corpus(seeds_path: Path, candidates_path: Path,
                 *, entries: Optional[Sequence[Entry]] = None) -> Tuple[int, int]:
    rows = list(entries) if entries is not None else all_entries()
    seeds_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    with seeds_path.open("w", encoding="utf-8") as fh:
        fh.write("# Generated by scripts/generate_planner_blind_corpus.py. Do not edit by hand.\n")
        fh.write(f"# {len(rows)} planner-blind core-Lean theorems (no Mathlib): shapes the v3 planner cannot construct.\n")
        for e in rows:
            fh.write(json.dumps(_seed_row(e), ensure_ascii=False, sort_keys=True) + "\n")
    n_cands = 0
    with candidates_path.open("w", encoding="utf-8") as fh:
        fh.write("# Generated by scripts/generate_planner_blind_corpus.py. Do not edit by hand.\n")
        fh.write("# Candidates keyed by (theorem_name, state_before == seed.initial_state).\n")
        for e in rows:
            fh.write(json.dumps(_candidate_row(e), ensure_ascii=False, sort_keys=True) + "\n")
            n_cands += len(e.candidates)
    return len(rows), n_cands


def _parse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--seeds-out", type=Path, default=Path("data/seeds/planner_blind_seeds.jsonl"))
    p.add_argument("--candidates-out", type=Path,
                   default=Path("data/manual/planner_blind_candidates.jsonl"))
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse().parse_args(argv)
    entries = all_entries()
    n_seeds, n_cands = write_corpus(args.seeds_out, args.candidates_out, entries=entries)
    fams = Counter(e.pattern_family for e in entries)
    diffs = Counter(e.difficulty for e in entries)
    print(f"wrote {n_seeds} seeds -> {args.seeds_out}")
    print(f"wrote {n_cands} candidate tactics -> {args.candidates_out}")
    print(f"{len(fams)} planner-blind families:")
    for fam, n in sorted(fams.items()):
        print(f"  {fam:22s} {n}")
    print(f"difficulty: {dict(sorted(diffs.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
