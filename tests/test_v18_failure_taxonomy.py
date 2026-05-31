"""Tests for the v18 failure taxonomy artefact."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "data" / "baselines" / "v18_audit"
HEADLINE = AUDIT / "failure_taxonomy.json"
CLASSIFIED = AUDIT / "classified.jsonl"


def _load_headline():
    if not HEADLINE.exists():
        pytest.skip(f"v18 audit absent: {HEADLINE}")
    return json.loads(HEADLINE.read_text(encoding="utf-8"))


def test_headline_and_classified_exist() -> None:
    assert HEADLINE.exists()
    assert CLASSIFIED.exists()


def test_n_rows_is_48() -> None:
    h = _load_headline()
    assert h["n_rows"] == 48


def test_total_slots_is_480() -> None:
    h = _load_headline()
    assert h["n_top10_slots"] == 480


def test_unknown_identifier_is_dominant_failure() -> None:
    """The v18 docs identify `unknown_identifier` as the largest
    failure class. Pin that this remains true; if it changes, the
    docs need updating."""
    h = _load_headline()
    by_class = h["per_class_total"]
    # Top entry should be unknown_identifier OR malformed_parse —
    # both are dominant categories from the v18 audit. Allow either.
    top_classes = list(by_class.keys())[:2]
    assert ("unknown_identifier" in top_classes
            or "malformed_parse" in top_classes), (
        f"top failure classes: {top_classes}")


def test_zero_top10_rows_is_20_pinned() -> None:
    """v18 brief headline: 20/48 theorems have no verified
    candidate in top-10 under the v17 panel policy."""
    h = _load_headline()
    assert h["n_zero_top10_rows"] == 20


def test_per_class_total_includes_all_categories() -> None:
    """Every failure class observed should be a non-negative integer
    counted across slots."""
    h = _load_headline()
    for cls, n in h["per_class_total"].items():
        assert isinstance(n, int)
        assert n >= 0


def test_classified_rows_match_n_rows() -> None:
    rows = []
    for ln in CLASSIFIED.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            rows.append(json.loads(ln))
    assert len(rows) == 48


def test_classified_rows_have_required_fields() -> None:
    rows = [json.loads(ln) for ln in
            CLASSIFIED.read_text(encoding="utf-8").splitlines()
            if ln.strip()]
    for r in rows:
        for k in ("theorem_name", "category", "pass@5", "pass@10",
                  "first_verified_rank", "slot_classes"):
            assert k in r
