"""Tests for the v24 broad+residual training set (Part 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data" / "processed" / "v24_broad_plus_residual"
TRAIN = DIR / "train_rows.jsonl"
SUMMARY = DIR / "summary.json"
V18 = ROOT / "data" / "processed" / "v18_broad_core"


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"absent: {p}")
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_training_set_exists_and_sized():
    rows = _read(TRAIN)
    assert len(rows) > 3000


def test_includes_residual_and_base():
    srcs = {r.get("corpus_source") for r in _read(TRAIN)}
    assert "v24_residual_shape_corpus" in srcs
    assert "v22_exists_corpus" in srcs  # base carried


def test_no_state_after():
    for r in _read(TRAIN):
        assert "state_after" not in r


def test_no_v18_name_leak():
    names = set()
    for fn in ("train.jsonl", "val.jsonl", "test.jsonl"):
        p = V18 / fn
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    names.add(json.loads(ln).get("theorem_name"))
    for r in _read(TRAIN):
        assert r.get("theorem_name") not in names


def test_summary_honesty_and_drops():
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert s["uses_state_after"] is False
    assert s["uses_manual_oracle"] is False
    st = s["ingest_stats"]
    assert st["dropped_v18_name"] == 0
    assert st["dropped_v18_triple"] == 0
    assert s["n_total"] == st["n_base"] + st["n_residual"] - st["dropped_dedup"]
