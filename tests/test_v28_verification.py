"""v28 Part 3 — corpus integrity + gold-sampling invariants (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTEGRITY = ROOT / "data" / "baselines" / "v28_corpus_integrity" / "report.json"

pytestmark = pytest.mark.skipif(not INTEGRITY.exists(), reason="v28 integrity report not generated")


def test_corpus_integrity_sound_and_complete():
    r = json.loads(INTEGRITY.read_text())
    assert r["integrity_ok"] is True
    assert r["n_verified_regressions"] == 0
    assert r["verified_still_pass"] == r["n_verified"]
    assert r["n_failed_now_pass"] == 0


def test_gold_sampling_zero_mismatches_all_categories():
    r = json.loads(INTEGRITY.read_text())
    assert r["gold_sample_size"] >= 20
    assert r["n_gold_mismatches"] == 0
    assert r["n_gold_false_positives"] == 0
    assert r["trusted_sound_on_sample"] is True
    # the sample spans every category in the corpus
    assert len(r["gold_sample_by_category"]) >= 6


def test_honesty_flags():
    r = json.loads(INTEGRITY.read_text())
    assert r["uses_state_after"] is False
    assert r["uses_manual_oracle"] is False
    assert "TrustedMathlibVerifier" in r["verifier"]
    assert "GoldMathlibVerifier" in r["verifier"]
