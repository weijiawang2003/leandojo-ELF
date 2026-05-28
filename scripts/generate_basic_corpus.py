"""Single-source-of-truth generator for the *basic Lean* theorem-level corpus.

Emits two JSONL files from one structured list of :class:`Entry`:

  data/seeds/basic_lean_seeds.jsonl       - LeanCliRunner seeds (template + initial_state)
  data/manual/basic_lean_candidates.jsonl - ManualFileLLMClient candidates

Why a generator (not hand-written JSONL): the candidate ``state_before`` must
match the seed ``initial_state`` exactly (the manual-file client demands an
exact (name, state) match), and at ~140 theorems hand-maintenance drifts.

Design for baseline transfer
----------------------------
The previous 43-theorem corpus had mostly one-of-a-kind proof patterns, so the
theorem-level split isolated every pattern into val/test and the retrieval
baseline had nothing to transfer from (0% pass@k). This version groups
theorems into **pattern families** with >=5 variants each. Within a family we
keep the *hypothesis names constant* (``h``, ``hp``, ``hq``, ``h1``, ``h2``)
and vary only the Prop/type names, so the correct tactic STRING is identical
across variants. After a by-theorem split, most families have representatives
in both train and eval, and the train tactic is exactly what the eval theorem
needs — that is the transfer signal the retrieval baseline is meant to exploit.

Each :class:`Entry` carries ``pattern_family`` and ``correct`` / ``wrong``
candidate lists. ``correct`` are the intended-to-typecheck tactics (also
emitted as ``expected_success_tactics`` metadata); ``wrong`` are near-misses +
generic-wrong tactics kept on purpose so the failed-out stream stays useful for
audit-quality work. Only core Lean 4 (no Mathlib).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Entry:
    name: str
    pattern_family: str
    statement_fragment: str       # the bit between 'example ' and ':=' in the template
    initial_state: str            # conventional pp; also the candidate match key
    correct: Tuple[str, ...]      # intended-to-typecheck tactics
    wrong: Tuple[str, ...] = ()   # near-miss + generic-wrong tactics

    @property
    def candidates(self) -> List[str]:
        # correct first, then wrong; dedup preserving order.
        out: List[str] = []
        for t in (*self.correct, *self.wrong):
            if t not in out:
                out.append(t)
        return out


def _state(hyps: Sequence[str], goal: str) -> str:
    return "\n".join([*hyps, f"⊢ {goal}"])


# ---------------- families ----------------
# Each builder returns a list of Entry. Hypothesis names are constant within a
# family; only the Prop/type names vary, so `correct` tactics are shared.


def fam_imp_identity() -> List[Entry]:
    fam = "imp_identity"
    correct = ("intro h\n  exact h", "exact fun h => h", "exact id")
    wrong = ("rfl",)
    out: List[Entry] = []
    for v in ("p", "q", "r", "s", "t", "a"):
        out.append(Entry(
            f"imp_id_{v}", fam, f"({v} : Prop) : {v} → {v}",
            _state([f"{v} : Prop"], f"{v} → {v}"), correct, wrong,
        ))
    out.append(Entry(
        "imp_id_and", fam, "(p q : Prop) : (p ∧ q) → (p ∧ q)",
        _state(["p q : Prop"], "p ∧ q → p ∧ q"), correct, wrong,
    ))
    out.append(Entry(
        "imp_id_or", fam, "(p q : Prop) : (p ∨ q) → (p ∨ q)",
        _state(["p q : Prop"], "p ∨ q → p ∨ q"), correct, wrong,
    ))
    return out


def fam_imp_compose() -> List[Entry]:
    fam = "imp_compose"
    correct = ("intro hp\n  exact h2 (h1 hp)", "exact fun hp => h2 (h1 hp)")
    wrong = ("exact h2", "exact h1", "rfl")
    out: List[Entry] = []
    triples = [("p", "q", "r"), ("a", "b", "c"), ("x", "y", "z"),
               ("p", "r", "s"), ("q", "r", "t"), ("a", "c", "d")]
    for a, b, c in triples:
        out.append(Entry(
            f"imp_compose_{a}{b}{c}", fam,
            f"({a} {b} {c} : Prop) (h1 : {a} → {b}) (h2 : {b} → {c}) : {a} → {c}",
            _state([f"{a} {b} {c} : Prop", f"h1 : {a} → {b}", f"h2 : {b} → {c}"], f"{a} → {c}"),
            correct, wrong,
        ))
    return out


def fam_modus_ponens() -> List[Entry]:
    fam = "modus_ponens"
    correct = ("exact hpq hp", "apply hpq\n  exact hp")
    wrong = ("exact hp", "exact hpq", "rfl")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("r", "s"), ("x", "y"), ("p", "r"), ("q", "t")]:
        out.append(Entry(
            f"mp_{a}{b}", fam,
            f"({a} {b} : Prop) (hp : {a}) (hpq : {a} → {b}) : {b}",
            _state([f"{a} {b} : Prop", f"hp : {a}", f"hpq : {a} → {b}"], f"{b}"),
            correct, wrong,
        ))
    return out


def fam_and_intro() -> List[Entry]:
    fam = "and_intro"
    correct = ("exact ⟨hp, hq⟩", "exact And.intro hp hq", "constructor\n  exact hp\n  exact hq")
    wrong = ("exact ⟨hq, hp⟩", "rfl")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("r", "s"), ("x", "y"), ("p", "r"), ("q", "s")]:
        out.append(Entry(
            f"and_intro_{a}{b}", fam,
            f"({a} {b} : Prop) (hp : {a}) (hq : {b}) : {a} ∧ {b}",
            _state([f"{a} {b} : Prop", f"hp : {a}", f"hq : {b}"], f"{a} ∧ {b}"),
            correct, wrong,
        ))
    out.append(Entry(
        "and_intro_nested", fam,
        "(p q r : Prop) (hp : p) (hq : q ∧ r) : p ∧ (q ∧ r)",
        _state(["p q r : Prop", "hp : p", "hq : q ∧ r"], "p ∧ (q ∧ r)"),
        ("exact ⟨hp, hq⟩", "exact And.intro hp hq"), ("exact ⟨hq, hp⟩", "rfl"),
    ))
    return out


def fam_and_elim_left() -> List[Entry]:
    fam = "and_elim_left"
    correct = ("exact h.1", "exact h.left", "exact And.left h")
    wrong = ("exact h.2", "rfl")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("r", "s"), ("x", "y"), ("p", "r"), ("q", "t"), ("s", "u")]:
        out.append(Entry(
            f"and_left_{a}{b}", fam,
            f"({a} {b} : Prop) (h : {a} ∧ {b}) : {a}",
            _state([f"{a} {b} : Prop", f"h : {a} ∧ {b}"], f"{a}"), correct, wrong,
        ))
    return out


def fam_and_elim_right() -> List[Entry]:
    fam = "and_elim_right"
    correct = ("exact h.2", "exact h.right", "exact And.right h")
    wrong = ("exact h.1", "rfl")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("r", "s"), ("x", "y"), ("p", "r"), ("q", "t"), ("s", "u")]:
        out.append(Entry(
            f"and_right_{a}{b}", fam,
            f"({a} {b} : Prop) (h : {a} ∧ {b}) : {b}",
            _state([f"{a} {b} : Prop", f"h : {a} ∧ {b}"], f"{b}"), correct, wrong,
        ))
    return out


def fam_and_comm() -> List[Entry]:
    fam = "and_comm"
    correct = (
        "exact ⟨h.2, h.1⟩",
        "rcases h with ⟨hp, hq⟩\n  exact ⟨hq, hp⟩",
        "cases h with\n  | intro hp hq => exact ⟨hq, hp⟩",
    )
    wrong = ("exact h", "rfl")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("r", "s"), ("x", "y"), ("p", "r"), ("q", "t")]:
        out.append(Entry(
            f"and_comm_{a}{b}", fam,
            f"({a} {b} : Prop) (h : {a} ∧ {b}) : {b} ∧ {a}",
            _state([f"{a} {b} : Prop", f"h : {a} ∧ {b}"], f"{b} ∧ {a}"), correct, wrong,
        ))
    return out


def fam_or_intro_left() -> List[Entry]:
    fam = "or_intro_left"
    correct = ("exact Or.inl h", "left\n  exact h")
    wrong = ("exact Or.inr h", "exact h", "rfl")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("r", "s"), ("x", "y"), ("p", "r"), ("q", "t"), ("s", "u")]:
        out.append(Entry(
            f"or_inl_{a}{b}", fam,
            f"({a} {b} : Prop) (h : {a}) : {a} ∨ {b}",
            _state([f"{a} {b} : Prop", f"h : {a}"], f"{a} ∨ {b}"), correct, wrong,
        ))
    return out


def fam_or_intro_right() -> List[Entry]:
    fam = "or_intro_right"
    correct = ("exact Or.inr h", "right\n  exact h")
    wrong = ("exact Or.inl h", "exact h", "rfl")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("r", "s"), ("x", "y"), ("p", "r"), ("q", "t"), ("s", "u")]:
        out.append(Entry(
            f"or_inr_{a}{b}", fam,
            f"({a} {b} : Prop) (h : {b}) : {a} ∨ {b}",
            _state([f"{a} {b} : Prop", f"h : {b}"], f"{a} ∨ {b}"), correct, wrong,
        ))
    return out


def fam_or_comm() -> List[Entry]:
    fam = "or_comm"
    correct = (
        "rcases h with hp | hq\n  exact Or.inr hp\n  exact Or.inl hq",
        "cases h with\n  | inl hp => exact Or.inr hp\n  | inr hq => exact Or.inl hq",
    )
    wrong = ("exact h", "rfl")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("r", "s"), ("x", "y"), ("p", "r")]:
        out.append(Entry(
            f"or_comm_{a}{b}", fam,
            f"({a} {b} : Prop) (h : {a} ∨ {b}) : {b} ∨ {a}",
            _state([f"{a} {b} : Prop", f"h : {a} ∨ {b}"], f"{b} ∨ {a}"), correct, wrong,
        ))
    return out


def fam_or_self_elim() -> List[Entry]:
    fam = "or_self_elim"
    correct = (
        "rcases h with hp | hp\n  exact hp\n  exact hp",
        "cases h with\n  | inl hp => exact hp\n  | inr hp => exact hp",
    )
    wrong = ("exact h", "rfl")
    out: List[Entry] = []
    for v in ("p", "q", "r", "s", "t"):
        out.append(Entry(
            f"or_self_{v}", fam,
            f"({v} : Prop) (h : {v} ∨ {v}) : {v}",
            _state([f"{v} : Prop", f"h : {v} ∨ {v}"], f"{v}"), correct, wrong,
        ))
    return out


def fam_iff_intro() -> List[Entry]:
    fam = "iff_intro"
    correct = ("exact ⟨h1, h2⟩", "exact Iff.intro h1 h2", "constructor\n  exact h1\n  exact h2")
    wrong = ("exact ⟨h2, h1⟩", "rfl")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("r", "s"), ("x", "y"), ("p", "r"), ("q", "t")]:
        out.append(Entry(
            f"iff_intro_{a}{b}", fam,
            f"({a} {b} : Prop) (h1 : {a} → {b}) (h2 : {b} → {a}) : {a} ↔ {b}",
            _state([f"{a} {b} : Prop", f"h1 : {a} → {b}", f"h2 : {b} → {a}"], f"{a} ↔ {b}"),
            correct, wrong,
        ))
    return out


def fam_iff_mp() -> List[Entry]:
    fam = "iff_mp"
    correct = ("exact h.mp hp", "exact h.1 hp")
    wrong = ("exact h.mpr hp", "exact hp", "rfl")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("r", "s"), ("x", "y"), ("p", "r"), ("q", "t")]:
        out.append(Entry(
            f"iff_mp_{a}{b}", fam,
            f"({a} {b} : Prop) (h : {a} ↔ {b}) (hp : {a}) : {b}",
            _state([f"{a} {b} : Prop", f"h : {a} ↔ {b}", f"hp : {a}"], f"{b}"), correct, wrong,
        ))
    return out


def fam_iff_mpr() -> List[Entry]:
    fam = "iff_mpr"
    correct = ("exact h.mpr hq", "exact h.2 hq")
    wrong = ("exact h.mp hq", "exact hq", "rfl")
    out: List[Entry] = []
    for a, b in [("p", "q"), ("a", "b"), ("r", "s"), ("x", "y"), ("p", "r"), ("q", "t")]:
        out.append(Entry(
            f"iff_mpr_{a}{b}", fam,
            f"({a} {b} : Prop) (h : {a} ↔ {b}) (hq : {b}) : {a}",
            _state([f"{a} {b} : Prop", f"h : {a} ↔ {b}", f"hq : {b}"], f"{a}"), correct, wrong,
        ))
    return out


def fam_eq_refl() -> List[Entry]:
    fam = "eq_refl"
    correct = ("rfl", "exact rfl", "exact Eq.refl a")
    wrong = ("exact a",)
    out: List[Entry] = []
    for ty in ("Nat", "Bool", "String"):
        out.append(Entry(
            f"eq_refl_{ty.lower()}", fam,
            f"(a : {ty}) : a = a",
            _state([f"a : {ty}"], "a = a"), correct, wrong,
        ))
    # polymorphic
    for tv in ("α", "β"):
        out.append(Entry(
            f"eq_refl_{'alpha' if tv == 'α' else 'beta'}", fam,
            f"({tv} : Type) (a : {tv}) : a = a",
            _state([f"{tv} : Type", f"a : {tv}"], "a = a"), correct, wrong,
        ))
    # two-binder (still a = a)
    out.append(Entry(
        "eq_refl_pair", fam,
        "(α : Type) (a b : α) : a = a",
        _state(["α : Type", "a b : α"], "a = a"), correct, wrong,
    ))
    return out


def fam_eq_symm() -> List[Entry]:
    fam = "eq_symm"
    correct = ("exact h.symm", "exact Eq.symm h")
    wrong = ("exact h", "rfl")
    out: List[Entry] = []
    for ty in ("Nat", "Bool", "String"):
        out.append(Entry(
            f"eq_symm_{ty.lower()}", fam,
            f"(a b : {ty}) (h : a = b) : b = a",
            _state([f"a b : {ty}", "h : a = b"], "b = a"), correct, wrong,
        ))
    for tv in ("α", "β", "γ"):
        nm = {"α": "alpha", "β": "beta", "γ": "gamma"}[tv]
        out.append(Entry(
            f"eq_symm_{nm}", fam,
            f"({tv} : Type) (a b : {tv}) (h : a = b) : b = a",
            _state([f"{tv} : Type", f"a b : {tv}", "h : a = b"], "b = a"), correct, wrong,
        ))
    return out


def fam_eq_trans() -> List[Entry]:
    fam = "eq_trans"
    correct = ("exact h1.trans h2", "exact Eq.trans h1 h2")
    wrong = ("exact h1", "exact h2", "rfl")
    out: List[Entry] = []
    for ty in ("Nat", "Bool", "String"):
        out.append(Entry(
            f"eq_trans_{ty.lower()}", fam,
            f"(a b c : {ty}) (h1 : a = b) (h2 : b = c) : a = c",
            _state([f"a b c : {ty}", "h1 : a = b", "h2 : b = c"], "a = c"), correct, wrong,
        ))
    for tv in ("α", "β", "γ"):
        nm = {"α": "alpha", "β": "beta", "γ": "gamma"}[tv]
        out.append(Entry(
            f"eq_trans_{nm}", fam,
            f"({tv} : Type) (a b c : {tv}) (h1 : a = b) (h2 : b = c) : a = c",
            _state([f"{tv} : Type", f"a b c : {tv}", "h1 : a = b", "h2 : b = c"], "a = c"),
            correct, wrong,
        ))
    return out


def fam_nat_rfl() -> List[Entry]:
    fam = "nat_rfl"
    correct = ("rfl", "exact rfl", "decide")
    wrong = ("exact 0",)
    out: List[Entry] = []
    exprs = [
        ("nat_lit2", "(2 : Nat) = 2", "2 = 2"),
        ("nat_lit5", "(5 : Nat) = 5", "5 = 5"),
        ("nat_lit10", "(10 : Nat) = 10", "10 = 10"),
        ("nat_add11", "(1 + 1 : Nat) = 2", "1 + 1 = 2"),
        ("nat_add23", "(2 + 3 : Nat) = 5", "2 + 3 = 5"),
        ("nat_add40", "(4 + 0 : Nat) = 4", "4 + 0 = 4"),
        ("nat_mul23", "(2 * 3 : Nat) = 6", "2 * 3 = 6"),
        ("nat_succ", "(Nat.succ 2) = 3", "Nat.succ 2 = 3"),
        ("nat_add_chain", "(1 + 2 + 3 : Nat) = 6", "1 + 2 + 3 = 6"),
    ]
    for name, frag, goal in exprs:
        out.append(Entry(name, fam, f": {frag}", _state([], goal), correct, wrong))
    return out


def fam_exists_witness() -> List[Entry]:
    fam = "exists_witness"
    out: List[Entry] = []
    # ∃ n : Nat, n = k  -> ⟨k, rfl⟩
    for k in (0, 1, 2, 5, 7):
        out.append(Entry(
            f"exists_nat_{k}", fam,
            f": ∃ n : Nat, n = {k}",
            _state([], f"∃ n : Nat, n = {k}"),
            (f"exact ⟨{k}, rfl⟩", f"refine ⟨{k}, ?_⟩\n  rfl"),
            ("exact rfl", "rfl"),
        ))
    # ∃ x : α, x = a  -> ⟨a, rfl⟩
    for tv in ("α", "β"):
        nm = {"α": "alpha", "β": "beta"}[tv]
        out.append(Entry(
            f"exists_self_{nm}", fam,
            f"({tv} : Type) (a : {tv}) : ∃ x : {tv}, x = a",
            _state([f"{tv} : Type", f"a : {tv}"], f"∃ x : {tv}, x = a"),
            ("exact ⟨a, rfl⟩", "refine ⟨a, ?_⟩\n  rfl"),
            ("exact a", "rfl"),
        ))
    out.append(Entry(
        "exists_nat_refl", fam, ": ∃ n : Nat, n = n",
        _state([], "∃ n : Nat, n = n"),
        ("exact ⟨0, rfl⟩", "exact ⟨1, rfl⟩"), ("rfl",),
    ))
    return out


def fam_false_elim() -> List[Entry]:
    fam = "false_elim"
    correct = ("exact h.elim", "exact False.elim h", "contradiction")
    wrong = ("exact h", "rfl")
    out: List[Entry] = []
    for v in ("p", "q", "r", "s", "t"):
        out.append(Entry(
            f"false_elim_{v}", fam,
            f"({v} : Prop) (h : False) : {v}",
            _state([f"{v} : Prop", "h : False"], f"{v}"), correct, wrong,
        ))
    return out


def fam_true_intro() -> List[Entry]:
    fam = "true_intro"
    correct = ("trivial", "exact True.intro", "constructor")
    wrong = ("rfl",)
    out: List[Entry] = []
    out.append(Entry("true_bare", fam, ": True", _state([], "True"), correct, wrong))
    for v in ("p", "q", "r", "s"):
        out.append(Entry(
            f"true_const_{v}", fam,
            f"({v} : Prop) (h : {v}) : True",
            _state([f"{v} : Prop", f"h : {v}"], "True"),
            ("trivial", "exact True.intro"), ("exact h", "rfl"),
        ))
    return out


FAMILY_BUILDERS = (
    fam_imp_identity, fam_imp_compose, fam_modus_ponens,
    fam_and_intro, fam_and_elim_left, fam_and_elim_right, fam_and_comm,
    fam_or_intro_left, fam_or_intro_right, fam_or_comm, fam_or_self_elim,
    fam_iff_intro, fam_iff_mp, fam_iff_mpr,
    fam_eq_refl, fam_eq_symm, fam_eq_trans,
    fam_nat_rfl, fam_exists_witness, fam_false_elim, fam_true_intro,
)


def all_entries() -> List[Entry]:
    out: List[Entry] = []
    seen: set = set()
    for build in FAMILY_BUILDERS:
        for e in build():
            if e.name in seen:
                raise ValueError(f"duplicate theorem name: {e.name}")
            seen.add(e.name)
            out.append(e)
    return out


# ---------------- emission ----------------


def _seed_row(e: Entry) -> dict:
    return {
        "theorem_name": e.name,
        "theorem_statement": e.statement_fragment,
        "initial_state": e.initial_state,
        "imports": [],
        "template": f"example {e.statement_fragment} := by\n  __TACTIC__",
        "placeholder": "__TACTIC__",
        "metadata": {
            "pattern_family": e.pattern_family,
            "expected_success_tactics": list(e.correct),
        },
    }


def _candidate_row(e: Entry) -> dict:
    return {
        "theorem_name": e.name,
        "state_before": e.initial_state,
        "candidates": e.candidates,
        "source": "manual-corpus",
        "prompt_style": "diverse",
        "metadata": {
            "pattern_family": e.pattern_family,
            "expected_success_tactics": list(e.correct),
        },
    }


def write_corpus(
    seeds_path: Path, candidates_path: Path, *, entries: Optional[Sequence[Entry]] = None
) -> Tuple[int, int]:
    rows = list(entries) if entries is not None else all_entries()
    seeds_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.parent.mkdir(parents=True, exist_ok=True)

    with seeds_path.open("w", encoding="utf-8") as fh:
        fh.write("# Generated by scripts/generate_basic_corpus.py. Do not edit by hand.\n")
        fh.write(f"# {len(rows)} tiny core-Lean theorems (no Mathlib) in pattern families.\n")
        for e in rows:
            fh.write(json.dumps(_seed_row(e), ensure_ascii=False, sort_keys=True) + "\n")

    n_cands = 0
    with candidates_path.open("w", encoding="utf-8") as fh:
        fh.write("# Generated by scripts/generate_basic_corpus.py. Do not edit by hand.\n")
        fh.write("# Candidates keyed by (theorem_name, state_before); state_before MUST\n")
        fh.write("# match the seed's initial_state for the manual-file client to match.\n")
        for e in rows:
            fh.write(json.dumps(_candidate_row(e), ensure_ascii=False, sort_keys=True) + "\n")
            n_cands += len(e.candidates)
    return len(rows), n_cands


def _parse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--seeds-out", type=Path, default=Path("data/seeds/basic_lean_seeds.jsonl"))
    p.add_argument("--candidates-out", type=Path,
                   default=Path("data/manual/basic_lean_candidates.jsonl"))
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse().parse_args(argv)
    entries = all_entries()
    n_seeds, n_cands = write_corpus(args.seeds_out, args.candidates_out, entries=entries)
    from collections import Counter
    fams = Counter(e.pattern_family for e in entries)
    print(f"wrote {n_seeds} seeds -> {args.seeds_out}")
    print(f"wrote {n_cands} candidate tactics -> {args.candidates_out}")
    print(f"{len(fams)} pattern families:")
    for fam, n in sorted(fams.items()):
        print(f"  {fam:18s} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
