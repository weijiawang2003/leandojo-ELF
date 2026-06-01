"""v29 Part 4 — corpus integrity + gold sampling (reads the integrity report)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "data" / "baselines" / "v29_corpus_integrity" / "report.json"

pytestmark = pytest.mark.skipif(not REP.exists(), reason="v29 corpus integrity not run")


def _report():
    return json.loads(REP.read_text())


def test_integrity_ok_and_no_regressions():
    r = _report()
    assert r["integrity_ok"] is True
    assert r["n_verified_regressions"] == 0
    assert r["n_failed_now_pass"] == 0


def test_gold_sample_clean_and_broad():
    r = _report()
    assert r["gold_sample_size"] >= 30, "gold sample must be >= 30 verified candidates"
    assert r["n_gold_false_positives"] == 0, "trusted verifier must be sound vs gold"
    assert r["n_gold_mismatches"] == 0
    # every category represented in the gold sample
    assert len(r["gold_sample_by_category"]) >= 5


def test_zero_coverage_gaps():
    assert _report()["n_zero_success_theorems"] == 0


def test_honesty_flags():
    r = _report()
    assert r["uses_state_after"] is False
    assert r["uses_manual_oracle"] is False
    assert "Trusted" in r["verifier"] and "Gold" in r["verifier"]
