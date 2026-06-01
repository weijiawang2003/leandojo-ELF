"""v33 Part 1 — remaining-residual audit (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "data" / "baselines" / "v33_remaining_residual" / "report.json"

pytestmark = pytest.mark.skipif(not REP.exists(), reason="v33 residual audit not run")


def _r():
    return json.loads(REP.read_text())


def test_eleven_residuals_none_multistep():
    r = _r()
    assert r["n_residuals"] == 11
    assert r["any_multi_step"] is False
    assert "true_multi_step_gap" not in r["classification_counts"]


def test_subscript_residuals_classified_canonicalization():
    r = _r()
    assert r["classification_counts"].get("canonicalization_gap", 0) == 5


def test_hardened_decode_documented():
    assert "subscript" in _r()["v33_levers"]["hardened_canonical_decode"]
