"""Mini-ELF v25 — tests for the Mathlib environment probe (Part 1).

These assert the probe artifact's *shape* and self-consistency. They do
NOT require Mathlib to be installed in CI (the probe JSON is committed as
the record); a `mathlib_available` flag of either value is acceptable, but
if true it must be backed by an `import_mathlib.ok` true result (no faked
availability).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE_JSON = ROOT / "data" / "baselines" / "v25_mathlib_env_probe.json"
PROBE_SCRIPT = ROOT / "scripts" / "probe_v25_mathlib_env.py"


def _load():
    if not PROBE_JSON.exists():
        pytest.skip(f"absent: {PROBE_JSON}")
    return json.loads(PROBE_JSON.read_text(encoding="utf-8"))


def test_probe_script_exists():
    assert PROBE_SCRIPT.exists()


def test_probe_records_both_paths():
    d = _load()
    assert "A_repo" in d["paths"]
    assert "B_scratch" in d["paths"]
    assert "mathlib_available" in d


def test_repo_path_has_no_mathlib():
    # the in-repo minimal project must NOT provide Mathlib (by design)
    d = _load()
    assert d["paths"]["A_repo"]["mathlib_importable"] is False


def test_availability_not_faked():
    d = _load()
    if d.get("mathlib_available"):
        # availability must be backed by a real rc-0 `import Mathlib` compile
        b = d["paths"]["B_scratch"]
        assert b.get("mathlib_importable") is True
        assert b["import_mathlib"]["returncode"] == 0
        assert b["import_mathlib"]["ok"] is True


def test_pinned_lean_and_rev_recorded():
    d = _load()
    assert "leanprover--lean4---v4.30.0" in d["pinned_lean"]
    assert d["mathlib_rev"] == "v4.30.0"
