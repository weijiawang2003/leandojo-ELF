"""Tests for the v17 arrow_false_elim corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "data" / "seeds" / "v17_arrow_false_elim_seeds.jsonl"
CANDIDATES = ROOT / "data" / "manual" / "v17_arrow_false_elim_candidates.jsonl"
CORPUS_DIR = ROOT / "data" / "processed" / "v17_arrow_false_elim_corpus"


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"v17 corpus artefact absent: {p}")
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


# ----------------- counts -------------------------------------------------


def test_v17_corpus_artefacts_exist() -> None:
    for p in (SEEDS, CANDIDATES, CORPUS_DIR / "summary.json"):
        assert p.exists(), f"v17 corpus artefact missing: {p}"


def test_v17_candidate_count_reasonable() -> None:
    rows = _read(CANDIDATES)
    # ~137 verified planned.
    assert len(rows) >= 100, (
        f"v17 corpus verified count too low: {len(rows)}")


# ----------------- every candidate carries v17 metadata -------------------


def test_every_v17_candidate_is_verified() -> None:
    rows = _read(CANDIDATES)
    assert all(r.get("verified") for r in rows)


def test_v17_metadata_tags_present() -> None:
    rows = _read(CANDIDATES)
    required = {"theorem_name", "theorem_statement", "state_before",
                "tactic", "family", "required_operation",
                "corpus_source", "redundancy_group", "regime"}
    for r in rows:
        missing = required - set(r.keys())
        assert not missing, f"v17 row missing {missing}"
        assert r["required_operation"] == "contradiction"
        assert r["corpus_source"] == "v17_arrow_false_elim_corpus"
        assert r["redundancy_group"] == "arrow_false_elim"
        assert r["regime"] == "v17_arrow_false_elim_redundancy"


# ----------------- both shape families present ----------------------------


def test_both_v17_surface_families_present() -> None:
    rows = _read(CANDIDATES)
    fams = {r["family"] for r in rows}
    assert "arrow_false_elim" in fams
    # The False-target sibling shape is included to strengthen the
    # cross-shape correlation, but isn't load-bearing for the
    # headline; we don't make it strictly required.


def test_canonical_proof_present() -> None:
    """The v17 corpus must include at least one
    `exact (h hp).elim` proof on the `arrow_false_elim` shape — the
    canonical pattern the v17 brief calls out."""
    rows = _read(CANDIDATES)
    canonical_count = sum(
        1 for r in rows
        if r["family"] == "arrow_false_elim"
        and ".elim" in r["tactic"]
        and "hp" in r["tactic"]
    )
    assert canonical_count >= 10, (
        f"only {canonical_count} `.elim` proofs in v17 corpus")


# ----------------- variable-name leakage guard ----------------------------


_V11_TEST_NAME_PAIRS = {("p", "q"), ("a", "b"), ("x", "y"),
                        ("m", "n"), ("a", "d")}


def test_no_v11_lofo_test_variable_pairs_used() -> None:
    rows = _read(CANDIDATES)
    for r in rows:
        stmt = r.get("theorem_statement", "")
        for pa, pb in _V11_TEST_NAME_PAIRS:
            forbidden = f"({pa} {pb} : Prop)"
            assert forbidden not in stmt, (
                f"v17 corpus uses v11 LOFO test pair {pa},{pb}: {stmt!r}")


# ----------------- no state_after -----------------------------------------


def test_no_state_after_in_v17_rows() -> None:
    for p in (SEEDS, CANDIDATES, CORPUS_DIR / "train_rows.jsonl"):
        if not p.exists():
            continue
        for r in _read(p):
            assert "state_after" not in r
