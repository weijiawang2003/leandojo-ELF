"""v30 Part 5 — dataset split leakage guards (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed" / "v30_mathlib_specialist"
CFG = OUT / "configs"
P = ROOT / "data" / "processed"
BENCH = [
    ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl",
    P / "v26_mathlib_specialist_splits" / "theorem_holdout" / "test_seeds.jsonl",
    P / "v27_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl",
    P / "v28_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl",
    P / "v29_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl",
]
CONFIG_FILES = ["v30_general_targeted_train_rows.jsonl", "v30_v29best_plus_train_rows.jsonl",
                "v30_targeted_only_train_rows.jsonl", "v30_targeted_upsample_train_rows.jsonl"]
SPLITS = ["theorem_holdout", "targeted_family_holdout"]

pytestmark = pytest.mark.skipif(not (CFG / "v30_general_targeted_train_rows.jsonl").exists(),
                                reason="v30 dataset not built")


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _pairs(rows):
    return {(r.get("theorem_statement", ""), r.get("state_before", "")) for r in rows}


def _names(rows):
    return {r.get("theorem_name", "") for r in rows}


def test_no_split_test_in_any_config():
    for split in SPLITS:
        tr = _read(OUT / split / "test_rows.jsonl")
        tp, tn = _pairs(tr), _names(tr)
        for f in CONFIG_FILES:
            rows = _read(CFG / f)
            assert _pairs(rows) & tp == set(), f"{split} statement leaked into {f}"
            assert _names(rows) & tn == set(), f"{split} name leaked into {f}"


def test_no_v25_v29_benchmark_in_any_config():
    bench = set()
    for p in BENCH:
        for s in _read(p):
            bench.add((s["theorem_statement"], s["state_before"]))
    for f in CONFIG_FILES + ["val_rows.jsonl"]:
        assert _pairs(_read(CFG / f)) & bench == set(), f"benchmark leaked into {f}"


def test_no_state_after_anywhere():
    for f in CONFIG_FILES + ["val_rows.jsonl"]:
        for r in _read(CFG / f):
            assert "state_after" not in r


def test_category_balanced_not_built():
    s = json.loads((OUT / "summary.json").read_text())
    assert "NOT built" in s["category_balanced"]
