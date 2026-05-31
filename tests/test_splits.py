"""v2 split strategies: leakage-freedom, family disjointness, difficulty/sibling
holdout constraints, and graceful fallback when metadata is missing. Pure-Python;
no torch, no Lean."""

from __future__ import annotations

from pathlib import Path

import pytest

from mini_elf_lean.splits import (
    SIBLING_SPLITS,
    SPLIT_STRATEGIES,
    assign_splits,
    family_disjoint,
    load_theorem_metadata,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "mini_elf_lean"


def _meta():
    # 3 families × 4 theorems, mixed difficulty, incl. sibling families.
    m = {}
    for i in range(4):
        m[f"and_elim_left_{i}"] = {"pattern_family": "and_elim_left", "difficulty": "easy"}
        m[f"and_elim_right_{i}"] = {"pattern_family": "and_elim_right", "difficulty": "medium"}
        m[f"chain_{i}"] = {"pattern_family": "imp_chain3", "difficulty": "hard"}
    return m


@pytest.mark.parametrize("strategy", SPLIT_STRATEGIES)
def test_no_theorem_leakage(strategy):
    m = _meta()
    sp = assign_splits(m.keys(), m, strategy, seed=0)
    # every theorem assigned exactly one split
    assert set(sp) == set(m)
    assert all(v in ("train", "val", "test") for v in sp.values())


def test_family_holdout_disjoint():
    m = _meta()
    sp = assign_splits(m.keys(), m, "family_holdout", seed=0)
    assert family_disjoint(sp, m)  # no family spans two splits


def test_difficulty_holdout_puts_hard_in_eval():
    m = _meta()
    sp = assign_splits(m.keys(), m, "difficulty_holdout", seed=0)
    for name, info in m.items():
        if info["difficulty"] == "hard":
            assert sp[name] in ("val", "test"), f"{name} hard but in {sp[name]}"
        else:
            assert sp[name] == "train", f"{name} easy/medium but in {sp[name]}"
    # at least one hard theorem actually lands in test
    assert any(sp[n] == "test" for n, i in m.items() if i["difficulty"] == "hard")


def test_adversarial_sibling_holds_out_eval_side():
    m = _meta()
    sp = assign_splits(m.keys(), m, "adversarial_sibling", seed=0)
    # and_elim_left is a train-side family; and_elim_right is the eval-side.
    for name, info in m.items():
        fam = info["pattern_family"]
        if fam == "and_elim_left":
            assert sp[name] == "train"
        elif fam == "and_elim_right":
            assert sp[name] in ("val", "test")


def test_sibling_map_pairs_are_disjoint():
    lefts = [p[0] for p in SIBLING_SPLITS.values()]
    rights = [p[1] for p in SIBLING_SPLITS.values()]
    assert set(lefts).isdisjoint(set(rights))


def test_fallback_when_metadata_missing():
    # No metadata at all -> every strategy must still assign valid splits
    names = [f"t{i}" for i in range(20)]
    empty = {}
    for strategy in SPLIT_STRATEGIES:
        sp = assign_splits(names, empty, strategy, seed=1)
        assert set(sp) == set(names)
        assert all(v in ("train", "val", "test") for v in sp.values())
    # difficulty_holdout with no difficulty -> all train (default easy)
    sp = assign_splits(names, empty, "difficulty_holdout", seed=1)
    assert all(v == "train" for v in sp.values())


def test_hash_strategy_matches_fractions_roughly():
    names = [f"thm_{i}" for i in range(400)]
    sp = assign_splits(names, {}, "hash", train=0.8, val=0.1, test=0.1, seed=42)
    frac_train = sum(1 for v in sp.values() if v == "train") / len(names)
    assert 0.7 < frac_train < 0.9  # roughly 0.8


def test_deterministic():
    m = _meta()
    a = assign_splits(m.keys(), m, "family_holdout", seed=3)
    b = assign_splits(m.keys(), m, "family_holdout", seed=3)
    assert a == b


def test_load_theorem_metadata_real_seeds():
    seeds = Path(__file__).resolve().parents[1] / "data" / "seeds" / "hard_lean_seeds.jsonl"
    if not seeds.exists():
        pytest.skip("hard seeds not generated")
    meta = load_theorem_metadata(seeds)
    assert meta
    some = next(iter(meta.values()))
    assert "pattern_family" in some and "difficulty" in some


def test_splits_module_never_accesses_state_after():
    text = (SRC / "splits.py").read_text(encoding="utf-8")
    for pat in (".state_after", '["state_after"]', "['state_after']",
                'get("state_after"', "get('state_after'"):
        assert pat not in text
