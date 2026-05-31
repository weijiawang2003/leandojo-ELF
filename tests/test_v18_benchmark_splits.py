"""Tests for the v18 theorem-level train/val/test split."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed" / "v18_broad_core"


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"v18 split artefact absent: {p}")
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def test_three_split_files_exist() -> None:
    for n in ("train.jsonl", "val.jsonl", "test.jsonl"):
        assert (PROCESSED / n).exists(), f"v18 split missing: {n}"


def test_split_rows_are_verified_only() -> None:
    for n in ("train.jsonl", "val.jsonl", "test.jsonl"):
        for r in _read(PROCESSED / n):
            assert r.get("verified") is True, (
                f"{n} contains unverified row {r.get('theorem_name')}")


def test_theorem_names_disjoint_across_splits() -> None:
    train = {r["theorem_name"] for r in _read(PROCESSED / "train.jsonl")}
    val = {r["theorem_name"] for r in _read(PROCESSED / "val.jsonl")}
    test = {r["theorem_name"] for r in _read(PROCESSED / "test.jsonl")}
    assert not (train & val)
    assert not (train & test)
    assert not (val & test)


def test_no_state_after_in_split_rows() -> None:
    for n in ("train.jsonl", "val.jsonl", "test.jsonl"):
        for r in _read(PROCESSED / n):
            assert "state_after" not in r


def test_uses_mathlib_false_throughout() -> None:
    for n in ("train.jsonl", "val.jsonl", "test.jsonl"):
        for r in _read(PROCESSED / n):
            assert r.get("uses_mathlib") is False


def test_each_category_represented_in_at_least_one_split() -> None:
    seen_per_split = {n: set() for n in ("train", "val", "test")}
    for n in ("train", "val", "test"):
        for r in _read(PROCESSED / f"{n}.jsonl"):
            seen_per_split[n].add(r["category"])
    # At least train + test (val may be small) should cover all 10
    cover = seen_per_split["train"] | seen_per_split["test"]
    required = {"implication", "conjunction", "disjunction", "negation",
                "equality_rewrite", "exists", "forall", "nat_succ",
                "bool", "list"}
    missing = required - cover
    assert not missing, (
        f"categories not in train ∪ test (smaller v18 corpus?): {missing}")
