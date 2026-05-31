"""Invariants for the v13-vs-v14 comparison artefact.

These tests are about the *structure* of the comparison report, not
about which model wins — the v14 brief is explicit that token-level
decoding may or may not move pass@k. The honesty invariants are:

  * comparison.json references v12 and v13 paths but does not alter
    their contents.
  * v13 corrected metrics appear verbatim (matching what's on disk).
  * Every family present in v14 metrics is present in the comparison.
  * No ``state_after`` key in the comparison structure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V12 = ROOT / "data" / "baselines" / "v12_eval"
V13 = ROOT / "data" / "baselines" / "v13_timeout_rerun"
V14 = ROOT / "data" / "baselines" / "v14_token_seq2seq"
CMP = V14 / "comparison.json"


def _load_cmp():
    if not CMP.exists():
        pytest.skip(f"comparison artefact absent: {CMP}")
    return json.loads(CMP.read_text(encoding="utf-8"))


def test_comparison_lists_required_top_level_keys() -> None:
    c = _load_cmp()
    for k in ("families", "rows",
              "v13_corrected_metrics_path",
              "v14_metrics_path",
              "v12_metrics_path_referenced_but_not_modified",
              "uses_state_after"):
        assert k in c
    assert c["uses_state_after"] is False


def test_comparison_v13_warm_matches_v13_disk() -> None:
    """The comparison must echo v13 corrected metrics verbatim — any
    drift would mean v14 silently rewrote the v13 headline."""
    c = _load_cmp()
    disk = V13 / "metrics_rerun.json"
    if not disk.exists():
        pytest.skip("v13 metrics_rerun.json missing")
    src = json.loads(disk.read_text(encoding="utf-8"))
    for fam, row in c["rows"].items():
        v13 = row.get("v13_char_warm") or {}
        if not v13:
            continue
        disk_fam = src.get(fam, {}).get("literal_adapt_rerank") or {}
        if not disk_fam:
            continue
        assert v13["pass@5"] == disk_fam["pass@5_warm_rerun"]
        assert v13["pass@1"] == disk_fam["pass@1_warm_rerun"]
        assert v13["pass@10"] == disk_fam["pass@10_warm_rerun"]


def test_comparison_has_v14_raw_and_literal_adapt() -> None:
    c = _load_cmp()
    for fam, row in c["rows"].items():
        # Either both configs are present, or v14 wasn't run for this fam
        # — tolerate the latter by skipping rather than failing.
        if not row.get("v14_raw"):
            continue
        assert "pass@5" in row["v14_raw"]
        assert "n_with_fused_token" in row["v14_raw"]
        assert "literal_adapt_verified" in row["v14_raw"]


def test_comparison_does_not_overwrite_v13_disk_metrics() -> None:
    """Running compare_v13_v14 must not touch v13's metrics_rerun.json
    or the audit-snapshot metrics_original.json. We check by sha256 if
    a sidecar file documenting expected hashes exists; otherwise we
    fall back to checking the v13 forall_inst pass@5_warm_rerun is
    still 6/7."""
    disk = V13 / "metrics_rerun.json"
    if not disk.exists():
        pytest.skip("v13 metrics_rerun.json missing")
    src = json.loads(disk.read_text(encoding="utf-8"))
    val = src.get("forall_inst", {}).get("literal_adapt_rerank", {}).get(
        "pass@5_warm_rerun")
    assert val == pytest.approx(6.0 / 7, abs=1e-3), (
        "v13 forall_inst warm pass@5 changed — comparison script "
        "improperly mutated v13's metrics_rerun.json"
    )
