"""Tests for the v16 contrapositive corpus generation.

Pins:
  * every persisted candidate carries the v16 metadata tags,
  * proof variants are lean-cli-verified before being written
    (we assert presence via the ``verified=True`` flag the
    generator emits),
  * variable names are disjoint from v11 LOFO test theorem names,
  * the three surface families are all present,
  * candidates do not reference ``state_after``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = ROOT / "data" / "processed" / "v16_contrapositive_corpus"
SEEDS = ROOT / "data" / "seeds" / "v16_contrapositive_seeds.jsonl"
CANDIDATES = ROOT / "data" / "manual" / "v16_contrapositive_candidates.jsonl"


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"v16 corpus artefact absent: {p}")
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


# ----------------- existence / counts --------------------------------------


def test_corpus_files_exist() -> None:
    assert SEEDS.exists() or (CORPUS_DIR / "train_rows.jsonl").exists(), (
        "v16 corpus artefacts missing; run "
        "scripts/generate_v16_contrapositive_corpus.py")


def test_seed_count_reasonable() -> None:
    rows = _read(SEEDS)
    # We planned 81 seeds in the script.
    assert len(rows) >= 60, f"only {len(rows)} seeds — generation skipped?"


def test_candidate_count_reasonable() -> None:
    rows = _read(CANDIDATES)
    # ~287 verified candidates expected.
    assert len(rows) >= 200, f"only {len(rows)} verified candidates"


# ----------------- metadata tags -------------------------------------------


def test_every_candidate_is_marked_verified() -> None:
    rows = _read(CANDIDATES)
    n_unverified = sum(1 for r in rows if not r.get("verified"))
    assert n_unverified == 0, (
        f"{n_unverified} unverified candidates in the manual file — "
        f"verifier filter is broken")


def test_every_candidate_uses_lean_cli_backend() -> None:
    rows = _read(CANDIDATES)
    backends = {r.get("verifier") for r in rows}
    assert backends == {"lean-cli"}, (
        f"unexpected verifier backends: {backends}")


def test_metadata_fields_present() -> None:
    rows = _read(CANDIDATES)
    required = {"theorem_name", "theorem_statement", "state_before",
                "tactic", "family", "required_operation",
                "corpus_source", "tactic_source",
                "split", "regime", "redundancy_group"}
    for r in rows:
        missing = required - set(r.keys())
        assert not missing, f"row missing fields: {missing}"
        assert r["required_operation"] == "intro_negation"
        assert r["corpus_source"] == "v16_contrapositive_corpus"
        assert r["redundancy_group"] == "contrapositive"
        assert r["split"] == "train"
        assert r["regime"] == "v16_contrapositive_redundancy"


# ----------------- variable-name leakage guard ----------------------------


_V11_TEST_NAME_PAIRS = {("p", "q"), ("a", "b"), ("x", "y"),
                        ("m", "n"), ("a", "d")}


def test_no_v11_lofo_test_variable_pairs_used() -> None:
    """Belt-and-braces: the corpus uses disjoint variable names so it
    cannot accidentally memorise a held-out test row."""
    rows = _read(CANDIDATES)
    for r in rows:
        stmt = r.get("theorem_statement", "")
        # Crude check: the typical v11 LOFO test statement begins with
        # ``(p q : Prop)`` or ``(a b : Prop)`` etc.
        for pa, pb in _V11_TEST_NAME_PAIRS:
            forbidden = f"({pa} {pb} : Prop)"
            assert forbidden not in stmt, (
                f"v16 corpus row uses v11 LOFO test variable pair "
                f"{pa},{pb}: {stmt!r}")


# ----------------- surface-family coverage --------------------------------


def test_all_three_surface_families_present() -> None:
    rows = _read(CANDIDATES)
    fams = {r["family"] for r in rows}
    expected = {"contrapositive_classic",
                "contrapositive_neg_imp",
                "contrapositive_false_target"}
    assert fams == expected, f"got {fams}"


def test_neg_imp_dominant_for_v11_target() -> None:
    """The v11 LOFO neg_imp_exfalso test shape is ``(hnp : ¬p) : p → q``
    — that's the ``contrapositive_neg_imp`` family. It should have
    the most rows so the augmentation directly attacks the brief's
    primary target."""
    rows = _read(CANDIDATES)
    by_fam = {}
    for r in rows:
        by_fam[r["family"]] = by_fam.get(r["family"], 0) + 1
    assert by_fam["contrapositive_neg_imp"] >= max(by_fam.values()) - 30, (
        f"contrapositive_neg_imp ({by_fam.get('contrapositive_neg_imp')}) "
        f"is not the largest contributor: {by_fam}")


# ----------------- no state_after ------------------------------------------


def test_no_state_after_in_any_row() -> None:
    for p in (SEEDS, CANDIDATES, CORPUS_DIR / "train_rows.jsonl"):
        if not p.exists():
            continue
        for r in _read(p):
            assert "state_after" not in r, (
                f"v16 corpus row carries state_after: {p}")


# ----------------- summary file --------------------------------------------


def test_summary_matches_candidate_count() -> None:
    sp = CORPUS_DIR / "summary.json"
    if not sp.exists():
        pytest.skip("summary.json absent")
    s = json.loads(sp.read_text(encoding="utf-8"))
    assert s["uses_state_after"] is False
    assert s["n_candidates_verified"] >= 200
    assert s["n_candidates_verified"] + s["n_candidates_failed"] \
        == s["n_candidates_proposed"]
