"""v29 Part 5 — dataset split leakage guards + density-contrast holdouts (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed" / "v29_mathlib_specialist"
CFG = OUT / "configs"
V25 = ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"
V26 = ROOT / "data" / "processed" / "v26_mathlib_specialist_splits" / "theorem_holdout" / "test_seeds.jsonl"
V27 = ROOT / "data" / "processed" / "v27_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"
V28 = ROOT / "data" / "processed" / "v28_mathlib_specialist" / "theorem_holdout" / "test_seeds.jsonl"

CONFIG_FILES = ["v29_general_train_rows.jsonl", "v29_v28best_plus_train_rows.jsonl",
                "v29_set_finset_order_heavy_train_rows.jsonl", "v29_category_balanced_train_rows.jsonl",
                "v29_function_order_train_rows.jsonl"]
SPLITS = ["theorem_holdout", "family_density_holdout", "low_density_holdout"]

pytestmark = pytest.mark.skipif(not (CFG / "v29_general_train_rows.jsonl").exists(),
                                reason="v29 dataset not built")


def _read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _pairs(rows):
    return {(r.get("theorem_statement", ""), r.get("state_before", "")) for r in rows}


def _names(rows):
    return {r.get("theorem_name", "") for r in rows}


def _bench_pairs():
    out = set()
    for p in (V25, V26, V27, V28):
        for s in _read(p):
            out.add((s["theorem_statement"], s["state_before"]))
    return out


def test_no_split_test_statement_or_name_in_any_config():
    for split in SPLITS:
        tr = _read(OUT / split / "test_rows.jsonl")
        tp, tn = _pairs(tr), _names(tr)
        for f in CONFIG_FILES:
            rows = _read(CFG / f)
            assert _pairs(rows) & tp == set(), f"{split} statement leaked into {f}"
            assert _names(rows) & tn == set(), f"{split} name leaked into {f}"


def test_no_v25_v28_benchmark_in_any_config():
    bench = _bench_pairs()
    for f in CONFIG_FILES + ["val_rows.jsonl"]:
        assert _pairs(_read(CFG / f)) & bench == set(), f"benchmark leaked into {f}"


def test_no_triple_overlap_train_vs_test():
    def triples(rows):
        return {(r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", "")) for r in rows}
    train = triples(_read(CFG / "v29_general_train_rows.jsonl"))
    for split in SPLITS:
        test = triples(_read(OUT / split / "test_rows.jsonl"))
        assert train & test == set(), f"(stmt,state,tactic) triple leaked train<->{split}"


def test_no_state_after_anywhere():
    for f in CONFIG_FILES + ["val_rows.jsonl"]:
        for r in _read(CFG / f):
            assert "state_after" not in r


def test_density_contrast_is_real():
    s = json.loads((OUT / "summary.json").read_text())
    fd = s["family_density_holdout"]["family_train_density"]
    ld = s["low_density_holdout"]["family_train_density"]
    assert fd and ld
    mean_fd = sum(fd.values()) / len(fd)
    mean_ld = sum(ld.values()) / len(ld)
    # dense holdout families must have materially MORE training siblings than sparse
    assert mean_fd >= mean_ld + 2, f"density contrast too small: dense={mean_fd:.1f} sparse={mean_ld:.1f}"


def test_category_balanced_labelled_negative_control():
    s = json.loads((OUT / "summary.json").read_text())
    assert "NEGATIVE CONTROL" in s["category_balanced_role"]
