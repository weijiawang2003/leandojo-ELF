"""Tests for the v21 training-config builder (configs B and C pools)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG_B = ROOT / "data" / "processed" / "v21_broad_plus_forall"
CONFIG_C = ROOT / "data" / "processed" / "v21_forall_only"
V18_ROOT = ROOT / "data" / "processed" / "v18_broad_core"


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"v21 config artefact absent: {p}")
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s:
            continue
        out.append(json.loads(s))
    return out


def test_config_b_exists_and_sized():
    rows = _read(CONFIG_B / "train_rows.jsonl")
    # v20 pool (2099) + v21 forall (677) minus dedup ~= 2776.
    assert len(rows) >= 2700, f"config B too small: {len(rows)}"


def test_config_b_includes_forall_and_v20():
    rows = _read(CONFIG_B / "train_rows.jsonl")
    srcs = {r.get("corpus_source") for r in rows}
    assert "v21_forall_corpus" in srcs
    assert "v20_implication_corpus" in srcs
    assert "v20_bool_corpus" in srcs


def test_config_b_forall_row_count():
    rows = _read(CONFIG_B / "train_rows.jsonl")
    forall = [r for r in rows if r.get("corpus_source") == "v21_forall_corpus"]
    assert len(forall) >= 600, f"config B forall rows too few: {len(forall)}"


def test_config_c_forall_only():
    rows = _read(CONFIG_C / "train_rows.jsonl")
    # Specialist pool must be (nearly) all forall.
    assert len(rows) >= 600
    non_forall = [r for r in rows
                  if r.get("category") not in (None, "forall")
                  and r.get("required_operation") != "instantiate_forall"]
    assert not non_forall, f"specialist pool has non-forall rows: {non_forall[:3]}"


def _v18_universe():
    names, triples = set(), set()
    for fname in ("train.jsonl", "val.jsonl", "test.jsonl"):
        p = V18_ROOT / fname
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            o = json.loads(ln)
            if o.get("theorem_name"):
                names.add(o["theorem_name"])
            triples.add((o.get("theorem_statement", ""),
                         o.get("state_before", ""), o.get("tactic", "")))
    return names, triples


def test_config_b_no_v18_leakage():
    rows = _read(CONFIG_B / "train_rows.jsonl")
    names, triples = _v18_universe()
    for r in rows:
        assert r.get("theorem_name") not in names
        t = (r.get("theorem_statement", ""), r.get("state_before", ""),
             r.get("tactic", ""))
        assert t not in triples


def test_config_b_no_state_after():
    rows = _read(CONFIG_B / "train_rows.jsonl")
    for r in rows:
        assert "state_after" not in r


def test_config_summaries_honest():
    for d in (CONFIG_B, CONFIG_C):
        sp = d / "summary.json"
        if not sp.exists():
            pytest.skip()
        s = json.loads(sp.read_text(encoding="utf-8"))
        assert s.get("uses_state_after") is False
        assert s.get("uses_manual_oracle") is False
        assert s["ingest_stats"].get("dropped_by_v18_name_guard", 0) == 0
