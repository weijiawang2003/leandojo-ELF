"""Tests for the v24 residual shape corpus (Parts 2-3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "data" / "seeds" / "v24_residual_shape_seeds.jsonl"
CAND = ROOT / "data" / "manual" / "v24_residual_shape_candidates.jsonl"
CORPUS = ROOT / "data" / "processed" / "v24_residual_shape_corpus"
TRAIN = CORPUS / "train_rows.jsonl"
SUMMARY = CORPUS / "summary.json"
V18 = ROOT / "data" / "processed" / "v18_broad_core"

FAMILIES = {"or_intro", "or_elim", "conj_reassoc", "neg_of_or",
            "exists_eq_rev", "nat_zero_add", "nat_succ_inj", "list_append_nil"}


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"absent: {p}")
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_corpus_artifacts_exist():
    for p in (SEEDS, CAND, TRAIN, SUMMARY):
        assert p.exists(), f"missing {p}"


def test_all_candidates_verified():
    assert all(r.get("verified") for r in _read(CAND))


def test_families_covered():
    fams = {r["family"] for r in _read(TRAIN)}
    assert FAMILIES <= fams, f"missing {FAMILIES - fams}"


def test_summary_honest_and_complete():
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert s["uses_state_after"] is False
    assert s["uses_manual_oracle"] is False
    assert s["uses_mathlib"] is False
    assert s["n_candidates_verified"] >= 100
    assert s["n_zero_success_theorems"] == 0
    assert s["n_dropped_by_v18_name_guard"] == 0


def test_no_state_after():
    for p in (SEEDS, CAND, TRAIN):
        for r in _read(p):
            assert "state_after" not in r


def test_metadata_and_targets():
    for r in _read(CAND):
        assert r["corpus_source"] == "v24_residual_shape_corpus"
        assert r["core_lean"] is True
        assert r["target_v18_failure"].startswith("v18_")


def test_no_v18_leakage():
    names, triples = set(), set()
    for fn in ("train.jsonl", "val.jsonl", "test.jsonl"):
        p = V18 / fn
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                o = json.loads(ln)
                names.add(o.get("theorem_name"))
                triples.add((o.get("theorem_statement", ""),
                             o.get("state_before", ""), o.get("tactic", "")))
    for r in _read(CAND):
        assert r["theorem_name"] not in names
        assert (r["theorem_statement"], r["state_before"], r["tactic"]) not in triples
