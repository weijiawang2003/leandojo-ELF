"""Mini-ELF v7 — donor-scarcity split strategies for *retrieval* evaluation.

v6 hit pass@5 1.00 on the planner-blind `family_interpolation` split, but the
Part-1 audit shows that split keeps a same-family donor in train for every test
row (and forbidding same-family donors collapses v6 to 0.00). v7 measures
retrieval under graded donor scarcity. These split builders re-assign each
theorem's `split` field (`train`/`test`; no val) under four regimes:

  * ``family_holdout``   — leave-one-family-out: each fold's test family has **no
    same-family donor** in train (a same-*operation* sibling family may remain).
  * ``operation_holdout``— leave-one-operation-out: the held operation (and all
    its families) is absent from train — **no same-operation donor**, the hardest.
  * ``k_shot_family``    — each family contributes exactly ``k`` donor theorems to
    train (deterministic), the rest to test. ``k=0`` is a pure floor (empty
    train); ``k=1,2`` measure *scarce* same-family donors.
  * ``literal_holdout``  — the proof *schema* stays in train but each test
    theorem's numeric literal is **globally unseen** in any train tactic, forcing
    numeric adaptation rather than verbatim reuse.

Pure-Python / torch-free; deterministic given ``seed``; reads neither Lean nor
``state_after``. The family→operation map is supplied by the caller (computed
from `retrieval_features.extract_features` over the corpus)."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

OP_UNKNOWN = "unknown"
_NUM_RE = re.compile(r"(?<![\w.])\d+(?!\w)")

# A "fold" is (held_label, {theorem_name: 'train'|'test'}).
Fold = Tuple[str, Dict[str, str]]


def _hash01(s: str, seed: int) -> float:
    h = hashlib.sha256(f"{s}|{seed}".encode("utf-8")).hexdigest()
    return int(h[:16], 16) / float(1 << 64)


def _ordered(names: Sequence[str], seed: int) -> List[str]:
    return sorted(set(names), key=lambda nm: (_hash01(nm, seed), nm))


# ---------------- leave-one-out holdouts ----------------


def family_holdout_folds(theorems: Sequence[str], thm2fam: Dict[str, str]) -> List[Fold]:
    """One fold per pattern family: that family's theorems -> test, all others ->
    train. A theorem with no family is always train (it can never be the held
    family)."""
    fams = sorted({thm2fam.get(t) for t in theorems} - {None})
    folds: List[Fold] = []
    for held in fams:
        assign = {t: ("test" if thm2fam.get(t) == held else "train") for t in theorems}
        folds.append((held, assign))
    return folds


def operation_holdout_folds(theorems: Sequence[str], thm2op: Dict[str, str]) -> List[Fold]:
    """One fold per required-operation value (including ``unknown``): every
    theorem with that operation -> test, all others -> train. Harder than family
    holdout because *all* families sharing the operation are removed at once."""
    ops = sorted({thm2op.get(t, OP_UNKNOWN) for t in theorems})
    folds: List[Fold] = []
    for held in ops:
        assign = {t: ("test" if thm2op.get(t, OP_UNKNOWN) == held else "train") for t in theorems}
        folds.append((held, assign))
    return folds


# ---------------- k-shot ----------------


def kshot_family_split(theorems: Sequence[str], thm2fam: Dict[str, str], k: int,
                       *, seed: int = 42) -> Dict[str, str]:
    """Each family keeps the first ``k`` theorems (deterministic hash order) as
    train donors; the rest go to test. ``k=0`` -> train empty (floor). A theorem
    with no family always goes to test (it can supply no same-family donor)."""
    members: Dict[str, List[str]] = defaultdict(list)
    out: Dict[str, str] = {}
    for t in theorems:
        fam = thm2fam.get(t)
        if fam is None:
            out[t] = "test"
        else:
            members[fam].append(t)
    for fam, ms in members.items():
        for idx, nm in enumerate(_ordered(ms, seed)):
            out[nm] = "train" if idx < k else "test"
    return out


# ---------------- v10 redundancy: cell holdout + per-operation k-shot ----------------


def cell_holdout_folds(
    theorems: Sequence[str],
    thm2op: Dict[str, str],
    thm2fam: Dict[str, str],
) -> List[Tuple[Tuple[str, str], Dict[str, str]]]:
    """v10 redundancy-corpus split: leave-one-cell-out.

    A "cell" is the pair (``operation``, ``surface_family``). The held cell's
    theorems go to ``test``; everything else (including *other* surface
    families of the *same* operation — the redundancy condition) goes to
    ``train``. Returns ``[((operation, family), assignment), ...]`` sorted
    deterministically.
    """
    cells = sorted({
        (thm2op.get(t, OP_UNKNOWN), thm2fam.get(t))
        for t in theorems
        if thm2fam.get(t) is not None
    })
    folds: List[Tuple[Tuple[str, str], Dict[str, str]]] = []
    for held_op, held_fam in cells:
        assign = {
            t: ("test"
                if (thm2op.get(t, OP_UNKNOWN) == held_op
                    and thm2fam.get(t) == held_fam)
                else "train")
            for t in theorems
        }
        folds.append(((held_op, held_fam), assign))
    return folds


def kshot_operation_split(
    theorems: Sequence[str],
    thm2op: Dict[str, str],
    thm2fam: Dict[str, str],
    k_train_cells_per_op: int,
    *,
    seed: int = 42,
) -> Dict[str, str]:
    """v10 redundancy-corpus split: each *operation* contributes exactly
    ``k_train_cells_per_op`` distinct surface families to train; the rest of
    that operation's cells go to test. Deterministic given ``seed``.

    A theorem with no family/operation always goes to test (it can never count
    as a per-operation training donor)."""
    # Group families by operation; pick k families per operation as train.
    op_families: Dict[str, List[str]] = defaultdict(list)
    for t in theorems:
        op = thm2op.get(t, OP_UNKNOWN)
        fam = thm2fam.get(t)
        if fam is None:
            continue
        if fam not in op_families[op]:
            op_families[op].append(fam)

    train_families: Dict[str, set] = {}
    for op, fams in op_families.items():
        ordered = _ordered(fams, seed)
        train_families[op] = set(ordered[:k_train_cells_per_op])

    out: Dict[str, str] = {}
    for t in theorems:
        op = thm2op.get(t, OP_UNKNOWN)
        fam = thm2fam.get(t)
        if fam is None:
            out[t] = "test"
            continue
        out[t] = "train" if fam in train_families.get(op, set()) else "test"
    return out


def operation_sibling_in_train(
    assign: Dict[str, str],
    thm2op: Dict[str, str],
    thm2fam: Dict[str, str],
    held_op: str,
    held_fam: str,
) -> bool:
    """For a held cell ``(held_op, held_fam)``: True iff at least one train
    theorem shares the operation but is a *different* surface family. v10's
    redundancy regimes rely on this being True (donor-sibling present)."""
    for t, s in assign.items():
        if s != "train":
            continue
        if thm2op.get(t, OP_UNKNOWN) == held_op and thm2fam.get(t) != held_fam:
            return True
    return False


# ---------------- literal holdout ----------------


def _literals_of(tactics: Sequence[str]) -> set:
    out: set = set()
    for t in tactics:
        out |= {m.group(0) for m in _NUM_RE.finditer(t)}
    return out


def _skeleton(tactic: str) -> str:
    """Tactic with its numeric literals blanked (``exact h 13`` -> ``exact h
    <num>``) — a state-free proxy for the proof *schema*, used to group
    literal-bearing theorems that differ only in their literal."""
    return _NUM_RE.sub("<num>", tactic)


def literal_holdout_split(
    thm_tactics: Dict[str, List[str]],
    *,
    seed: int = 42,
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """Hold out literal-bearing theorems whose numeric literal is **globally
    unseen** among train tactics, while the literal-free schema stays in train.

    ``thm_tactics`` maps theorem_name -> its verified tactic strings. Returns
    ``(assignment, held_literals)``. Strategy: group literal-bearing theorems by
    their literal-blanked *skeleton*; keep ~half of each group in train (anchoring
    the schema and a set of "seen" literals), then hold out a remaining theorem
    only if its literal is novel vs train — both within its group and globally.
    Non-literal theorems always go to train."""
    lit_thms = {t: _literals_of(tacs) for t, tacs in thm_tactics.items() if _literals_of(tacs)}
    # group by the skeleton of a theorem's (first, deterministic) literal-bearing tactic
    groups: Dict[str, List[str]] = defaultdict(list)
    for t in lit_thms:
        for tac in sorted(thm_tactics[t]):
            if _NUM_RE.search(tac):
                groups[_skeleton(tac)].append(t)
                break

    out: Dict[str, str] = {t: "train" for t in thm_tactics}
    tentative_test: List[str] = []
    for _sk, members in groups.items():
        ordered = _ordered(members, seed)
        n_train = max(1, (len(ordered) + 1) // 2)  # keep >= half in train to anchor the schema
        train_lits: set = set()
        for t in ordered[:n_train]:
            train_lits |= lit_thms[t]
        for t in ordered[n_train:]:
            if lit_thms[t] and lit_thms[t].isdisjoint(train_lits):
                tentative_test.append(t)
            # else: literal already seen in this group's train half -> keep train

    # Global guard: a held-out literal must not appear in ANY train tactic.
    train_global_lits = _literals_of(
        [tac for t in thm_tactics if t not in tentative_test for tac in thm_tactics[t]]
    )
    held_literals: Dict[str, List[str]] = {}
    for t in tentative_test:
        lits = lit_thms[t]
        if lits.isdisjoint(train_global_lits):
            out[t] = "test"
            held_literals[t] = sorted(lits)
        # else: literal seen elsewhere in train -> keep in train
    return out, held_literals


# ---------------- invariants (used by tests + the build script) ----------------


def assert_no_theorem_leakage(assign: Dict[str, str]) -> None:
    """A theorem lands in exactly one split (guaranteed by construction; checked
    so a future refactor cannot silently break it)."""
    # `assign` is a dict, so each theorem maps to one value by definition; this
    # asserts every value is a known split label.
    bad = {t: s for t, s in assign.items() if s not in ("train", "test", "val")}
    if bad:
        raise AssertionError(f"unknown split labels: {bad}")


def family_absent_from_train(assign: Dict[str, str], thm2fam: Dict[str, str], held: str) -> bool:
    """True iff no train theorem belongs to the held family."""
    return all(thm2fam.get(t) != held for t, s in assign.items() if s == "train")


def operation_absent_from_train(assign: Dict[str, str], thm2op: Dict[str, str], held: str) -> bool:
    return all(thm2op.get(t, OP_UNKNOWN) != held for t, s in assign.items() if s == "train")


def family_train_count(assign: Dict[str, str], thm2fam: Dict[str, str], fam: str) -> int:
    return sum(1 for t, s in assign.items() if s == "train" and thm2fam.get(t) == fam)
