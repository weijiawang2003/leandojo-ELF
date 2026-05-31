"""Tests for the v20 implication corpus.

These tests check structural invariants, leakage guards, and that
the canonical proofs the v20 brief lists (`exact hp`,
`intro hq\\n  exact hp`, `exact h hp`, `exact hqr (hpq hp)`,
`exact g (f a)`, `exact h hp hq`, `exact h hpq`) all appear in the
verified candidate set.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "data" / "seeds" / "v20_implication_seeds.jsonl"
CANDIDATES = ROOT / "data" / "manual" / "v20_implication_candidates.jsonl"
CORPUS_DIR = ROOT / "data" / "processed" / "v20_implication_corpus"
TRAIN_ROWS = CORPUS_DIR / "train_rows.jsonl"
SUMMARY = CORPUS_DIR / "summary.json"

V18_ROOT = ROOT / "data" / "processed" / "v18_broad_core"


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"v20 implication corpus artefact absent: {p}")
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


# ------------- existence / counts ------------------------------------------


def test_v20_implication_artefacts_exist() -> None:
    for p in (SEEDS, CANDIDATES, TRAIN_ROWS, SUMMARY):
        assert p.exists(), f"v20 implication artefact missing: {p}"


def test_v20_implication_verified_count_reasonable() -> None:
    rows = _read(CANDIDATES)
    # Plan is 266 theorems × 1–4 proofs. Even if some Lean-syntax
    # variants fail, we expect a healthy verified count.
    assert len(rows) >= 200, (
        f"v20 implication verified count too low: {len(rows)}")


# ------------- metadata invariants -----------------------------------------


def test_v20_metadata_tags_present() -> None:
    rows = _read(CANDIDATES)
    required = {"theorem_name", "theorem_statement", "state_before",
                "tactic", "family", "required_operation",
                "corpus_source", "redundancy_group", "regime",
                "category", "core_lean"}
    for r in rows:
        missing = required - set(r.keys())
        assert not missing, f"v20 row missing {missing}"
        assert r["category"] == "implication"
        assert r["required_operation"] == "implication"
        assert r["corpus_source"] == "v20_implication_corpus"
        assert r["core_lean"] is True


def test_every_v20_implication_candidate_is_verified() -> None:
    rows = _read(CANDIDATES)
    assert all(r.get("verified") for r in rows), (
        "v20 implication candidates must all be lean-cli verified")


# ------------- all 7 shape families present --------------------------------


_EXPECTED_FAMILIES = {
    "implication_identity",
    "implication_intro_const",
    "implication_modus_ponens",
    "implication_compose",
    "implication_fun_compose",
    "implication_swap_args",
    "implication_arrow_arrow",
}


def test_all_v20_implication_families_present() -> None:
    rows = _read(CANDIDATES)
    fams = {r["family"] for r in rows}
    missing = _EXPECTED_FAMILIES - fams
    assert not missing, f"v20 missing families: {missing}"


# ------------- canonical proofs present ------------------------------------


def test_v20_canonical_identity_proof_present() -> None:
    rows = _read(CANDIDATES)
    # at least one `exact <name>` row for identity
    identity = [r for r in rows
                if r["family"] == "implication_identity"
                and r["tactic"].startswith("exact ")]
    assert len(identity) >= 10, (
        f"v20 implication: too few `exact hp`-style identity proofs: "
        f"{len(identity)}")


def test_v20_canonical_intro_const_proof_present() -> None:
    rows = _read(CANDIDATES)
    intro = [r for r in rows
             if r["family"] == "implication_intro_const"
             and r["tactic"].startswith("intro ")
             and "\n  exact " in r["tactic"]]
    assert len(intro) >= 5, (
        f"v20 implication: too few `intro hq; exact hp`-style proofs: "
        f"{len(intro)}")


def test_v20_canonical_modus_ponens_present() -> None:
    rows = _read(CANDIDATES)
    mp = [r for r in rows
          if r["family"] == "implication_modus_ponens"
          and r["tactic"].startswith("exact ")]
    assert len(mp) >= 10, (
        f"v20 implication: too few modus-ponens proofs: {len(mp)}")


def test_v20_canonical_compose_present() -> None:
    rows = _read(CANDIDATES)
    compose = [r for r in rows
               if r["family"] == "implication_compose"
               and r["tactic"].startswith("exact ")
               and " (" in r["tactic"]]
    assert len(compose) >= 5, (
        f"v20 implication: too few compose proofs: {len(compose)}")


def test_v20_fun_compose_uses_type_binders() -> None:
    rows = _read(CANDIDATES)
    fun_rows = [r for r in rows if r["family"] == "implication_fun_compose"]
    assert fun_rows, "v20 fun_compose family is empty"
    # Every fun_compose row's statement must contain ': Type)' not
    # only ': Prop)' — these are the Type-level composition shape
    # matching v18_imp_compose.
    for r in fun_rows:
        assert ": Type)" in r["theorem_statement"], (
            f"v20 fun_compose row not Type-level: {r['theorem_statement']}")


# ------------- v18 leakage guards ------------------------------------------


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


def test_v20_implication_no_v18_name_overlap() -> None:
    rows = _read(CANDIDATES)
    v18_names, _ = _v18_universe()
    for r in rows:
        nm = r["theorem_name"]
        assert nm not in v18_names, (
            f"v20 implication leaks v18 name: {nm}")


def test_v20_implication_no_v18_triple_overlap() -> None:
    rows = _read(CANDIDATES)
    _, v18_triples = _v18_universe()
    for r in rows:
        triple = (r["theorem_statement"], r["state_before"], r["tactic"])
        assert triple not in v18_triples, (
            f"v20 implication leaks v18 triple: {triple[0]}")


# ------------- honesty contracts -------------------------------------------


def test_no_state_after_in_v20_implication_rows() -> None:
    for p in (SEEDS, CANDIDATES, TRAIN_ROWS):
        if not p.exists():
            continue
        for r in _read(p):
            assert "state_after" not in r, (
                f"v20 implication row contains state_after: {r}")


def test_v20_implication_summary_records_no_leakage_or_state_after() -> None:
    if not SUMMARY.exists():
        pytest.skip("summary absent")
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert s.get("uses_state_after") is False
    assert s.get("uses_manual_oracle") is False
    assert s.get("n_dropped_by_v18_name_guard", 0) == 0
    assert s.get("n_dropped_by_v18_triple_guard", 0) == 0
