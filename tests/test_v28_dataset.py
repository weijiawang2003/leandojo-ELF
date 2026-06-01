"""v28 Part 4 — dataset split leakage guards (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed" / "v28_mathlib_specialist"
CFG = OUT / "configs"
TH = OUT / "theorem_holdout"
V25_TEST = ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"
V26_TEST = ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout" / "test_seeds.jsonl"
V27_TEST = ROOT / "data" / "processed" / "v27_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"

CONFIG_FILES = ["v28_general_train_rows.jsonl", "v28_set_order_heavy_train_rows.jsonl",
                "v28_category_balanced_train_rows.jsonl", "v28_finset_specialist_train_rows.jsonl"]

pytestmark = pytest.mark.skipif(not (CFG / "v28_general_train_rows.jsonl").exists(),
                                reason="v28 dataset not built")


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _pairs(rows):
    return {(r["theorem_statement"], r["state_before"]) for r in rows}


def _names(rows):
    return {r["theorem_name"] for r in rows}


def _bench_pairs():
    out = set()
    for p in (V25_TEST, V26_TEST, V27_TEST):
        for s in _read(p):
            out.add((s["theorem_statement"], s["state_before"]))
    return out


def test_no_holdout_statement_or_name_in_any_config():
    test_rows = _read(TH / "test_rows.jsonl")
    test_pairs = _pairs(test_rows)
    test_names = _names(test_rows)
    for f in CONFIG_FILES:
        rows = _read(CFG / f)
        assert _pairs(rows) & test_pairs == set(), f"holdout statement leaked into {f}"
        assert _names(rows) & test_names == set(), f"holdout name leaked into {f}"


def test_no_v25_v26_v27_benchmark_in_any_config():
    bench = _bench_pairs()
    for f in CONFIG_FILES + ["val_rows.jsonl"]:
        assert _pairs(_read(CFG / f)) & bench == set(), f"benchmark leaked into {f}"


def test_no_state_after_anywhere():
    for f in CONFIG_FILES + ["val_rows.jsonl"]:
        for r in _read(CFG / f):
            assert "state_after" not in r
    for r in _read(TH / "test_rows.jsonl"):
        assert "state_after" not in r


def test_fresh_holdout_is_larger_than_v27():
    # v28 holdout must be a more robust benchmark than v27's 7 theorems
    seeds = _read(TH / "test_seeds.jsonl")
    assert len(seeds) >= 20


def test_category_holdouts_exclude_their_category_from_train():
    for key in ("set", "order", "finset"):
        d = OUT / f"category_holdout_{key}"
        if (d / "train_rows.jsonl").exists():
            assert all(r.get("category") != key for r in _read(d / "train_rows.jsonl")), \
                f"{key} rows present in its own holdout train"


def test_finset_category_present():
    rows = _read(CFG / "v28_general_train_rows.jsonl")
    assert any(r.get("category") == "finset" for r in rows)
