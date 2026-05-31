"""Tests for the v9 corpus generator's pure-Python plumbing.

The lean-cli verification path is NOT exercised here (covered by other tests
and a real-run smoke). We exercise the row construction, the
operation→families table, and the verify-or-refuse contract."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_v9_corpus.py"


def _load():
    spec = importlib.util.spec_from_file_location("build_v9_corpus", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    # dataclasses look up cls.__module__ in sys.modules during introspection;
    # register first so the @dataclass decorator inside the script can find it.
    sys.modules["build_v9_corpus"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_design_recurrence_per_operation():
    """Each operation appears in at least 3 families (the v9 design rule)."""
    m = _load()
    from collections import Counter
    op_counts = Counter(c.operation for c in m.DESIGN)
    for op, n in op_counts.items():
        assert n >= 3, (op, n)


def test_each_cell_has_distinct_theorem_name():
    m = _load()
    names = [f"{c.family}{c.theorem_suffix}" for c in m.DESIGN]
    assert len(set(names)) == len(names)


def test_seed_row_omits_state_after():
    m = _load()
    for c in m.DESIGN:
        row = m.to_seed_row(c)
        for k in row:
            assert not k.startswith("state_after"), k


def test_processed_row_marks_state_after_unreal():
    m = _load()
    for c in m.DESIGN:
        row = m.to_processed_row(c)
        assert row["state_after_is_real"] is False
        # The row dict must NOT contain a `state_after` field with real content;
        # the dataset builder asserts this on emit.
        for k in row:
            if k == "state_after_is_real":
                continue
            assert not k.startswith("state_after"), k


def test_candidate_row_has_required_operation_metadata():
    m = _load()
    for c in m.DESIGN:
        row = m.to_candidate_row(c)
        meta = row["metadata"]
        assert meta["required_operation"] == c.operation
        assert meta["pattern_family"] == c.family
        assert row["candidates"] == [c.tactic]


def test_operation_to_family_count_matches_table():
    """Documented design: 2 operations × 5 families in the validation subset."""
    m = _load()
    from collections import Counter
    op_counts = Counter(c.operation for c in m.DESIGN)
    # 2 ops, 5 families each => 10 cells total
    assert len(m.DESIGN) == 10
    assert set(op_counts.values()) == {5}
    assert set(op_counts.keys()) == {"contradiction", "instantiate_forall"}
