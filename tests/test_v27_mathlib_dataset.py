"""v27 Part 5 — dataset split leakage guards (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed" / "v27_mathlib_specialist"
CFG = OUT / "configs"
TH = OUT / "theorem_holdout"
V25_TEST = ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"
V26_TEST = ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout" / "test_seeds.jsonl"

pytestmark = pytest.mark.skipif(not (CFG / "v27_widened_train_rows.jsonl").exists(),
                                reason="v27 dataset not built")


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _pairs(rows):
    return {(r["theorem_statement"], r["state_before"]) for r in rows}


def _names(rows):
    return {r["theorem_name"] for r in rows}


def _bench_pairs():
    out = set()
    for p in (V25_TEST, V26_TEST):
        for s in _read(p):
            out.add((s["theorem_statement"], s["state_before"]))
    return out


def test_all_configs_exist_and_nonempty():
    for f in ("v27_base_train_rows.jsonl", "v27_widened_train_rows.jsonl",
              "v27_category_balanced_train_rows.jsonl", "v27_set_heavy_train_rows.jsonl",
              "val_rows.jsonl"):
        assert (CFG / f).exists() and len(_read(CFG / f)) > 0


def test_no_v27_holdout_statement_in_any_train_config():
    test_pairs = _pairs(_read(TH / "test_rows.jsonl"))
    for f in ("v27_base_train_rows.jsonl", "v27_widened_train_rows.jsonl",
              "v27_category_balanced_train_rows.jsonl", "v27_set_heavy_train_rows.jsonl"):
        assert _pairs(_read(CFG / f)) & test_pairs == set(), f"holdout-test leak in {f}"


def test_no_v25_v26_benchmark_statement_in_train():
    bench = _bench_pairs()
    for f in ("v27_base_train_rows.jsonl", "v27_widened_train_rows.jsonl"):
        assert _pairs(_read(CFG / f)) & bench == set(), f"benchmark leak in {f}"


def test_no_holdout_theorem_name_in_train():
    test_names = _names(_read(TH / "test_rows.jsonl"))
    assert _names(_read(CFG / "v27_widened_train_rows.jsonl")) & test_names == set()


def test_widened_superset_of_v27_contribution_vs_base():
    # widened has at least as many rows as base (extra v26 set-widen rows)
    assert len(_read(CFG / "v27_widened_train_rows.jsonl")) >= len(_read(CFG / "v27_base_train_rows.jsonl"))


def test_no_state_after_anywhere():
    for f in ("v27_widened_train_rows.jsonl", "val_rows.jsonl"):
        for r in _read(CFG / f):
            assert "state_after" not in r
    for r in _read(TH / "test_rows.jsonl"):
        assert "state_after" not in r


def test_category_holdouts_have_no_target_category_in_train():
    chs = OUT / "category_holdout_set"
    if (chs / "train_rows.jsonl").exists():
        assert all(r.get("category") != "set" for r in _read(chs / "train_rows.jsonl"))
    cho = OUT / "category_holdout_order"
    if (cho / "train_rows.jsonl").exists():
        assert all(r.get("expected_skill") != "order" and r.get("category") != "order"
                   for r in _read(cho / "train_rows.jsonl"))
