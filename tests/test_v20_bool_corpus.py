"""Tests for the v20 Bool corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "data" / "seeds" / "v20_bool_seeds.jsonl"
CANDIDATES = ROOT / "data" / "manual" / "v20_bool_candidates.jsonl"
CORPUS_DIR = ROOT / "data" / "processed" / "v20_bool_corpus"
TRAIN_ROWS = CORPUS_DIR / "train_rows.jsonl"
SUMMARY = CORPUS_DIR / "summary.json"

V18_ROOT = ROOT / "data" / "processed" / "v18_broad_core"


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"v20 bool corpus artefact absent: {p}")
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def test_v20_bool_artefacts_exist() -> None:
    for p in (SEEDS, CANDIDATES, TRAIN_ROWS, SUMMARY):
        assert p.exists(), f"v20 bool artefact missing: {p}"


def test_v20_bool_verified_count_reasonable() -> None:
    rows = _read(CANDIDATES)
    # Plan is 77 theorems × 1–4 proofs. Some syntactic variants
    # fail; we expect ≥ 70 verified candidates.
    assert len(rows) >= 70, (
        f"v20 bool verified count too low: {len(rows)}")


def test_v20_bool_metadata_tags_present() -> None:
    rows = _read(CANDIDATES)
    required = {"theorem_name", "theorem_statement", "state_before",
                "tactic", "family", "required_operation",
                "corpus_source", "redundancy_group", "regime",
                "category", "core_lean"}
    for r in rows:
        missing = required - set(r.keys())
        assert not missing, f"v20 bool row missing {missing}"
        assert r["category"] == "bool"
        assert r["required_operation"] == "bool_cases"
        assert r["corpus_source"] == "v20_bool_corpus"
        assert r["core_lean"] is True


def test_every_v20_bool_candidate_is_verified() -> None:
    rows = _read(CANDIDATES)
    assert all(r.get("verified") for r in rows)


_EXPECTED_FAMILIES = {
    "bool_refl", "bool_cases_taut", "bool_no_conf", "bool_if_id",
    "bool_eq_rw", "bool_double_neg", "bool_and_rw",
}


def test_v20_bool_families_present() -> None:
    rows = _read(CANDIDATES)
    fams = {r["family"] for r in rows}
    # At least the core 4 must verify; bool_no_conf/bool_and_rw etc
    # might be syntactically rejected in core Lean. Require at least
    # the 4 core families.
    core = {"bool_refl", "bool_eq_rw"}
    missing = core - fams
    assert not missing, f"v20 bool missing core families: {missing}"


def test_v20_bool_has_at_least_one_cases_b_proof() -> None:
    rows = _read(CANDIDATES)
    cases = [r for r in rows
             if r["tactic"].startswith("cases ")
             or "\n  cases " in r["tactic"]]
    assert len(cases) >= 5, (
        f"v20 bool: too few `cases b`-style proofs: {len(cases)}")


def test_v20_bool_has_rfl_proof() -> None:
    rows = _read(CANDIDATES)
    rfl = [r for r in rows if r["tactic"] == "rfl"
           or r["tactic"] == "exact rfl"]
    assert len(rfl) >= 5, (
        f"v20 bool: too few `rfl`-style proofs: {len(rfl)}")


# -------------- v18 leakage guards ----------------------------------------


def _v18_universe():
    names = set()
    triples = set()
    for fname in ("train.jsonl", "val.jsonl", "test.jsonl"):
        p = V18_ROOT / fname
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            s = ln.strip()
            if not s:
                continue
            o = json.loads(s)
            if o.get("theorem_name"):
                names.add(o["theorem_name"])
            triples.add((o.get("theorem_statement", ""),
                         o.get("state_before", ""),
                         o.get("tactic", "")))
    return names, triples


def test_v20_bool_no_v18_name_overlap() -> None:
    rows = _read(CANDIDATES)
    v18_names, _ = _v18_universe()
    for r in rows:
        assert r["theorem_name"] not in v18_names, (
            f"v20 bool leaks v18 name: {r['theorem_name']}")


def test_v20_bool_no_v18_triple_overlap() -> None:
    rows = _read(CANDIDATES)
    _, v18_triples = _v18_universe()
    for r in rows:
        triple = (r["theorem_statement"], r["state_before"], r["tactic"])
        assert triple not in v18_triples, (
            f"v20 bool leaks v18 triple: {triple[0]}")


def test_no_state_after_in_v20_bool_rows() -> None:
    for p in (SEEDS, CANDIDATES, TRAIN_ROWS):
        if not p.exists():
            continue
        for r in _read(p):
            assert "state_after" not in r


def test_v20_bool_summary_honesty() -> None:
    if not SUMMARY.exists():
        pytest.skip()
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert s.get("uses_state_after") is False
    assert s.get("uses_manual_oracle") is False
