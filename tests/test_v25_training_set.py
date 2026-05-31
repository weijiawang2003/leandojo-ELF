"""Mini-ELF v25 — tests for the tier-C augmented training set (Part 5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AUG = ROOT / "data" / "processed" / "v25_tierc_augmented"
TRAIN = AUG / "train_rows.jsonl"
SUMMARY = AUG / "summary.json"
SPLIT = AUG / "test_theorems.json"
TEST_SEEDS = ROOT / "data" / "seeds" / "v25_mathlib_tierc_test_seeds.jsonl"


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"absent: {p}")
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_artifacts_exist():
    for p in (TRAIN, SUMMARY, SPLIT, TEST_SEEDS):
        if not p.exists():
            pytest.skip("v25 augmentation not built yet")


def test_summary_honest():
    if not SUMMARY.exists():
        pytest.skip("not built")
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert s["split_by_theorem"] is True
    assert s["uses_state_after"] is False
    assert s["uses_manual_oracle"] is False
    assert s["n_tierc_train_rows_added"] >= 1
    # every guard counter must be present
    for k in ("dropped_v18_name", "dropped_v18_triple",
              "dropped_test_theorem", "dropped_test_triple", "dropped_dedup"):
        assert k in s["ingest_stats"]


def test_held_out_theorems_absent_from_train():
    if not (SPLIT.exists() and TRAIN.exists()):
        pytest.skip("not built")
    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    test_t = set(split["test_theorems"])
    train_rows = _read(TRAIN)
    # no tier-C row for a held-out test theorem may appear in train
    leaked = {r["theorem_name"] for r in train_rows
              if r.get("corpus_source") == "v25_mathlib_tierc"
              and r["theorem_name"] in test_t}
    assert not leaked, f"held-out theorems leaked into train: {leaked}"


def test_train_test_disjoint():
    if not SPLIT.exists():
        pytest.skip("not built")
    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    assert not (set(split["test_theorems"]) & set(split["train_theorems"]))


def test_no_state_after():
    if not TRAIN.exists():
        pytest.skip("not built")
    for r in _read(TRAIN):
        assert "state_after" not in r
