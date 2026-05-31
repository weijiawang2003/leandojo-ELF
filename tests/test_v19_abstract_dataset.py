"""Tests for the v19 abstract dataset."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data" / "processed" / "v19_abstract_synthetic_train"
V18S = ROOT / "data" / "processed" / "v19_abstract_v18_split"


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"v19 abstract artefact absent: {p}")
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def test_artefacts_exist() -> None:
    for p in (SYN / "train.jsonl", SYN / "val.jsonl", SYN / "summary.json"):
        assert p.exists(), f"v19 abstract artefact missing: {p}"


def test_synthetic_summary_has_expected_keys() -> None:
    s = json.loads((SYN / "summary.json").read_text(encoding="utf-8"))
    assert s["uses_state_after"] is False
    for k in ("n_raw_total", "n_clean_total", "n_train_rows",
              "n_val_rows", "n_dropped_v18_name_leakage",
              "n_dropped_v18_triple_leakage", "drop_reasons"):
        assert k in s


def test_synthetic_zero_reconstruct_failures() -> None:
    """The v19 abstraction must round-trip cleanly: every row that
    *did* abstract must reconstruct to its original tactic. Drops
    here are accounted in ``n_dropped_abstract_or_reconstruct``."""
    s = json.loads((SYN / "summary.json").read_text(encoding="utf-8"))
    # The v19 abstract module pin: 0 reconstruct failures across the
    # synthetic corpus.
    assert s["n_dropped_abstract_or_reconstruct"] == 0, (
        f"v19 reconstruct failures: {s['drop_reasons']}")


def test_every_synthetic_row_has_abstract_pair() -> None:
    rows = _read(SYN / "train.jsonl")[:100]
    for r in rows:
        assert "state_before_abstract" in r
        assert "tactic_abstract" in r
        assert "placeholder_map_original_to_abstract" in r
        assert "placeholder_map_abstract_to_original" in r
        # The maps must be inverse on string keys/values.
        fwd = r["placeholder_map_original_to_abstract"]
        rev = r["placeholder_map_abstract_to_original"]
        for name, ph in fwd.items():
            assert rev.get(ph) == name


def test_v18_leakage_guard_dropped_some_rows() -> None:
    """The v18 corpus shares some shapes with v17 train rows; the
    triple guard should drop at least some entries (otherwise the
    guard is silently bypassed)."""
    s = json.loads((SYN / "summary.json").read_text(encoding="utf-8"))
    # We expect at least 1 row dropped by leakage guards.
    assert s["n_dropped_v18_name_leakage"] + \
        s["n_dropped_v18_triple_leakage"] >= 1


def test_v18_split_files_exist() -> None:
    if not V18S.exists():
        pytest.skip("v18 abstract split missing")
    for n in ("train.jsonl", "val.jsonl", "test.jsonl"):
        assert (V18S / n).exists(), f"v18 abstract split missing {n}"


def test_v18_split_rows_carry_abstract_pair() -> None:
    if not (V18S / "test.jsonl").exists():
        pytest.skip("v18 split test absent")
    for r in _read(V18S / "test.jsonl"):
        assert "state_before_abstract" in r
        assert "tactic_abstract" in r


def test_no_state_after_in_rows() -> None:
    for p in (SYN / "train.jsonl", SYN / "val.jsonl",
              V18S / "train.jsonl", V18S / "val.jsonl",
              V18S / "test.jsonl"):
        if not p.exists():
            continue
        for r in _read(p):
            assert "state_after" not in r
