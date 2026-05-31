"""Mini-ELF v25 — tests for the Mathlib tier-C corpus (Parts 2-3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "data" / "seeds" / "v25_mathlib_tierc_seeds.jsonl"
CAND = ROOT / "data" / "manual" / "v25_mathlib_tierc_candidates.jsonl"
VERIFIED = ROOT / "data" / "traces" / "v25_mathlib_tierc_verified.jsonl"
FAILED = ROOT / "data" / "traces" / "v25_mathlib_tierc_failed.jsonl"
CORPUS = ROOT / "data" / "processed" / "v25_mathlib_tierc_corpus"
TRAIN = CORPUS / "train_rows.jsonl"
SUMMARY = CORPUS / "summary.json"

CATEGORIES = {"nat", "list", "bool_option", "set", "logic"}


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"absent: {p}")
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_artifacts_exist():
    for p in (SEEDS, CAND, VERIFIED, FAILED, TRAIN, SUMMARY):
        assert p.exists(), f"missing {p}"


def test_theorem_count_in_range():
    seeds = _read(SEEDS)
    assert 20 <= len(seeds) <= 50, f"want 20-50 tier-C theorems, got {len(seeds)}"


def test_categories_covered():
    cats = {s["category"] for s in _read(SEEDS)}
    assert CATEGORIES <= cats, f"missing {CATEGORIES - cats}"


def test_all_verified_candidates_actually_verified():
    rows = _read(VERIFIED)
    assert rows, "no verified rows"
    assert all(r.get("verified") is True for r in rows)


def test_manual_candidates_are_verified_only():
    # the manual reference file must contain only Lean-accepted candidates
    assert all(r.get("verified") is True for r in _read(CAND))


def test_at_least_one_verified_per_theorem():
    seeds = {s["theorem_name"] for s in _read(SEEDS)}
    verified_thms = {r["theorem_name"] for r in _read(VERIFIED)}
    missing = seeds - verified_thms
    assert not missing, f"theorems with no verified candidate: {sorted(missing)}"


def test_summary_honest_and_mathlib():
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert s["mathlib_available"] is True
    assert s["uses_mathlib"] is True
    assert s["uses_state_after"] is False
    assert s["uses_manual_oracle"] is False
    assert s["imports_used"] == ["import Mathlib"]
    assert s["n_zero_success_theorems"] == 0
    assert s["n_candidates_verified"] >= 80


def test_no_state_after_anywhere():
    for p in (SEEDS, CAND, VERIFIED, FAILED, TRAIN):
        for r in _read(p):
            assert "state_after" not in r


def test_v18_leakage_guarded():
    # no verified/training tier-C row may duplicate a v18 (stmt,state,tactic)
    v18 = ROOT / "data" / "processed" / "v18_broad_core"
    triples = set()
    for fn in ("train.jsonl", "val.jsonl", "test.jsonl"):
        p = v18 / fn
        if p.exists():
            for r in (json.loads(l) for l in p.read_text().splitlines() if l.strip()):
                triples.add((r.get("theorem_statement", ""),
                             r.get("state_before", ""), r.get("tactic", "")))
    for r in _read(TRAIN):
        t = (r.get("theorem_statement", ""), r.get("state_before", ""), r.get("tactic", ""))
        assert t not in triples, f"v18 leak: {r['theorem_name']} / {r['tactic']!r}"


def test_seeds_use_mathlib_import():
    for s in _read(SEEDS):
        assert s.get("imports") == ["import Mathlib"]
        assert s.get("mathlib") is True
        assert "state_before" in s and s["state_before"].strip()
