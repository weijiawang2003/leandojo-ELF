"""Mini-ELF v10 — operation×surface-family redundancy corpus generator.

Builds a verified theorem corpus where each *proof operation* appears in
**multiple distinct surface families** (different variable names, proposition
names, hypothesis order, and theorem statements, but the same closing tactic
shape). This is the corpus the v8 retrospective identified as the missing
ingredient: when a held-out family/operation has *no* shape-compatible token
cousin in train, the seq2seq stays at 0.000; when sibling-family tokens *are*
present, it generalises (the v8 ``operation_holdout/intro_negation``
``cross_operation_verified = 3`` result). v10 tests the *data scaling*
hypothesis at corpus shape, not at architecture.

Output (default — ``--full``)::

    data/seeds/redundancy_seeds.jsonl
    data/manual/redundancy_candidates.jsonl

The downstream collect_traces / build_dataset / split scripts read these
files unchanged (they share the v6/v7/v8 row schema). **Every emitted
tactic is verified against the lean-cli verifier before commit**; a cell
that fails verification is *not* written and is reported in the run summary.
There is no fake corpus.

Honest scope this commit:
  * **No Mathlib imports** — every theorem typechecks in pure Lean 4 / Init.
  * **No state_after** is emitted; this corpus is theorem-level only.
  * Tactics use core-Lean idioms only (``exact``, ``rw``, ``cases``,
    ``intro``, ``rfl``). ``rcases``/``obtain`` are intentionally avoided.
  * Theorem names are namespaced ``v10_<operation>_<family>_<suffix>`` so
    no prior basic/hard/PB/v9 seed overlaps.

CLI::

    ./.venv/bin/python scripts/generate_redundancy_corpus.py [--rebuild]

The script is deterministic; rerunning with the same DESIGN table reproduces
byte-identical output.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mini_elf_lean.baseline_eval import (  # noqa: E402
    VerificationCache, make_lean_cli_verifier,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_redundancy_corpus")


# --------------------------------------------------------------------------- #
# Design table — 8 operations × ~5 surface families
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Cell:
    operation: str            # the v8 required_operation label
    surface_family: str       # this cell's pattern_family
    theorem_suffix: str       # appended to "v10_<op>_<family>" -> theorem_name
    theorem_statement: str    # `theorem ... :=` header (no `by`)
    state_before: str         # the lean tactic-state we feed to the model
    tactic: str               # the closing tactic — verified before commit
    requires_intro: bool = False
    requires_rewrite: bool = False
    requires_quantifier: bool = False
    requires_exists_elim: bool = False
    difficulty: str = "medium"


# Helper: build a Cell with all `requires_*` flags inferred from the operation,
# overridable per-cell. Each operation declares its default flag-set; per-cell
# overrides are accepted via kwargs.
_OP_DEFAULT_FLAGS: Dict[str, Dict[str, bool]] = {
    "contradiction": {},
    "intro_negation":
        {"requires_intro": True},
    "instantiate_forall":
        {"requires_quantifier": True},
    "rewrite_eq":
        {"requires_rewrite": True},
    "exists_elim":
        {"requires_exists_elim": True},
    "implication_chain":
        {"requires_intro": True},        # most chain cells need intro for hypothetical
    "conjunction_projection": {},
    "disjunction_cases": {},
}


def cell(op: str, family: str, suffix: str, statement: str, state: str,
         tactic: str, **flag_overrides: Any) -> Cell:
    flags = dict(_OP_DEFAULT_FLAGS.get(op, {}))
    flags.update(flag_overrides)
    return Cell(operation=op, surface_family=family, theorem_suffix=suffix,
                theorem_statement=statement, state_before=state, tactic=tactic,
                **flags)


# 8 operations × 5 surface families = 40 redundancy cells. Each cell uses a
# *different* variable layout / proposition naming / nesting pattern, but the
# *closing tactic* shape is consistent within the operation. This is the
# redundancy structure v10 tests.
DESIGN: Tuple[Cell, ...] = (
    # ============================================================
    # 1. contradiction — shape: `exact absurd <hp> <hnp>`
    # ============================================================
    cell("contradiction", "exfalso_pq", "_q",
         "(p q : Prop) (hp : p) (hnp : ¬p) : q",
         "p q : Prop\nhp : p\nhnp : ¬p\n⊢ q",
         "exact absurd hp hnp"),
    cell("contradiction", "exfalso_ab", "_b",
         "(a b : Prop) (ha : a) (hna : ¬a) : b",
         "a b : Prop\nha : a\nhna : ¬a\n⊢ b",
         "exact absurd ha hna"),
    cell("contradiction", "exfalso_with_extra", "_r",
         "(p q r : Prop) (hp : p) (hnp : ¬p) (hq : q) : r",
         "p q r : Prop\nhp : p\nhnp : ¬p\nhq : q\n⊢ r",
         "exact absurd hp hnp"),
    cell("contradiction", "arrow_false", "_q",
         "(p q : Prop) (hp : p) (hpf : p → False) : q",
         "p q : Prop\nhp : p\nhpf : p → False\n⊢ q",
         "exact absurd hp hpf"),
    cell("contradiction", "iff_false_mp", "_q",
         "(p q : Prop) (hp : p) (hpf : p ↔ False) : q",
         "p q : Prop\nhp : p\nhpf : p ↔ False\n⊢ q",
         "exact absurd hp hpf.mp"),
    # ============================================================
    # 2. intro_negation — shape: `intro <hp>; exact <hnq> (<h> <hp>)`
    # ============================================================
    cell("intro_negation", "contrapos_pq", "",
         "(p q : Prop) (h : p → q) (hnq : ¬q) : ¬p",
         "p q : Prop\nh : p → q\nhnq : ¬q\n⊢ ¬p",
         "intro hp; exact hnq (h hp)"),
    cell("intro_negation", "contrapos_ab", "",
         "(a b : Prop) (h : a → b) (hnb : ¬b) : ¬a",
         "a b : Prop\nh : a → b\nhnb : ¬b\n⊢ ¬a",
         "intro ha; exact hnb (h ha)"),
    cell("intro_negation", "contrapos_rs", "",
         "(r s : Prop) (h : r → s) (hns : ¬s) : ¬r",
         "r s : Prop\nh : r → s\nhns : ¬s\n⊢ ¬r",
         "intro hr; exact hns (h hr)"),
    cell("intro_negation", "contrapos_chain", "",
         "(p q r : Prop) (h1 : p → q) (h2 : q → r) (hnr : ¬r) : ¬p",
         "p q r : Prop\nh1 : p → q\nh2 : q → r\nhnr : ¬r\n⊢ ¬p",
         "intro hp; exact hnr (h2 (h1 hp))"),
    cell("intro_negation", "contrapos_with_extra", "",
         "(p q s : Prop) (h : p → q) (hnq : ¬q) (hs : s) : ¬p",
         "p q s : Prop\nh : p → q\nhnq : ¬q\nhs : s\n⊢ ¬p",
         "intro hp; exact hnq (h hp)"),
    # ============================================================
    # 3. instantiate_forall — shape: `exact h <args>`
    # ============================================================
    cell("instantiate_forall", "nat_eq_3", "",
         "(h : ∀ n : Nat, n = n) : 3 = 3",
         "h : ∀ n : Nat, n = n\n⊢ 3 = 3",
         "exact h 3"),
    cell("instantiate_forall", "nat_eq_7", "",
         "(h : ∀ k : Nat, k = k) : 7 = 7",
         "h : ∀ k : Nat, k = k\n⊢ 7 = 7",
         "exact h 7"),
    cell("instantiate_forall", "nat_le_5", "",
         "(h : ∀ x : Nat, x ≤ x) : 5 ≤ 5",
         "h : ∀ x : Nat, x ≤ x\n⊢ 5 ≤ 5",
         "exact h 5"),
    cell("instantiate_forall", "nat_add_zero_4", "",
         "(h : ∀ n : Nat, n + 0 = n) : 4 + 0 = 4",
         "h : ∀ n : Nat, n + 0 = n\n⊢ 4 + 0 = 4",
         "exact h 4"),
    cell("instantiate_forall", "prop_self_imp", "",
         "(p : Prop) (h : ∀ q : Prop, q → q) : p → p",
         "p : Prop\nh : ∀ q : Prop, q → q\n⊢ p → p",
         "exact h p"),
    # ============================================================
    # 4. rewrite_eq — shape: `rw [h]` (`rw` auto-rfl closes the goal)
    # ============================================================
    cell("rewrite_eq", "succ_eq", "",
         "(n m : Nat) (h : n = m) : Nat.succ n = Nat.succ m",
         "n m : Nat\nh : n = m\n⊢ Nat.succ n = Nat.succ m",
         "rw [h]"),
    cell("rewrite_eq", "add_zero", "",
         "(a b : Nat) (h : a = b) : a + 0 = b + 0",
         "a b : Nat\nh : a = b\n⊢ a + 0 = b + 0",
         "rw [h]"),
    cell("rewrite_eq", "mul_one", "",
         "(x y : Nat) (h : x = y) : x * 1 = y * 1",
         "x y : Nat\nh : x = y\n⊢ x * 1 = y * 1",
         "rw [h]"),
    cell("rewrite_eq", "swap_under_z", "",
         "(p q : Nat) (h : p = q) (z : Nat) : p + z = q + z",
         "p q : Nat\nh : p = q\nz : Nat\n⊢ p + z = q + z",
         "rw [h]"),
    cell("rewrite_eq", "rev_target", "",
         "(u v : Nat) (h : u = v) : v = u",
         "u v : Nat\nh : u = v\n⊢ v = u",
         "rw [h]"),
    # ============================================================
    # 5. exists_elim — shape: `cases h with | intro n hn => exact <use n hn>`
    # ============================================================
    cell("exists_elim", "reuse_witness_3", "",
         "(h : ∃ n : Nat, n = 3) : ∃ m : Nat, m = 3",
         "h : ∃ n : Nat, n = 3\n⊢ ∃ m : Nat, m = 3",
         "cases h with | intro n hn => exact ⟨n, hn⟩"),
    cell("exists_elim", "reuse_witness_5", "",
         "(h : ∃ n : Nat, n = 5) : ∃ m : Nat, m = 5",
         "h : ∃ n : Nat, n = 5\n⊢ ∃ m : Nat, m = 5",
         "cases h with | intro n hn => exact ⟨n, hn⟩"),
    cell("exists_elim", "reuse_witness_7", "",
         "(h : ∃ n : Nat, n = 7) : ∃ m : Nat, m = 7",
         "h : ∃ n : Nat, n = 7\n⊢ ∃ m : Nat, m = 7",
         "cases h with | intro n hn => exact ⟨n, hn⟩"),
    cell("exists_elim", "drop_witness_prop", "",
         "(p : Prop) (h : ∃ _ : Nat, p) : p",
         "p : Prop\nh : ∃ _ : Nat, p\n⊢ p",
         "cases h with | intro _ hp => exact hp"),
    cell("exists_elim", "reuse_addzero", "",
         "(h : ∃ n : Nat, n + 0 = n) : ∃ m : Nat, m + 0 = m",
         "h : ∃ n : Nat, n + 0 = n\n⊢ ∃ m : Nat, m + 0 = m",
         "cases h with | intro n hn => exact ⟨n, hn⟩"),
    # ============================================================
    # 6. implication_chain — shape: `exact <hi> (... (h1 hp))` or
    #                                `intro <hp>; exact <h2> (h1 hp)`
    # ============================================================
    cell("implication_chain", "two_step_pqr", "",
         "(p q r : Prop) (h1 : p → q) (h2 : q → r) (hp : p) : r",
         "p q r : Prop\nh1 : p → q\nh2 : q → r\nhp : p\n⊢ r",
         "exact h2 (h1 hp)",
         requires_intro=False),
    cell("implication_chain", "two_step_abc", "",
         "(a b c : Prop) (f : a → b) (g : b → c) (ha : a) : c",
         "a b c : Prop\nf : a → b\ng : b → c\nha : a\n⊢ c",
         "exact g (f ha)",
         requires_intro=False),
    cell("implication_chain", "three_step", "",
         "(p q r s : Prop) (h1 : p → q) (h2 : q → r) (h3 : r → s) (hp : p) : s",
         "p q r s : Prop\nh1 : p → q\nh2 : q → r\nh3 : r → s\nhp : p\n⊢ s",
         "exact h3 (h2 (h1 hp))",
         requires_intro=False),
    cell("implication_chain", "two_step_intro", "",
         "(p q r : Prop) (h1 : p → q) (h2 : q → r) : p → r",
         "p q r : Prop\nh1 : p → q\nh2 : q → r\n⊢ p → r",
         "intro hp; exact h2 (h1 hp)"),
    cell("implication_chain", "branch_join", "",
         "(p q r s : Prop) (h1 : p → q) (h2 : p → r) (h3 : q → r → s) (hp : p) : s",
         "p q r s : Prop\nh1 : p → q\nh2 : p → r\nh3 : q → r → s\nhp : p\n⊢ s",
         "exact h3 (h1 hp) (h2 hp)",
         requires_intro=False),
    # ============================================================
    # 7. conjunction_projection — shape: `exact h.left` / `exact h.right`
    # ============================================================
    cell("conjunction_projection", "left_pq", "",
         "(p q : Prop) (h : p ∧ q) : p",
         "p q : Prop\nh : p ∧ q\n⊢ p",
         "exact h.left"),
    cell("conjunction_projection", "left_ab", "",
         "(a b : Prop) (h : a ∧ b) : a",
         "a b : Prop\nh : a ∧ b\n⊢ a",
         "exact h.left"),
    cell("conjunction_projection", "right_xy", "",
         "(x y : Prop) (h : x ∧ y) : y",
         "x y : Prop\nh : x ∧ y\n⊢ y",
         "exact h.right"),
    cell("conjunction_projection", "nested_left_left", "",
         "(p q r : Prop) (h : (p ∧ q) ∧ r) : p",
         "p q r : Prop\nh : (p ∧ q) ∧ r\n⊢ p",
         "exact h.left.left"),
    cell("conjunction_projection", "right_then_left", "",
         "(p q r : Prop) (h : p ∧ q ∧ r) : q",
         "p q r : Prop\nh : p ∧ q ∧ r\n⊢ q",
         "exact h.right.left"),
    # ============================================================
    # 8. disjunction_cases — shape:
    #   `cases h with | inl <name> => <use> | inr <name> => <use>`
    # ============================================================
    cell("disjunction_cases", "or_self", "",
         "(p : Prop) (h : p ∨ p) : p",
         "p : Prop\nh : p ∨ p\n⊢ p",
         "cases h with | inl hp => exact hp | inr hp => exact hp"),
    cell("disjunction_cases", "or_to_via", "",
         "(p q r : Prop) (h : p ∨ q) (f : p → r) (g : q → r) : r",
         "p q r : Prop\nh : p ∨ q\nf : p → r\ng : q → r\n⊢ r",
         "cases h with | inl hp => exact f hp | inr hq => exact g hq"),
    cell("disjunction_cases", "or_swap", "",
         "(a b : Prop) (h : a ∨ b) : b ∨ a",
         "a b : Prop\nh : a ∨ b\n⊢ b ∨ a",
         "cases h with | inl ha => exact Or.inr ha | inr hb => exact Or.inl hb"),
    cell("disjunction_cases", "or_with_false", "",
         "(p : Prop) (h : p ∨ False) : p",
         "p : Prop\nh : p ∨ False\n⊢ p",
         "cases h with | inl hp => exact hp | inr hf => exact hf.elim"),
    cell("disjunction_cases", "or_true_lhs", "",
         "(p : Prop) (h : True ∨ p) : True",
         "p : Prop\nh : True ∨ p\n⊢ True",
         "cases h with | inl ht => exact ht | inr _ => trivial"),
)


# --------------------------------------------------------------------------- #
# Row builders (match the v6/v7/v8 schema so downstream scripts read it unchanged)
# --------------------------------------------------------------------------- #


def theorem_name(c: Cell) -> str:
    return f"v10_{c.operation}_{c.surface_family}{c.theorem_suffix}"


def to_seed_row(c: Cell) -> Dict[str, Any]:
    name = theorem_name(c)
    return {
        "imports": [],
        "initial_state": c.state_before,
        "metadata": {
            "difficulty": c.difficulty,
            "expected_success_tactics": [c.tactic],
            "operation": c.operation,
            "pattern_family": c.surface_family,
            "redundancy_corpus": True,
            "redundancy_group": c.operation,
            "required_operation": c.operation,
            "requires_exists_elim": c.requires_exists_elim,
            "requires_intro": c.requires_intro,
            "requires_quantifier": c.requires_quantifier,
            "requires_rewrite": c.requires_rewrite,
            "source": "redundancy-corpus",
            "surface_family": c.surface_family,
        },
        "placeholder": "__TACTIC__",
        "template": f"example {c.theorem_statement} := by\n  __TACTIC__",
        "theorem_name": name,
        "theorem_statement": c.theorem_statement,
    }


def to_processed_row(c: Cell, *, split: str = "train") -> Dict[str, Any]:
    """Row shape matching the v6/v7/v8 ``next_tactic.jsonl`` schema. The
    initial split label is ``train`` for every cell; the v10 split builder
    (`scripts/build_redundancy_splits.py`) re-assigns it per regime."""
    return {
        "backend": "lean-cli",
        "metadata": {
            "corpus_source": "redundancy_corpus",
            "operation": c.operation,
            "pattern_family": c.surface_family,
            "redundancy_corpus": True,
            "redundancy_group": c.operation,
            "required_operation": c.operation,
            "requires_exists_elim": c.requires_exists_elim,
            "requires_intro": c.requires_intro,
            "requires_quantifier": c.requires_quantifier,
            "requires_rewrite": c.requires_rewrite,
            "surface_family": c.surface_family,
        },
        "num_goals_after": 0,
        "num_goals_before": 1,
        "proof_finished": True,
        "source_record_hash": "",
        "split": split,
        "state_after_is_real": False,   # contract: v10 emits NO state_after
        "state_before": c.state_before,
        "success": True,
        "tactic": c.tactic,
        "theorem_name": theorem_name(c),
        "theorem_statement": c.theorem_statement,
        "verification_quality": "theorem-level",
    }


def to_failed_trace_row(c: Cell, err: str) -> Dict[str, Any]:
    """Trace-style record for a refused cell — written to a *separate* failed
    file so the auditor can see what was rejected without polluting the
    verified set."""
    return {
        "backend": "lean-cli",
        "metadata": {
            "corpus_source": "redundancy_corpus",
            "operation": c.operation,
            "pattern_family": c.surface_family,
            "redundancy_corpus": True,
            "refusal_reason": "lean-cli-failed-or-timeout",
        },
        "state_before": c.state_before,
        "success": False,
        "error": err,
        "tactic": c.tactic,
        "theorem_name": theorem_name(c),
        "theorem_statement": c.theorem_statement,
    }


def to_candidate_row(c: Cell) -> Dict[str, Any]:
    name = theorem_name(c)
    return {
        "candidates": [c.tactic],
        "metadata": {
            "difficulty": c.difficulty,
            "expected_success_tactics": [c.tactic],
            "operation": c.operation,
            "pattern_family": c.surface_family,
            "redundancy_corpus": True,
            "redundancy_group": c.operation,
            "required_operation": c.operation,
            "requires_exists_elim": c.requires_exists_elim,
            "requires_intro": c.requires_intro,
            "requires_quantifier": c.requires_quantifier,
            "requires_rewrite": c.requires_rewrite,
            "surface_family": c.surface_family,
        },
        "prompt_style": "redundancy-corpus",
        "source": "redundancy-corpus",
        "state_before": c.state_before,
        "theorem_name": name,
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds-out",
                    default=str(ROOT / "data" / "seeds" / "redundancy_seeds.jsonl"))
    ap.add_argument("--candidates-out",
                    default=str(ROOT / "data" / "manual" / "redundancy_candidates.jsonl"))
    ap.add_argument("--processed-out",
                    default=str(ROOT / "data" / "processed" / "redundancy_lean_cli"
                                / "next_tactic.jsonl"))
    ap.add_argument("--verified-traces-out",
                    default=str(ROOT / "data" / "traces"
                                / "redundancy_lean_cli_verified.jsonl"))
    ap.add_argument("--failed-traces-out",
                    default=str(ROOT / "data" / "traces"
                                / "redundancy_lean_cli_failed.jsonl"))
    ap.add_argument("--cache",
                    default=str(ROOT / "data" / "lean_cache" / "redundancy_corpus_cache.json"))
    ap.add_argument("--rebuild", action="store_true",
                    help="overwrite existing output files even if they exist")
    ap.add_argument("--no-verify", dest="verify", action="store_false",
                    help="skip lean-cli verification (used only by unit tests)")
    ap.add_argument("--timeout", type=float, default=60.0,
                    help="per-cell lean-cli verification timeout (s)")
    ap.set_defaults(verify=True)
    args = ap.parse_args()

    all_outs = (args.seeds_out, args.candidates_out, args.processed_out,
                args.verified_traces_out, args.failed_traces_out)
    for out in all_outs:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
    if not args.rebuild:
        for out in all_outs:
            if Path(out).exists():
                logger.warning("%s exists — pass --rebuild to overwrite", out)
                return 0

    # Sanity: no duplicate theorem names in DESIGN.
    seen: Dict[str, Cell] = {}
    for c in DESIGN:
        nm = theorem_name(c)
        if nm in seen:
            raise SystemExit(f"DESIGN has duplicate theorem_name {nm!r}")
        seen[nm] = c
    logger.info("DESIGN has %d cells across %d operations",
                len(DESIGN), len({c.operation for c in DESIGN}))

    cache = VerificationCache.load(Path(args.cache), enabled=True) \
        if args.verify else VerificationCache(enabled=False)
    verifier = make_lean_cli_verifier(timeout=args.timeout) if args.verify else None

    verified: List[Cell] = []
    failures: List[Tuple[Cell, str]] = []

    for c in DESIGN:
        if not args.verify:
            verified.append(c)
            continue
        nm = theorem_name(c)
        hit = cache.get(nm, c.tactic)
        if hit is not None:
            res = hit
        else:
            res = verifier(nm, c.theorem_statement, c.tactic)
            cache.put(nm, c.tactic, res)
        if res.get("success"):
            verified.append(c)
            logger.info("VERIFIED %s :: %s", nm, c.tactic.splitlines()[0])
        else:
            err = (res.get("error") or "").splitlines()[0][:200]
            failures.append((c, err))
            logger.warning("FAILED   %s :: %s  (%s)", nm,
                           c.tactic.splitlines()[0], err)

    if args.verify:
        cache.save()

    if failures:
        logger.warning("=== %d cells failed verification — they will NOT be written ===",
                       len(failures))
        for c, err in failures:
            logger.warning("  %s -> %s", theorem_name(c), err)

    # Write seeds
    with Path(args.seeds_out).open("w", encoding="utf-8") as f:
        f.write("# Generated by scripts/generate_redundancy_corpus.py — do not edit by hand.\n")
        f.write("# v10 redundancy corpus (operation × surface-family).\n")
        for c in verified:
            f.write(json.dumps(to_seed_row(c), ensure_ascii=False) + "\n")
    # Write candidates
    with Path(args.candidates_out).open("w", encoding="utf-8") as f:
        f.write("# Generated by scripts/generate_redundancy_corpus.py — do not edit by hand.\n")
        for c in verified:
            f.write(json.dumps(to_candidate_row(c), ensure_ascii=False) + "\n")
    # Write processed dataset (next_tactic.jsonl) — v6/v7/v8 schema
    with Path(args.processed_out).open("w", encoding="utf-8") as f:
        for c in verified:
            f.write(json.dumps(to_processed_row(c), ensure_ascii=False) + "\n")
    # Write verified traces (one positive transition per verified cell)
    with Path(args.verified_traces_out).open("w", encoding="utf-8") as f:
        for c in verified:
            f.write(json.dumps(to_processed_row(c), ensure_ascii=False) + "\n")
    # Write *failed* trace records separately — refused cells go here, NOT
    # into the verified set.
    with Path(args.failed_traces_out).open("w", encoding="utf-8") as f:
        for c, err in failures:
            f.write(json.dumps(to_failed_trace_row(c, err), ensure_ascii=False) + "\n")

    # Per-operation summary
    per_op: Dict[str, int] = {}
    per_op_fail: Dict[str, int] = {}
    for c in verified:
        per_op[c.operation] = per_op.get(c.operation, 0) + 1
    for c, _ in failures:
        per_op_fail[c.operation] = per_op_fail.get(c.operation, 0) + 1

    logger.info("WROTE %d verified cells (refused %d)", len(verified), len(failures))
    logger.info("  seeds:      %s", args.seeds_out)
    logger.info("  candidates: %s", args.candidates_out)
    logger.info("Per-operation verified / failed:")
    for op in sorted(set(list(per_op.keys()) + list(per_op_fail.keys()))):
        logger.info("  %-24s verified=%d failed=%d", op,
                    per_op.get(op, 0), per_op_fail.get(op, 0))

    return 0 if not failures else 2  # non-zero exit if any cell failed


if __name__ == "__main__":
    raise SystemExit(main())
