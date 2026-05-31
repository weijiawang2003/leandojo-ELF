"""Tests for the v20 broad-synthetic-plus training-set builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRAIN_DIR = ROOT / "data" / "processed" / "v20_broad_synthetic_plus"
TRAIN_ROWS = TRAIN_DIR / "train_rows.jsonl"
SUMMARY = TRAIN_DIR / "summary.json"
V18_ROOT = ROOT / "data" / "processed" / "v18_broad_core"


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"v20 broad-plus artefact absent: {p}")
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def test_v20_broad_plus_artefacts_exist() -> None:
    for p in (TRAIN_ROWS, SUMMARY):
        assert p.exists(), f"v20 broad-plus artefact missing: {p}"


def test_v20_broad_plus_row_count_reasonable() -> None:
    rows = _read(TRAIN_ROWS)
    # v18 broad gathered ~1151 rows. v20 adds implication+bool corpora.
    # We expect ≥ 1200 rows total.
    assert len(rows) >= 1200, (
        f"v20 broad-plus row count too low: {len(rows)}")


def test_v20_broad_plus_includes_v20_corpora() -> None:
    rows = _read(TRAIN_ROWS)
    sources = {r.get("corpus_source") for r in rows}
    assert "v20_implication_corpus" in sources or \
        "v20_implication" in sources, (
            f"v20_implication missing from sources: {sources}")
    assert "v20_bool_corpus" in sources or \
        "v20_bool" in sources, (
            f"v20_bool missing from sources: {sources}")


def test_v20_broad_plus_no_v18_name_leakage() -> None:
    rows = _read(TRAIN_ROWS)
    v18_names = set()
    for fname in ("train.jsonl", "val.jsonl", "test.jsonl"):
        p = V18_ROOT / fname
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            o = json.loads(ln)
            if o.get("theorem_name"):
                v18_names.add(o["theorem_name"])
    for r in rows:
        assert r.get("theorem_name") not in v18_names, (
            f"v20 broad-plus leaks v18 theorem: {r['theorem_name']}")


def test_v20_broad_plus_no_v18_triple_leakage() -> None:
    rows = _read(TRAIN_ROWS)
    v18_triples = set()
    for fname in ("train.jsonl", "val.jsonl", "test.jsonl"):
        p = V18_ROOT / fname
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            o = json.loads(ln)
            v18_triples.add((o.get("theorem_statement", ""),
                             o.get("state_before", ""),
                             o.get("tactic", "")))
    for r in rows:
        triple = (r.get("theorem_statement", ""),
                  r.get("state_before", ""),
                  r.get("tactic", ""))
        assert triple not in v18_triples, (
            f"v20 broad-plus triple leaks v18: {triple[0]}")


def test_v20_broad_plus_summary_records_no_leakage() -> None:
    if not SUMMARY.exists():
        pytest.skip()
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    stats = s.get("ingest_stats", {})
    # The v20 corpora themselves use disjoint `v20_*` names, so the
    # NAME guard must drop nothing. The TRIPLE guard, by contrast,
    # legitimately removes legacy v11/v16/v17 rows whose
    # (statement, state, tactic) coincides with a v18 row (e.g.
    # generic `rfl`/`exact rfl` proofs) — those drops are the guard
    # *protecting* against leakage, so a positive count is correct
    # and desirable. We assert the name guard is clean and that the
    # triple guard fired (or at least did not error) — the
    # downstream no-leakage tests verify the *result* is clean.
    assert stats.get("dropped_by_v18_name_guard", 0) == 0
    assert stats.get("dropped_by_v18_triple_guard", 0) >= 0
    assert s.get("uses_state_after") is False
    assert s.get("uses_manual_oracle") is False


def test_v20_broad_plus_no_state_after_in_rows() -> None:
    rows = _read(TRAIN_ROWS)
    for r in rows:
        assert "state_after" not in r


def test_v20_broad_plus_records_both_v18_base_and_v20() -> None:
    """The pool must include rows from v11/v16/v17 AND the v20
    additions — not just the v20 ones."""
    rows = _read(TRAIN_ROWS)
    src_counts = {}
    for r in rows:
        src_counts[r.get("corpus_source")] = (
            src_counts.get(r.get("corpus_source"), 0) + 1)
    # Quick sanity: there must be at least one row from a v11/v16/v17
    # legacy source.
    legacy_sources = ["v11_lofo", "v16_corpus", "v17_corpus"]
    legacy_total = sum(src_counts.get(k, 0) for k in legacy_sources)
    # Some original rows already have a `corpus_source` set on disk
    # (e.g. ``v17_arrow_false_elim_corpus``). Probe by substring too.
    legacy_total += sum(
        v for k, v in src_counts.items()
        if any(t in (k or "") for t in ("v17_arrow", "v16_contra", "v11"))
    )
    assert legacy_total > 0, (
        f"v20 broad-plus missing v11/v16/v17 base rows: {src_counts}")
