"""Split strategies for the v2 generalization study.

The default dataset split (``dataset_builder._theorem_split``) is a deterministic
per-theorem **hash** split — good for in-distribution evaluation, but it lets the
*same pattern family* land in both train and eval, so a model can pass by
near-copying a train sibling. v2 adds three harder, distribution-shifted
strategies to test generalization:

  - ``hash``                — existing behavior (in-distribution baseline).
  - ``family_holdout``      — whole pattern families go to one split; eval
                              families are unseen at train time (out-of-family).
  - ``difficulty_holdout``  — train on easy/medium, eval on hard (compositional).
  - ``adversarial_sibling`` — train one of a confusable sibling pair, eval the
                              other (e.g. train ``and_elim_left``, test
                              ``and_elim_right``); near neighbours exist in train
                              but the exact pattern is held out.

All strategies are deterministic given ``seed`` and degrade gracefully when
metadata (``pattern_family`` / ``difficulty``) is missing: an unlabelled theorem
falls back to the hash split (difficulty defaults to ``easy`` so legacy/basic
corpus rows train rather than vanish). No ``state_after`` is read.
"""

from __future__ import annotations

import hashlib
from typing import Dict, Iterable, List, Optional, Tuple

from .io_utils import read_jsonl

SPLIT_STRATEGIES: Tuple[str, ...] = (
    "hash", "family_holdout", "difficulty_holdout", "adversarial_sibling",
    "family_interpolation",
)

# Confusable sibling pairs: (train-side family, eval-side family). The eval-side
# family is held out of training so the model must generalize across the
# relational flip rather than copy a same-family train example.
SIBLING_SPLITS: Dict[str, Tuple[str, str]] = {
    "and_elim": ("and_elim_left", "and_elim_right"),
    "or_intro": ("or_intro_left", "or_intro_right"),
    "iff_dir": ("iff_mp", "iff_mpr"),
    # hard-corpus relational flips:
    "nested_and_elim": ("nested_and_elim_r", "nested_and_elim_l"),
    "iff_chain_dir": ("iff_apply", "iff_flip"),
}

_TRAIN_SIDE = {pair[0] for pair in SIBLING_SPLITS.values()}
_EVAL_SIDE = {pair[1] for pair in SIBLING_SPLITS.values()}


def _hash01(s: str, seed: int) -> float:
    h = hashlib.sha256(f"{s}|{seed}".encode("utf-8")).hexdigest()
    return int(h[:16], 16) / float(1 << 64)


def _bucket(x: float, train: float, val: float, test: float) -> str:
    total = train + val + test
    tr, va = train / total, val / total
    if x < tr:
        return "train"
    if x < tr + va:
        return "val"
    return "test"


def load_theorem_metadata(seeds_path) -> Dict[str, Dict]:
    """``theorem_name -> {pattern_family, difficulty, requires_*}`` from a seeds
    JSONL with a ``metadata`` block. Missing fields are ``None``."""
    out: Dict[str, Dict] = {}
    for row in read_jsonl(seeds_path):
        name = row.get("theorem_name")
        if not name:
            continue
        meta = row.get("metadata") or {}
        out[name] = {
            "pattern_family": meta.get("pattern_family"),
            "difficulty": meta.get("difficulty"),
            "requires_multistep": meta.get("requires_multistep"),
            "requires_copy": meta.get("requires_copy"),
            "requires_structure": meta.get("requires_structure"),
        }
    return out


def assign_splits(
    names: Iterable[str],
    meta: Dict[str, Dict],
    strategy: str = "hash",
    *,
    train: float = 0.8,
    val: float = 0.1,
    test: float = 0.1,
    seed: int = 42,
) -> Dict[str, str]:
    """Return ``theorem_name -> 'train'|'val'|'test'`` under ``strategy``.

    ``meta`` maps name -> metadata dict (``pattern_family`` / ``difficulty``).
    Theorems missing the relevant metadata fall back to the hash split."""
    if strategy not in SPLIT_STRATEGIES:
        raise ValueError(f"unknown split strategy {strategy!r}; choose from {SPLIT_STRATEGIES}")
    names = sorted(set(names))

    if strategy == "hash":
        return {n: _bucket(_hash01(n, seed), train, val, test) for n in names}

    if strategy == "family_holdout":
        fams = sorted({(meta.get(n) or {}).get("pattern_family") for n in names} - {None})
        fam_split = {f: _bucket(_hash01(f, seed), train, val, test) for f in fams}
        out: Dict[str, str] = {}
        for n in names:
            fam = (meta.get(n) or {}).get("pattern_family")
            out[n] = fam_split[fam] if fam in fam_split else _bucket(_hash01(n, seed), train, val, test)
        return out

    if strategy == "family_interpolation":
        # v5: *within-family* split. Each family keeps a train fraction (donors)
        # and holds out the rest to test, so a retrieval/learned proposer has
        # same-family examples WITHOUT the test theorem itself appearing in
        # train. Deterministic (hash-ranked within family); val is empty. Tiny
        # families (1 theorem) go to test (no donor — retrieval fails honestly).
        from collections import defaultdict

        total = train + val + test
        frac_train = train / total if total else 0.5
        fam_members: Dict[str, List[str]] = defaultdict(list)
        out = {}
        for n in names:
            fam = (meta.get(n) or {}).get("pattern_family")
            if fam:
                fam_members[fam].append(n)
            else:
                out[n] = _bucket(_hash01(n, seed), train, val, test)
        for fam, members in fam_members.items():
            ordered = sorted(members, key=lambda nm: (_hash01(nm, seed), nm))
            k = len(ordered)
            if k == 1:
                out[ordered[0]] = "test"
                continue
            n_train = int(round(frac_train * k))
            n_train = max(1, min(n_train, k - 1))  # guarantee both train and test
            for idx, nm in enumerate(ordered):
                out[nm] = "train" if idx < n_train else "test"
        return out

    if strategy == "difficulty_holdout":
        # easy/medium/None -> train; hard -> val|test (split 50/50 by hash).
        out = {}
        for n in names:
            diff = (meta.get(n) or {}).get("difficulty") or "easy"
            if diff == "hard":
                out[n] = "val" if _hash01(n, seed) < 0.5 else "test"
            else:
                out[n] = "train"
        return out

    # adversarial_sibling
    out = {}
    for n in names:
        fam = (meta.get(n) or {}).get("pattern_family")
        if fam in _TRAIN_SIDE:
            out[n] = "train"
        elif fam in _EVAL_SIDE:
            out[n] = "val" if _hash01(n, seed) < 0.5 else "test"
        else:
            out[n] = _bucket(_hash01(n, seed), train, val, test)
    return out


def family_disjoint(split_map: Dict[str, str], meta: Dict[str, Dict]) -> bool:
    """True iff no pattern family appears in more than one split (family_holdout
    invariant). Theorems without a family are ignored."""
    fam_to_splits: Dict[str, set] = {}
    for n, sp in split_map.items():
        fam = (meta.get(n) or {}).get("pattern_family")
        if fam:
            fam_to_splits.setdefault(fam, set()).add(sp)
    return all(len(s) == 1 for s in fam_to_splits.values())
