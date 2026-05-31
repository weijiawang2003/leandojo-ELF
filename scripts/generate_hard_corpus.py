"""Generator for the **hard** Lean theorem-level corpus (Mini-ELF v2).

A deliberately less-templated, more *compositional* sibling of the basic corpus
(`scripts/generate_basic_corpus.py`). It exists to test **generalization**: the
basic corpus is small and templated, so v1's headline numbers may be optimistic.
The hard corpus stresses multi-step proofs, nested structure, case splits, iff
directionality, equality chains, and existential witnesses with *unseen* literals.

Emits two files (never overwriting the basic corpus):

  data/seeds/hard_lean_seeds.jsonl          - LeanCliRunner seeds (template + initial_state)
  data/manual/hard_lean_candidates.jsonl    - ManualFileLLMClient candidates

Core Lean 4 only (no Mathlib; `imports=[]`). The verifying toolchain accepts
`rcases` / `cases ... with` / `constructor` / `refine` / `.trans` / `.symm` /
`.mp` / `.mpr` / anonymous constructors `⟨…⟩` and projections `.1/.2/.left/.right`
(confirmed against the basic corpus's verified traces).

Each :class:`Entry` carries difficulty + capability flags
(`requires_multistep` / `requires_copy` / `requires_structure`) so the v2 split
strategies (difficulty holdout, adversarial sibling) and per-difficulty metrics
have ground-truth metadata. ``correct`` tactics are shared within a family by
keeping hypothesis names constant and varying only the Prop/type names.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

SOURCE = "hard-manual-corpus"


@dataclass(frozen=True)
class Entry:
    name: str
    pattern_family: str
    statement_fragment: str       # between 'example ' and ':=' in the template
    initial_state: str            # conventional pp; also the candidate match key
    correct: Tuple[str, ...]      # intended-to-typecheck tactics
    wrong: Tuple[str, ...] = ()   # deliberate near-miss / wrong tactics
    difficulty: str = "hard"      # easy | medium | hard
    requires_multistep: bool = False
    requires_copy: bool = False
    requires_structure: bool = False

    @property
    def candidates(self) -> List[str]:
        out: List[str] = []
        for t in (*self.correct, *self.wrong):
            if t not in out:
                out.append(t)
        return out


def _state(hyps: Sequence[str], goal: str) -> str:
    return "\n".join([*hyps, f"⊢ {goal}"])


# ---------------- 1. multi-step implication chains ----------------


def fam_imp_chain3() -> List[Entry]:
    fam = "imp_chain3"
    correct = ("intro h\n  exact h3 (h2 (h1 h))", "exact fun h => h3 (h2 (h1 h))")
    wrong = ("intro h\n  exact h3 (h1 h)", "exact h1", "intro h\n  exact h")
    out: List[Entry] = []
    for a, b, c, d in [("p", "q", "r", "s"), ("a", "b", "c", "d"), ("w", "x", "y", "z"),
                       ("p", "q", "r", "t"), ("a", "b", "d", "e"), ("m", "n", "o", "u")]:
        out.append(Entry(
            f"imp_chain3_{a}{b}{c}{d}", fam,
            f"({a} {b} {c} {d} : Prop) (h1 : {a} → {b}) (h2 : {b} → {c}) (h3 : {c} → {d}) : {a} → {d}",
            _state([f"{a} {b} {c} {d} : Prop", f"h1 : {a} → {b}", f"h2 : {b} → {c}", f"h3 : {c} → {d}"],
                   f"{a} → {d}"),
            correct, wrong, difficulty="hard", requires_multistep=True,
        ))
    return out


def fam_imp_uncurry() -> List[Entry]:
    fam = "imp_uncurry"
    correct = ("intro ha hb\n  exact h ⟨ha, hb⟩", "exact fun ha hb => h ⟨ha, hb⟩")
    wrong = ("intro ha hb\n  exact h ha", "exact h", "intro ha hb\n  exact h ⟨hb, ha⟩")
    out: List[Entry] = []
    for a, b, c in [("p", "q", "r"), ("a", "b", "c"), ("x", "y", "z"),
                    ("p", "q", "s"), ("a", "c", "d"), ("m", "n", "o")]:
        out.append(Entry(
            f"imp_uncurry_{a}{b}{c}", fam,
            f"({a} {b} {c} : Prop) (h : {a} ∧ {b} → {c}) : {a} → {b} → {c}",
            _state([f"{a} {b} {c} : Prop", f"h : {a} ∧ {b} → {c}"], f"{a} → {b} → {c}"),
            correct, wrong, difficulty="hard", requires_multistep=True, requires_structure=True,
        ))
    return out


def fam_imp_chain_mixed() -> List[Entry]:
    fam = "imp_chain_mixed"
    correct = ("exact h2 (h1 h3.1)", "exact h2 (h1 h3.left)")
    wrong = ("exact h2 (h1 h3.2)", "exact h1 h3.1", "exact h2 h3.1")
    out: List[Entry] = []
    for a, b, c, t in [("p", "q", "r", "t"), ("a", "b", "c", "d"), ("x", "y", "z", "w"),
                       ("p", "q", "s", "u"), ("a", "b", "e", "f")]:
        out.append(Entry(
            f"imp_chain_mixed_{a}{b}{c}{t}", fam,
            f"({a} {b} {c} {t} : Prop) (h1 : {a} → {b}) (h2 : {b} → {c}) (h3 : {a} ∧ {t}) : {c}",
            _state([f"{a} {b} {c} {t} : Prop", f"h1 : {a} → {b}", f"h2 : {b} → {c}", f"h3 : {a} ∧ {t}"],
                   f"{c}"),
            correct, wrong, difficulty="hard", requires_multistep=True, requires_structure=True,
        ))
    return out


# ---------------- 2. nested conjunction elim / intro ----------------


def fam_nested_and_elim_r() -> List[Entry]:
    # h : p ∧ q ∧ r  (right-assoc: p ∧ (q ∧ r))
    fam = "nested_and_elim_r"
    out: List[Entry] = []
    for a, b, c in [("p", "q", "r"), ("a", "b", "c"), ("x", "y", "z"), ("p", "q", "s")]:
        out.append(Entry(
            f"nested_and_r_last_{a}{b}{c}", fam,
            f"({a} {b} {c} : Prop) (h : {a} ∧ {b} ∧ {c}) : {c}",
            _state([f"{a} {b} {c} : Prop", f"h : {a} ∧ {b} ∧ {c}"], f"{c}"),
            ("exact h.2.2", "exact h.right.right"), ("exact h.1", "exact h.2.1", "exact h.2"),
            difficulty="hard", requires_structure=True,
        ))
        out.append(Entry(
            f"nested_and_r_mid_{a}{b}{c}", fam,
            f"({a} {b} {c} : Prop) (h : {a} ∧ {b} ∧ {c}) : {b}",
            _state([f"{a} {b} {c} : Prop", f"h : {a} ∧ {b} ∧ {c}"], f"{b}"),
            ("exact h.2.1", "exact h.right.left"), ("exact h.1", "exact h.2.2", "exact h.2"),
            difficulty="hard", requires_structure=True,
        ))
    return out


def fam_nested_and_elim_l() -> List[Entry]:
    # h : (p ∧ q) ∧ r
    fam = "nested_and_elim_l"
    out: List[Entry] = []
    for a, b, c in [("p", "q", "r"), ("a", "b", "c"), ("x", "y", "z"), ("p", "r", "s")]:
        out.append(Entry(
            f"nested_and_l_first_{a}{b}{c}", fam,
            f"({a} {b} {c} : Prop) (h : ({a} ∧ {b}) ∧ {c}) : {a}",
            _state([f"{a} {b} {c} : Prop", f"h : ({a} ∧ {b}) ∧ {c}"], f"{a}"),
            ("exact h.1.1", "exact h.left.left"), ("exact h.2", "exact h.1.2", "exact h.1"),
            difficulty="hard", requires_structure=True,
        ))
        out.append(Entry(
            f"nested_and_l_mid_{a}{b}{c}", fam,
            f"({a} {b} {c} : Prop) (h : ({a} ∧ {b}) ∧ {c}) : {b}",
            _state([f"{a} {b} {c} : Prop", f"h : ({a} ∧ {b}) ∧ {c}"], f"{b}"),
            ("exact h.1.2", "exact h.left.right"), ("exact h.2", "exact h.1.1", "exact h.1"),
            difficulty="hard", requires_structure=True,
        ))
    return out


def fam_nested_and_intro() -> List[Entry]:
    fam = "nested_and_intro"
    out: List[Entry] = []
    for a, b, c in [("p", "q", "r"), ("a", "b", "c"), ("x", "y", "z"), ("p", "q", "s")]:
        hyps = [f"{a} {b} {c} : Prop", "hp : " + a, "hq : " + b, "hr : " + c]
        out.append(Entry(
            f"nested_and_intro_skip_{a}{b}{c}", fam,
            f"({a} {b} {c} : Prop) (hp : {a}) (hq : {b}) (hr : {c}) : {a} ∧ {c}",
            _state(hyps, f"{a} ∧ {c}"),
            ("exact ⟨hp, hr⟩", "constructor\n  exact hp\n  exact hr"),
            ("exact ⟨hp, hq⟩", "exact ⟨hr, hp⟩"),
            difficulty="medium", requires_structure=True,
        ))
        out.append(Entry(
            f"nested_and_intro_ll_{a}{b}{c}", fam,
            f"({a} {b} {c} : Prop) (hp : {a}) (hq : {b}) (hr : {c}) : ({a} ∧ {b}) ∧ {c}",
            _state(hyps, f"({a} ∧ {b}) ∧ {c}"),
            ("exact ⟨⟨hp, hq⟩, hr⟩", "exact And.intro (And.intro hp hq) hr"),
            ("exact ⟨hp, hq, hr⟩", "exact ⟨hp, ⟨hq, hr⟩⟩"),
            difficulty="hard", requires_structure=True,
        ))
        out.append(Entry(
            f"nested_and_intro_rr_{a}{b}{c}", fam,
            f"({a} {b} {c} : Prop) (hp : {a}) (hq : {b}) (hr : {c}) : {a} ∧ {b} ∧ {c}",
            _state(hyps, f"{a} ∧ {b} ∧ {c}"),
            ("exact ⟨hp, hq, hr⟩", "exact ⟨hp, ⟨hq, hr⟩⟩"),
            ("exact ⟨⟨hp, hq⟩, hr⟩", "exact ⟨hp, hq⟩"),
            difficulty="hard", requires_structure=True,
        ))
    return out


# ---------------- 3. or elimination / case splits ----------------


def fam_or_elim() -> List[Entry]:
    fam = "or_elim"
    correct = (
        "cases h with\n  | inl hx => exact hp hx\n  | inr hx => exact hq hx",
        "rcases h with hx | hx\n  exact hp hx\n  exact hq hx",
        "exact Or.elim h hp hq",
    )
    wrong = ("exact hp h", "exact h", "cases h with\n  | inl hx => exact hp hx")
    out: List[Entry] = []
    for a, b, c in [("p", "q", "r"), ("a", "b", "c"), ("x", "y", "z"),
                    ("p", "q", "s"), ("a", "b", "d")]:
        out.append(Entry(
            f"or_elim_{a}{b}{c}", fam,
            f"({a} {b} {c} : Prop) (h : {a} ∨ {b}) (hp : {a} → {c}) (hq : {b} → {c}) : {c}",
            _state([f"{a} {b} {c} : Prop", f"h : {a} ∨ {b}", f"hp : {a} → {c}", f"hq : {b} → {c}"],
                   f"{c}"),
            correct, wrong, difficulty="hard", requires_multistep=True,
        ))
    return out


def fam_or_self_hard() -> List[Entry]:
    fam = "or_self_elim"  # same family label as basic (adversarial-sibling friendly)
    correct = (
        "cases h with\n  | inl hp => exact hp\n  | inr hp => exact hp",
        "rcases h with hp | hp\n  exact hp\n  exact hp",
    )
    wrong = ("exact h", "exact h.1", "cases h with\n  | inl hp => exact hp")
    out: List[Entry] = []
    for v in ("p", "q", "r", "s", "u"):
        out.append(Entry(
            f"or_self_hard_{v}", fam,
            f"({v} : Prop) (h : {v} ∨ {v}) : {v}",
            _state([f"{v} : Prop", f"h : {v} ∨ {v}"], f"{v}"),
            correct, wrong, difficulty="hard", requires_multistep=True,
        ))
    return out


# ---------------- 4. iff chains and directionality ----------------


def fam_iff_chain() -> List[Entry]:
    fam = "iff_chain"
    correct = ("intro hp\n  exact h2.mp (h1.mp hp)", "exact fun hp => h2.mp (h1.mp hp)")
    wrong = ("intro hp\n  exact h1.mp hp", "exact h1.mp", "intro hp\n  exact h2.mpr (h1.mpr hp)")
    out: List[Entry] = []
    for a, b, c in [("p", "q", "r"), ("a", "b", "c"), ("x", "y", "z"),
                    ("p", "q", "s"), ("a", "b", "d")]:
        out.append(Entry(
            f"iff_chain_{a}{b}{c}", fam,
            f"({a} {b} {c} : Prop) (h1 : {a} ↔ {b}) (h2 : {b} ↔ {c}) : {a} → {c}",
            _state([f"{a} {b} {c} : Prop", f"h1 : {a} ↔ {b}", f"h2 : {b} ↔ {c}"], f"{a} → {c}"),
            correct, wrong, difficulty="hard", requires_multistep=True,
        ))
    return out


def fam_iff_flip() -> List[Entry]:
    fam = "iff_flip"
    correct = ("intro hq\n  exact h.mpr hq", "exact h.mpr", "exact fun hq => h.mpr hq")
    wrong = ("intro hq\n  exact h.mp hq", "exact h.mp", "exact h")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("x", "y"), ("p", "r"), ("q", "t"), ("a", "c")]:
        out.append(Entry(
            f"iff_flip_{a}{b}", fam,
            f"({a} {b} : Prop) (h : {a} ↔ {b}) : {b} → {a}",
            _state([f"{a} {b} : Prop", f"h : {a} ↔ {b}"], f"{b} → {a}"),
            correct, wrong, difficulty="medium", requires_multistep=True,
        ))
    return out


def fam_iff_apply() -> List[Entry]:
    fam = "iff_apply"
    correct = ("exact h.mp hp", "exact h.1 hp")
    wrong = ("exact h.mpr hp", "exact hp", "exact h")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("x", "y"), ("p", "r"), ("q", "t"), ("a", "c")]:
        out.append(Entry(
            f"iff_apply_{a}{b}", fam,
            f"({a} {b} : Prop) (h : {a} ↔ {b}) (hp : {a}) : {b}",
            _state([f"{a} {b} : Prop", f"h : {a} ↔ {b}", f"hp : {a}"], f"{b}"),
            correct, wrong, difficulty="medium",
        ))
    return out


# ---------------- 5. equality trans / symm combinations ----------------


def fam_eq_chain3() -> List[Entry]:
    fam = "eq_chain3"
    correct = ("exact h1.trans (h2.trans h3)", "exact (h1.trans h2).trans h3",
               "exact Eq.trans h1 (Eq.trans h2 h3)")
    wrong = ("exact h1.trans h2", "exact h1", "exact h3")
    out: List[Entry] = []
    for ty in ("Nat", "Bool"):
        out.append(Entry(
            f"eq_chain3_{ty.lower()}", fam,
            f"(a b c d : {ty}) (h1 : a = b) (h2 : b = c) (h3 : c = d) : a = d",
            _state([f"a b c d : {ty}", "h1 : a = b", "h2 : b = c", "h3 : c = d"], "a = d"),
            correct, wrong, difficulty="hard", requires_multistep=True,
        ))
    for tv in ("α", "β", "γ"):
        nm = {"α": "alpha", "β": "beta", "γ": "gamma"}[tv]
        out.append(Entry(
            f"eq_chain3_{nm}", fam,
            f"({tv} : Type) (a b c d : {tv}) (h1 : a = b) (h2 : b = c) (h3 : c = d) : a = d",
            _state([f"{tv} : Type", f"a b c d : {tv}", "h1 : a = b", "h2 : b = c", "h3 : c = d"],
                   "a = d"),
            correct, wrong, difficulty="hard", requires_multistep=True,
        ))
    return out


def fam_eq_symm_trans() -> List[Entry]:
    fam = "eq_symm_trans"
    correct = ("exact h1.trans h2.symm", "exact Eq.trans h1 (Eq.symm h2)")
    wrong = ("exact h1.trans h2", "exact h1", "exact h2.symm")
    out: List[Entry] = []
    for ty in ("Nat", "Bool"):
        out.append(Entry(
            f"eq_symm_trans_{ty.lower()}", fam,
            f"(a b c : {ty}) (h1 : a = b) (h2 : c = b) : a = c",
            _state([f"a b c : {ty}", "h1 : a = b", "h2 : c = b"], "a = c"),
            correct, wrong, difficulty="hard", requires_multistep=True,
        ))
    for tv in ("α", "β", "γ"):
        nm = {"α": "alpha", "β": "beta", "γ": "gamma"}[tv]
        out.append(Entry(
            f"eq_symm_trans_{nm}", fam,
            f"({tv} : Type) (a b c : {tv}) (h1 : a = b) (h2 : c = b) : a = c",
            _state([f"{tv} : Type", f"a b c : {tv}", "h1 : a = b", "h2 : c = b"], "a = c"),
            correct, wrong, difficulty="hard", requires_multistep=True,
        ))
    return out


# ---------------- 6. exists witness with copied / unseen literals ----------------


def fam_exists_copy() -> List[Entry]:
    fam = "exists_witness"  # same label as basic (sibling-friendly)
    out: List[Entry] = []
    # unseen / larger literals (basic corpus only had 0,1,2,5,7)
    for k in (3, 4, 6, 8, 9, 10, 13, 42, 100):
        out.append(Entry(
            f"exists_hard_nat_{k}", fam,
            f": ∃ n : Nat, n = {k}",
            _state([], f"∃ n : Nat, n = {k}"),
            (f"exact ⟨{k}, rfl⟩", f"refine ⟨{k}, ?_⟩\n  rfl"),
            ("exact ⟨0, rfl⟩", "rfl", "exact rfl"),
            difficulty="medium", requires_copy=True,
        ))
    # witness copied from a hypothesis literal/binder
    for k in (3, 8, 12):
        out.append(Entry(
            f"exists_hyp_copy_{k}", fam,
            f"(m : Nat) (h : m = {k}) : ∃ n : Nat, n = m",
            _state([f"m : Nat", f"h : m = {k}"], "∃ n : Nat, n = m"),
            ("exact ⟨m, rfl⟩", "refine ⟨m, ?_⟩\n  rfl"),
            (f"exact ⟨{k}, rfl⟩", "exact ⟨0, rfl⟩", "rfl"),
            difficulty="hard", requires_copy=True, requires_structure=True,
        ))
    return out


HARD_FAMILY_BUILDERS = (
    fam_imp_chain3, fam_imp_uncurry, fam_imp_chain_mixed,
    fam_nested_and_elim_r, fam_nested_and_elim_l, fam_nested_and_intro,
    fam_or_elim, fam_or_self_hard,
    fam_iff_chain, fam_iff_flip, fam_iff_apply,
    fam_eq_chain3, fam_eq_symm_trans,
    fam_exists_copy,
)


def all_entries() -> List[Entry]:
    out: List[Entry] = []
    seen: set = set()
    for build in HARD_FAMILY_BUILDERS:
        for e in build():
            if e.name in seen:
                raise ValueError(f"duplicate theorem name: {e.name}")
            seen.add(e.name)
            out.append(e)
    return out


# ---------------- emission ----------------


def _meta(e: Entry) -> dict:
    return {
        "pattern_family": e.pattern_family,
        "difficulty": e.difficulty,
        "requires_multistep": e.requires_multistep,
        "requires_copy": e.requires_copy,
        "requires_structure": e.requires_structure,
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


def write_corpus(
    seeds_path: Path, candidates_path: Path, *, entries: Optional[Sequence[Entry]] = None
) -> Tuple[int, int]:
    rows = list(entries) if entries is not None else all_entries()
    seeds_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.parent.mkdir(parents=True, exist_ok=True)

    with seeds_path.open("w", encoding="utf-8") as fh:
        fh.write("# Generated by scripts/generate_hard_corpus.py. Do not edit by hand.\n")
        fh.write(f"# {len(rows)} harder core-Lean theorems (no Mathlib): compositional / multi-step.\n")
        for e in rows:
            fh.write(json.dumps(_seed_row(e), ensure_ascii=False, sort_keys=True) + "\n")

    n_cands = 0
    with candidates_path.open("w", encoding="utf-8") as fh:
        fh.write("# Generated by scripts/generate_hard_corpus.py. Do not edit by hand.\n")
        fh.write("# Candidates keyed by (theorem_name, state_before == seed.initial_state).\n")
        for e in rows:
            fh.write(json.dumps(_candidate_row(e), ensure_ascii=False, sort_keys=True) + "\n")
            n_cands += len(e.candidates)
    return len(rows), n_cands


def _parse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--seeds-out", type=Path, default=Path("data/seeds/hard_lean_seeds.jsonl"))
    p.add_argument("--candidates-out", type=Path,
                   default=Path("data/manual/hard_lean_candidates.jsonl"))
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse().parse_args(argv)
    entries = all_entries()
    n_seeds, n_cands = write_corpus(args.seeds_out, args.candidates_out, entries=entries)
    fams = Counter(e.pattern_family for e in entries)
    diffs = Counter(e.difficulty for e in entries)
    print(f"wrote {n_seeds} seeds -> {args.seeds_out}")
    print(f"wrote {n_cands} candidate tactics -> {args.candidates_out}")
    print(f"{len(fams)} pattern families:")
    for fam, n in sorted(fams.items()):
        print(f"  {fam:20s} {n}")
    print(f"difficulty: {dict(sorted(diffs.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
