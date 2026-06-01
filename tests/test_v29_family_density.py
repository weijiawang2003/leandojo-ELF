"""v29 Part 1 — family-density audit (no Lean)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "data" / "baselines" / "v29_family_density" / "report.json"

pytestmark = pytest.mark.skipif(not REP.exists(), reason="v29 family-density audit not run")


def _report():
    return json.loads(REP.read_text())


def test_audit_has_families_and_points():
    r = _report()
    assert r["n_families"] > 50
    assert r["n_effective_density_points"] > 50


def test_density_law_is_monotone_nondecreasing():
    # held-out pass@10 should not DROP as effective training density rises across
    # populated bins (the central v29 claim).
    law = _report()["effective_density_law"]
    order = ["0", "1-3", "4-6", "7-10", "10+"]
    seq = [law[b]["pass@10"] for b in order if law.get(b, {}).get("pass@10") is not None and law[b]["n_heldout"] >= 5]
    assert seq, "no populated density bins"
    assert all(b >= a - 1e-9 for a, b in zip(seq, seq[1:])), f"density law not monotone: {seq}"


def test_density_gate_positive():
    g = _report()["effective_density_gate"]
    if g["pass@10_density_0"] is not None and g["pass@10_density_ge1"] is not None:
        assert g["pass@10_density_ge1"] >= g["pass@10_density_0"] - 1e-9


def test_sparse_families_identified():
    r = _report()
    assert r["n_sparse_families_1_3"] > 0
    fams = {f["family"].split("::")[-1] for f in r["named_target_families"]}
    # the v28-memory named residuals must appear among the flagged sparse targets
    assert {"comp_assoc", "antisymm"} & fams or {"union_subset", "mem_inter_proj"} & fams


def test_no_state_after_flag():
    assert _report().get("uses_state_after") is False
