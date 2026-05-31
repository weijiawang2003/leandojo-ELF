"""Tests for the v18 broad-core corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "data" / "seeds" / "v18_broad_core_seeds.jsonl"
CANDS = ROOT / "data" / "manual" / "v18_broad_core_candidates.jsonl"
VERIF = ROOT / "data" / "traces" / "v18_broad_core_verified.jsonl"
FAIL = ROOT / "data" / "traces" / "v18_broad_core_failed.jsonl"
PROCESSED = ROOT / "data" / "processed" / "v18_broad_core"


def _read(p: Path):
    if not p.exists():
        pytest.skip(f"v18 corpus artefact absent: {p}")
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def test_corpus_files_exist() -> None:
    for p in (SEEDS, CANDS, VERIF, FAIL, PROCESSED / "summary.json"):
        assert p.exists(), f"v18 corpus artefact missing: {p}"


def test_seed_count_at_least_48() -> None:
    rows = _read(SEEDS)
    assert len(rows) >= 48


def test_ten_categories_covered() -> None:
    rows = _read(SEEDS)
    cats = {r["category"] for r in rows}
    required = {"implication", "conjunction", "disjunction", "negation",
                "equality_rewrite", "exists", "forall", "nat_succ",
                "bool", "list"}
    missing = required - cats
    assert not missing, f"v18 corpus missing categories: {missing}"


def test_every_seed_carries_no_mathlib_no_state_after() -> None:
    rows = _read(SEEDS)
    for r in rows:
        assert r.get("uses_mathlib") is False, (
            f"v18 seed {r.get('theorem_name')} uses_mathlib != False")
        assert "state_after" not in r
        # imports must be empty (core Lean only)
        assert not r.get("imports"), (
            f"v18 seed {r.get('theorem_name')} has imports: {r.get('imports')}")


def test_every_candidate_has_verification_label() -> None:
    rows = _read(CANDS)
    for r in rows:
        assert "verified" in r
        assert isinstance(r["verified"], bool)
        assert r.get("uses_mathlib") is False


def test_verified_count_above_100() -> None:
    """The corpus design targets ~109 verified candidates. Pin a
    floor."""
    rows = _read(CANDS)
    n_v = sum(1 for r in rows if r.get("verified"))
    assert n_v >= 100, (
        f"v18 verified count too low: {n_v}; expected ≥100")


def test_zero_zero_success_theorems() -> None:
    """Every v18 theorem must have at least one verified candidate."""
    s = json.loads((PROCESSED / "summary.json").read_text(encoding="utf-8"))
    assert s["n_zero_success_theorems"] == 0, (
        f"v18 has zero-success theorems: "
        f"{s.get('zero_success_theorems')}"
    )


def test_split_is_theorem_level_not_candidate_level() -> None:
    """Train / val / test rows must come from disjoint theorem-name
    sets (theorem-level split)."""
    splits = {}
    for nm in ("train", "val", "test"):
        rows = _read(PROCESSED / f"{nm}.jsonl")
        splits[nm] = {r["theorem_name"] for r in rows}
    assert not (splits["train"] & splits["val"])
    assert not (splits["train"] & splits["test"])
    assert not (splits["val"] & splits["test"])


def test_summary_metadata() -> None:
    s = json.loads((PROCESSED / "summary.json").read_text(encoding="utf-8"))
    assert s["uses_state_after"] is False
    assert s["uses_mathlib"] is False
    assert s["n_categories"] == 10
    assert s["n_theorems_planned"] >= 48
