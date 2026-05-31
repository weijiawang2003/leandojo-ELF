"""Tests for the v22 balanced multi-category training pools (Part 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BROAD = ROOT / "data" / "processed" / "v22_balanced_broad"
V18_ROOT = ROOT / "data" / "processed" / "v18_broad_core"
CONFIGS = ("A_mixed", "B_oversample", "C_undersample", "D_loss_weighted",
           "E_plus_exists")


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"v22 balanced artefact absent: {p}")
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _rows(cfg: str):
    return _read(BROAD / cfg / "train_rows.jsonl")


def _summary(cfg: str):
    p = BROAD / cfg / "summary.json"
    if not p.exists():
        pytest.skip(f"missing {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def test_v22_balanced_configs_exist():
    for cfg in CONFIGS:
        assert (BROAD / cfg / "train_rows.jsonl").exists(), f"missing {cfg}"
        assert (BROAD / cfg / "summary.json").exists(), f"missing {cfg} summary"


def test_v22_mixed_is_alias_of_plus_exists():
    a = _rows("A_mixed")
    e = _rows("E_plus_exists")
    assert len(a) == len(e)


def test_v22_no_state_after_anywhere():
    for cfg in CONFIGS:
        for r in _rows(cfg):
            assert "state_after" not in r, f"{cfg} row has state_after"


def test_v22_source_tags_preserved():
    # every mixed row carries a corpus_source provenance tag.
    rows = _rows("A_mixed")
    assert all(r.get("corpus_source") for r in rows), "missing corpus_source"
    srcs = {r["corpus_source"] for r in rows}
    assert "v22_exists_corpus" in srcs, "exists corpus not merged in"


def test_v22_no_v18_name_leak():
    names = set()
    for fn in ("train.jsonl", "val.jsonl", "test.jsonl"):
        p = V18_ROOT / fn
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                o = json.loads(ln)
                if o.get("theorem_name"):
                    names.add(o["theorem_name"])
    for cfg in CONFIGS:
        for r in _rows(cfg):
            assert r.get("theorem_name") not in names, \
                f"{cfg} leaks v18 name {r.get('theorem_name')}"


def test_v22_oversample_raises_minority():
    """B oversamples destruct_exists toward the cap, never below A."""
    a = _summary("A_mixed")["by_operation"]
    b = _summary("B_oversample")["by_operation"]
    # destruct_exists is the fragile minority op the experiment targets.
    assert b.get("destruct_exists", 0) >= a.get("destruct_exists", 0)
    # oversampling only adds rows (deterministic repetition).
    assert _summary("B_oversample")["n_total"] >= _summary("A_mixed")["n_total"]


def test_v22_undersample_caps_majority():
    """C caps every operation at the median; total is smaller than A."""
    c = _summary("C_undersample")
    assert c["n_total"] <= _summary("A_mixed")["n_total"]
    median = c.get("median_cap")
    if median is not None:
        for op, n in c["by_operation"].items():
            assert n <= median, f"{op}={n} exceeds median cap {median}"


def test_v22_loss_weights_sidecar():
    d = BROAD / "D_loss_weighted"
    if not (d / "row_weights.jsonl").exists():
        pytest.skip("D weights sidecar absent")
    w = _read(d / "row_weights.jsonl")
    assert len(w) == len(_rows("D_loss_weighted"))
    assert all("weight" in x for x in w)
    s = _summary("D_loss_weighted")
    # D is documented as advisory (current trainer has no per-row hook).
    assert s.get("applied") is False


def test_v22_balanced_summary_honesty():
    for cfg in CONFIGS:
        s = _summary(cfg)
        assert s.get("uses_state_after") is False
        assert s.get("uses_manual_oracle") is False
