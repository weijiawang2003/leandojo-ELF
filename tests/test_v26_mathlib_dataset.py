"""v26 specialist dataset/split tests: leakage guards on the produced splits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPL = ROOT / "data" / "processed" / "v26_mathlib_specialist_splits"
TH = SPL / "theorem_holdout"
V25_TT = ROOT / "data" / "processed" / "v25_tierc_augmented" / "test_theorems.json"

pytestmark = pytest.mark.skipif(not TH.exists(), reason="splits not built")


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _triples(rows):
    return {(r["theorem_statement"], r["state_before"], r["tactic"]) for r in rows}


def _names(rows):
    return {r["theorem_name"] for r in rows}


def test_theorem_holdout_no_name_overlap():
    tr, va, te = _read(TH / "train_rows.jsonl"), _read(TH / "val_rows.jsonl"), _read(TH / "test_rows.jsonl")
    assert _names(tr) & _names(te) == set()
    assert _names(tr) & _names(va) == set()


def test_theorem_holdout_no_triple_overlap():
    tr, va, te = _read(TH / "train_rows.jsonl"), _read(TH / "val_rows.jsonl"), _read(TH / "test_rows.jsonl")
    assert _triples(tr) & _triples(te) == set()
    assert _triples(tr) & _triples(va) == set()


def test_v25_heldout_test_theorems_never_in_train():
    tt = json.loads(V25_TT.read_text())
    v25_test = set(tt["test_theorems"])
    tr = _read(TH / "train_rows.jsonl")
    assert _names(tr) & v25_test == set()


def test_category_holdout_set_train_has_no_set_rows():
    rows = _read(SPL / "category_holdout_set" / "train_rows.jsonl")
    assert all(r["category"] != "set" for r in rows)
    test = _read(SPL / "category_holdout_set" / "test_rows.jsonl")
    assert all(r["category"] == "set" for r in test) and len(test) > 0


def test_category_holdout_order_train_has_no_order_rows():
    rows = _read(SPL / "category_holdout_order" / "train_rows.jsonl")
    assert all(r.get("expected_skill") != "order" for r in rows)


def test_plus_core_adds_small_core_subset():
    plus = _read(TH / "train_rows_plus_core.jsonl")
    base = _read(TH / "train_rows.jsonl")
    core = [r for r in plus if not r["mathlib"]]
    assert len(core) > 0
    assert len(plus) == len(base) + len(core)
    # "small": far smaller than the v24 broad corpus (3138 rows)
    assert len(core) < 200


def test_no_state_after_anywhere():
    for fn in ("train_rows.jsonl", "val_rows.jsonl", "test_rows.jsonl"):
        for r in _read(TH / fn):
            assert "state_after" not in r
