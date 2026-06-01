"""v30 Part 4 — corpus integrity + gold sampling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "data" / "baselines" / "v30_corpus_integrity" / "report.json"

pytestmark = pytest.mark.skipif(not REP.exists(), reason="v30 corpus integrity not run")


def _report():
    return json.loads(REP.read_text())


def test_integrity_ok_no_regressions():
    r = _report()
    assert r["integrity_ok"] is True
    assert r["n_verified_regressions"] == 0
    assert r["n_failed_now_pass"] == 0
    assert r["n_zero_success_theorems"] == 0


def test_gold_clean_and_per_family():
    r = _report()
    assert r["gold_sample_size"] >= 20
    assert r["n_gold_false_positives"] == 0 and r["n_gold_mismatches"] == 0
    assert len(r["gold_sample_by_family"]) >= 6


def test_honesty_flags():
    r = _report()
    assert r["uses_state_after"] is False and r["uses_manual_oracle"] is False
    assert "Trusted" in r["verifier"] and "Gold" in r["verifier"]
