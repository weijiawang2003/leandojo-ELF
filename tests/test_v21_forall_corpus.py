"""Tests for the v21 forall-instantiation corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "data" / "seeds" / "v21_forall_seeds.jsonl"
CANDIDATES = ROOT / "data" / "manual" / "v21_forall_candidates.jsonl"
CORPUS_DIR = ROOT / "data" / "processed" / "v21_forall_corpus"
TRAIN_ROWS = CORPUS_DIR / "train_rows.jsonl"
SUMMARY = CORPUS_DIR / "summary.json"
V18_ROOT = ROOT / "data" / "processed" / "v18_broad_core"


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"v21 forall artefact absent: {p}")
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def test_v21_forall_artefacts_exist():
    for p in (SEEDS, CANDIDATES, TRAIN_ROWS, SUMMARY):
        assert p.exists(), f"missing {p}"


def test_v21_forall_verified_count_reasonable():
    rows = _read(CANDIDATES)
    assert len(rows) >= 300, f"too few verified forall candidates: {len(rows)}"


def test_v21_forall_metadata():
    rows = _read(CANDIDATES)
    req = {"theorem_name", "theorem_statement", "state_before", "tactic",
           "family", "required_operation", "corpus_source", "category",
           "core_lean"}
    for r in rows:
        assert req <= set(r), f"missing {req - set(r)}"
        assert r["category"] == "forall"
        assert r["required_operation"] == "instantiate_forall"
        assert r["corpus_source"] == "v21_forall_corpus"
        assert r["core_lean"] is True


def test_v21_forall_all_verified():
    assert all(r.get("verified") for r in _read(CANDIDATES))


def test_v21_forall_has_instantiation_schema():
    """The whole point: the corpus must contain bare `exact h <arg>`
    instantiation proofs (literal and variable)."""
    rows = _read(CANDIDATES)
    lit = [r for r in rows if r["family"] == "forall_inst_literal"
           and r["tactic"].startswith("exact ")]
    var = [r for r in rows if r["family"] == "forall_inst_var"
           and r["tactic"].startswith("exact ")]
    assert len(lit) >= 50, f"too few literal-instantiation proofs: {len(lit)}"
    assert len(var) >= 20, f"too few var-instantiation proofs: {len(var)}"


def test_v21_forall_families_present():
    rows = _read(CANDIDATES)
    fams = {r["family"] for r in rows}
    # The 3 core families must verify; compose/prop may partly fail.
    for must in ("forall_inst_literal", "forall_inst_var", "forall_arrow_inst"):
        assert must in fams, f"family {must} absent"


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


def test_v21_forall_no_v18_name_leak():
    rows = _read(CANDIDATES)
    names, _ = _v18_universe()
    for r in rows:
        assert r["theorem_name"] not in names


def test_v21_forall_no_v18_triple_leak():
    """Critical: must NOT contain v18_forall_inst_at_7's `exact h 7`
    triple etc."""
    rows = _read(CANDIDATES)
    _, triples = _v18_universe()
    for r in rows:
        t = (r["theorem_statement"], r["state_before"], r["tactic"])
        assert t not in triples, f"leaks v18 triple: {t}"


def test_v21_forall_no_state_after():
    for p in (SEEDS, CANDIDATES, TRAIN_ROWS):
        if not p.exists():
            continue
        for r in _read(p):
            assert "state_after" not in r


def test_v21_forall_summary_honesty():
    if not SUMMARY.exists():
        pytest.skip()
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert s.get("uses_state_after") is False
    assert s.get("uses_manual_oracle") is False
    assert s.get("n_dropped_by_v18_name_guard", 0) == 0
