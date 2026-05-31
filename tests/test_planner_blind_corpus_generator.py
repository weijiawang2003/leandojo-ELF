"""V4 — planner-blind corpus generator tests (Part 2/7).

Pure-Python: no torch, no Lean. Validates the generated JSONL structure,
metadata, core-Lean-only imports, candidate-key consistency, the v4 capability
flags, and **theorem-name disjointness** from the basic + hard corpora."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_planner_blind_corpus import all_entries, write_corpus

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FAMILIES = {
    "neg_exfalso", "neg_contrapositive", "neg_imp_exfalso", "neg_double_intro",
    "neg_or_cases", "exists_elim_prop", "exists_elim_conj", "forall_inst",
    "rewrite_succ", "exists_reconstruct",
}


def _load(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def test_generator_emits_valid_jsonl(tmp_path):
    seeds_p = tmp_path / "seeds.jsonl"
    cands_p = tmp_path / "cands.jsonl"
    n_seeds, n_cands = write_corpus(seeds_p, cands_p)
    assert 60 <= n_seeds <= 120, f"expected 60-120 seeds, got {n_seeds}"
    assert 250 <= n_cands <= 600, f"expected 250-600 candidates, got {n_cands}"
    seeds = _load(seeds_p)
    cands = _load(cands_p)
    assert len(seeds) == n_seeds and len(cands) == n_seeds
    # every row parses and is well-formed
    for r in seeds:
        assert r["theorem_name"] and r["theorem_statement"] and r["initial_state"]
        assert r["template"].startswith("example ") and r["placeholder"] == "__TACTIC__"


def test_families_and_counts():
    entries = all_entries()
    fams = {e.pattern_family for e in entries}
    assert fams == EXPECTED_FAMILIES
    assert 8 <= len(fams) <= 12


def test_metadata_present_with_v4_flags(tmp_path):
    seeds_p, cands_p = tmp_path / "s.jsonl", tmp_path / "c.jsonl"
    write_corpus(seeds_p, cands_p)
    for r in _load(seeds_p):
        m = r["metadata"]
        for key in ("pattern_family", "difficulty", "requires_negation",
                    "requires_exists_elim", "requires_forall", "requires_rewrite",
                    "planner_blind", "expected_success_tactics"):
            assert key in m, f"{r['theorem_name']} missing metadata.{key}"
        assert m["planner_blind"] is True
        assert m["expected_success_tactics"]  # at least one intended-correct tactic
    for r in _load(cands_p):
        assert r["source"] == "planner-blind-manual-corpus"


def test_no_mathlib_imports(tmp_path):
    seeds_p, cands_p = tmp_path / "s.jsonl", tmp_path / "c.jsonl"
    write_corpus(seeds_p, cands_p)
    for r in _load(seeds_p):
        assert r["imports"] == [], f"{r['theorem_name']} has imports {r['imports']}"
        assert "Mathlib" not in r["template"]


def test_every_seed_has_candidates_and_keys_match(tmp_path):
    seeds_p, cands_p = tmp_path / "s.jsonl", tmp_path / "c.jsonl"
    write_corpus(seeds_p, cands_p)
    seeds = {r["theorem_name"]: r for r in _load(seeds_p)}
    cands = {r["theorem_name"]: r for r in _load(cands_p)}
    assert set(seeds) == set(cands)
    for name, c in cands.items():
        assert c["candidates"], f"{name} has no candidates"
        # candidate key: state_before must equal the seed's initial_state
        assert c["state_before"] == seeds[name]["initial_state"]


def test_capability_flags_match_family():
    by_fam = {}
    for e in all_entries():
        by_fam.setdefault(e.pattern_family, e)
    assert by_fam["neg_exfalso"].requires_negation
    assert by_fam["neg_contrapositive"].requires_negation
    assert by_fam["exists_elim_prop"].requires_exists_elim
    assert by_fam["forall_inst"].requires_forall
    assert by_fam["rewrite_succ"].requires_rewrite


def test_no_overlap_with_basic_or_hard_theorem_names():
    blind = {e.name for e in all_entries()}
    for other in ("data/seeds/basic_lean_seeds.jsonl", "data/seeds/hard_lean_seeds.jsonl"):
        p = ROOT / other
        if not p.exists():
            continue
        names = {json.loads(l)["theorem_name"] for l in p.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")}
        assert not (blind & names), f"name overlap with {other}: {sorted(blind & names)}"
