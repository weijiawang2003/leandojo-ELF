"""Tests for the v22 exists corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "data" / "seeds" / "v22_exists_seeds.jsonl"
CANDIDATES = ROOT / "data" / "manual" / "v22_exists_candidates.jsonl"
CORPUS_DIR = ROOT / "data" / "processed" / "v22_exists_corpus"
TRAIN_ROWS = CORPUS_DIR / "train_rows.jsonl"
SUMMARY = CORPUS_DIR / "summary.json"
V18_ROOT = ROOT / "data" / "processed" / "v18_broad_core"


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"v22 exists artefact absent: {p}")
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def test_v22_exists_artefacts_exist():
    for p in (SEEDS, CANDIDATES, TRAIN_ROWS, SUMMARY):
        assert p.exists(), f"missing {p}"


def test_v22_exists_verified_count_reasonable():
    rows = _read(CANDIDATES)
    assert len(rows) >= 200, f"too few verified exists candidates: {len(rows)}"


def test_v22_exists_metadata():
    rows = _read(CANDIDATES)
    req = {"theorem_name", "theorem_statement", "state_before", "tactic",
           "family", "required_operation", "corpus_source", "category",
           "core_lean"}
    for r in rows:
        assert req <= set(r), f"missing {req - set(r)}"
        assert r["category"] == "exists"
        assert r["corpus_source"] == "v22_exists_corpus"
        assert r["core_lean"] is True


def test_v22_exists_all_verified():
    assert all(r.get("verified") for r in _read(CANDIDATES))


def test_v22_exists_has_witness_intro():
    """Must contain anonymous-constructor witness introductions
    `exact ⟨w, h⟩` — the shape the v18 exists_intro_nat needed."""
    rows = _read(CANDIDATES)
    wit = [r for r in rows if r["family"] == "exists_intro_witness"
           and "⟨" in r["tactic"]]
    assert len(wit) >= 40, f"too few witness-intro proofs: {len(wit)}"


def test_v22_exists_has_elim_and_compose():
    rows = _read(CANDIDATES)
    fams = {r["family"] for r in rows}
    # elim/compose use cases-with-intro; at least one family must verify.
    assert "exists_relabel" in fams
    assert ("exists_compose" in fams) or ("exists_elim_prop" in fams)


def test_v22_exists_has_reflexive_witness():
    rows = _read(CANDIDATES)
    rfl = [r for r in rows if "rfl" in r["tactic"] and "⟨" in r["tactic"]]
    assert len(rfl) >= 4, f"too few reflexive-witness proofs: {len(rfl)}"


def _v18_universe():
    names, triples = set(), set()
    for fn in ("train.jsonl", "val.jsonl", "test.jsonl"):
        p = V18_ROOT / fn
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


def test_v22_exists_no_v18_name_leak():
    rows = _read(CANDIDATES)
    names, _ = _v18_universe()
    for r in rows:
        assert r["theorem_name"] not in names


def test_v22_exists_no_v18_triple_leak():
    rows = _read(CANDIDATES)
    _, triples = _v18_universe()
    for r in rows:
        t = (r["theorem_statement"], r["state_before"], r["tactic"])
        assert t not in triples


def test_v22_exists_no_state_after():
    for p in (SEEDS, CANDIDATES, TRAIN_ROWS):
        if not p.exists():
            continue
        for r in _read(p):
            assert "state_after" not in r


def test_v22_exists_summary_honesty():
    if not SUMMARY.exists():
        pytest.skip()
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert s.get("uses_state_after") is False
    assert s.get("uses_manual_oracle") is False
    assert s.get("n_dropped_by_v18_name_guard", 0) == 0
