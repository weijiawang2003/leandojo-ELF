"""Unit tests for the v10 redundancy-corpus generator's static design table.

These tests do **not** invoke lean-cli (the verification is exercised end-to-end
by the generator script itself, which refuses to commit unverified cells).
They check the static design and emitted JSONL row shape:

  * theorem_name uniqueness across DESIGN (caught by the generator's own
    SystemExit; we test the constraint explicitly here so a regression is
    flagged by pytest, not only at corpus-build time);
  * every cell has an operation, surface_family, and a non-empty tactic;
  * the generator emits valid JSONL with the required metadata fields, no
    Mathlib imports, and no overlap with prior corpora (basic/hard/PB/v9);
  * forbidden tokens (``sorry``, ``admit``, ``unsafe``) appear in no tactic;
  * theorem-name prefix is ``v10_``;
  * each operation has at least one cell with `requires_*` flag consistent
    with its kind (sanity check on the per-op default-flags table).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_redundancy_corpus as gen  # noqa: E402


def test_design_has_8_operations():
    ops = {c.operation for c in gen.DESIGN}
    expected = {
        "contradiction", "intro_negation", "instantiate_forall",
        "rewrite_eq", "exists_elim", "implication_chain",
        "conjunction_projection", "disjunction_cases",
    }
    assert ops == expected, f"expected 8 ops, got {ops}"


def test_design_has_at_least_3_families_per_operation():
    per_op: dict = {}
    for c in gen.DESIGN:
        per_op.setdefault(c.operation, set()).add(c.surface_family)
    for op, fams in per_op.items():
        # redundancy means *multiple* sibling families per operation; insist on >=3.
        assert len(fams) >= 3, f"op {op} has only {len(fams)} surface families"


def test_design_theorem_names_unique():
    names = [gen.theorem_name(c) for c in gen.DESIGN]
    assert len(names) == len(set(names)), f"duplicate theorem_names: {names}"


def test_design_theorem_names_v10_prefixed():
    for c in gen.DESIGN:
        nm = gen.theorem_name(c)
        assert nm.startswith("v10_"), f"non-v10 name: {nm}"


def test_design_no_overlap_with_prior_corpora():
    """The v10 redundancy seeds must not collide with any existing seed
    theorem_name on disk (basic/hard/planner_blind/v9)."""
    prior_files = [
        ROOT / "data" / "seeds" / "basic_lean_seeds.jsonl",
        ROOT / "data" / "seeds" / "hard_lean_seeds.jsonl",
        ROOT / "data" / "seeds" / "planner_blind_seeds.jsonl",
        ROOT / "data" / "seeds" / "v9_validation_seeds.jsonl",
    ]
    prior_names: set = set()
    for p in prior_files:
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            try:
                prior_names.add(json.loads(s).get("theorem_name"))
            except json.JSONDecodeError:
                pass
    v10_names = {gen.theorem_name(c) for c in gen.DESIGN}
    overlap = v10_names & prior_names
    assert not overlap, f"v10 design overlaps prior corpora: {overlap}"


def test_no_forbidden_tactics():
    for c in gen.DESIGN:
        for bad in ("sorry", "admit", "unsafe"):
            assert bad not in c.tactic, \
                f"{gen.theorem_name(c)} tactic contains forbidden token {bad!r}"


def test_no_mathlib_imports_in_seed_rows():
    for c in gen.DESIGN:
        row = gen.to_seed_row(c)
        assert row["imports"] == [], f"{gen.theorem_name(c)} has imports {row['imports']}"


def test_seed_rows_have_required_metadata():
    required = {
        "difficulty", "expected_success_tactics", "operation", "pattern_family",
        "redundancy_corpus", "redundancy_group", "required_operation",
        "requires_exists_elim", "requires_intro", "requires_quantifier",
        "requires_rewrite", "source", "surface_family",
    }
    for c in gen.DESIGN:
        row = gen.to_seed_row(c)
        keys = set(row["metadata"].keys())
        assert required <= keys, \
            f"{gen.theorem_name(c)} missing metadata keys: {required - keys}"
        assert row["metadata"]["source"] == "redundancy-corpus"
        assert row["metadata"]["redundancy_corpus"] is True
        assert row["metadata"]["redundancy_group"] == c.operation
        assert row["metadata"]["operation"] == c.operation
        assert row["metadata"]["surface_family"] == c.surface_family


def test_candidate_rows_carry_at_least_one_expected_success_tactic():
    for c in gen.DESIGN:
        row = gen.to_candidate_row(c)
        assert row["candidates"], \
            f"{gen.theorem_name(c)} candidate row has no candidates"
        assert row["candidates"][0] == c.tactic
        assert row["metadata"]["expected_success_tactics"]


def test_intro_negation_requires_intro_flag_set():
    """The per-operation default-flags table should mark intro_negation cells as
    requires_intro=True; spot-check the static design table to catch silent
    regressions."""
    intro_neg = [c for c in gen.DESIGN if c.operation == "intro_negation"]
    assert intro_neg, "no intro_negation cells in DESIGN"
    assert all(c.requires_intro for c in intro_neg)


def test_instantiate_forall_requires_quantifier_flag_set():
    fc = [c for c in gen.DESIGN if c.operation == "instantiate_forall"]
    assert fc, "no instantiate_forall cells in DESIGN"
    assert all(c.requires_quantifier for c in fc)


def test_rewrite_eq_requires_rewrite_flag_set():
    rc = [c for c in gen.DESIGN if c.operation == "rewrite_eq"]
    assert rc, "no rewrite_eq cells in DESIGN"
    assert all(c.requires_rewrite for c in rc)


def test_exists_elim_requires_exists_elim_flag_set():
    ec = [c for c in gen.DESIGN if c.operation == "exists_elim"]
    assert ec, "no exists_elim cells in DESIGN"
    assert all(c.requires_exists_elim for c in ec)


def test_dry_run_no_verify_writes_files(tmp_path, monkeypatch):
    """End-to-end check: ``--no-verify --rebuild`` writes a valid JSONL of
    every DESIGN cell."""
    seeds_out = tmp_path / "seeds.jsonl"
    cands_out = tmp_path / "candidates.jsonl"
    cache_out = tmp_path / "cache.json"
    argv = [
        "generate_redundancy_corpus.py",
        "--no-verify", "--rebuild",
        "--seeds-out", str(seeds_out),
        "--candidates-out", str(cands_out),
        "--cache", str(cache_out),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    rc = gen.main()
    assert rc == 0
    assert seeds_out.exists() and cands_out.exists()
    seed_rows = [json.loads(ln) for ln in seeds_out.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]
    cand_rows = [json.loads(ln) for ln in cands_out.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]
    assert len(seed_rows) == len(gen.DESIGN)
    assert len(cand_rows) == len(gen.DESIGN)
