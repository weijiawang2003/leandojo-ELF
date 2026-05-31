"""Hard-corpus generator (Mini-ELF v2). Verifies seeds + candidates are
schema-valid, key-matched, and carry the difficulty/capability metadata the v2
split strategies and per-difficulty metrics rely on. No Lean; pure-Python."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from scripts.generate_hard_corpus import (
    HARD_FAMILY_BUILDERS,
    SOURCE,
    Entry,
    all_entries,
    write_corpus,
)

from mini_elf_lean.llm_client import ManualFileLLMClient
from mini_elf_lean.schemas import ManualCandidateRecord, TheoremSeed


def test_generator_emits_seeds_and_candidates(tmp_path):
    seeds_p = tmp_path / "seeds.jsonl"
    cands_p = tmp_path / "cands.jsonl"
    n_seeds, n_cands = write_corpus(seeds_p, cands_p)
    assert n_seeds >= 80  # target 80-150 theorems
    assert 300 <= n_cands <= 800
    assert seeds_p.exists() and cands_p.exists()


def test_every_seed_has_candidates():
    for e in all_entries():
        assert len(e.candidates) >= 3, f"{e.name} has too few candidates"
        assert len(e.candidates) <= 8, f"{e.name} has too many candidates"


def test_every_theorem_has_expected_success():
    for e in all_entries():
        assert e.correct, f"{e.name} declares no expected-success tactic"


def test_no_mathlib_imports(tmp_path):
    seeds_p = tmp_path / "seeds.jsonl"
    write_corpus(seeds_p, tmp_path / "cands.jsonl")
    for line in seeds_p.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        row = json.loads(line)
        assert row["imports"] == [], f"{row['theorem_name']} has imports {row['imports']}"
        seed = TheoremSeed.model_validate(row)  # must validate
        assert "Mathlib" not in (seed.template or "")


def test_candidate_keys_match_seed_keys(tmp_path):
    seeds_p = tmp_path / "seeds.jsonl"
    cands_p = tmp_path / "cands.jsonl"
    write_corpus(seeds_p, cands_p)
    seeds = {json.loads(l)["theorem_name"]: json.loads(l)
             for l in seeds_p.read_text(encoding="utf-8").splitlines() if not l.startswith("#")}
    for line in cands_p.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        row = json.loads(line)
        name = row["theorem_name"]
        assert name in seeds
        # the manual-file client matches on (name, state_before == initial_state)
        assert row["state_before"] == seeds[name]["initial_state"]
        ManualCandidateRecord.model_validate(row)  # must validate (extra ignored)


def test_metadata_fields_present():
    for e in all_entries():
        from scripts.generate_hard_corpus import _meta
        m = _meta(e)
        for k in ("pattern_family", "difficulty", "requires_multistep",
                  "requires_copy", "requires_structure", "expected_success_tactics"):
            assert k in m
        assert m["difficulty"] in ("easy", "medium", "hard")


def test_family_counts_nontrivial():
    fams = Counter(e.pattern_family for e in all_entries())
    assert len(fams) >= 10
    assert all(n >= 3 for n in fams.values())
    # multi-step + structure + copy capabilities are all represented
    es = all_entries()
    assert any(e.requires_multistep for e in es)
    assert any(e.requires_structure for e in es)
    assert any(e.requires_copy for e in es)


def test_source_label():
    seeds_p = Path("/tmp/_hc_src_seeds.jsonl")
    cands_p = Path("/tmp/_hc_src_cands.jsonl")
    write_corpus(seeds_p, cands_p)
    for line in cands_p.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        assert json.loads(line)["source"] == SOURCE
    seeds_p.unlink(missing_ok=True)
    cands_p.unlink(missing_ok=True)


def test_manual_client_matches_generated(tmp_path):
    """End-to-end: the ManualFileLLMClient must find candidates for each seed
    (drift between seed.initial_state and candidate.state_before would silently
    produce an empty corpus on collection)."""
    seeds_p = tmp_path / "seeds.jsonl"
    cands_p = tmp_path / "cands.jsonl"
    write_corpus(seeds_p, cands_p)
    client = ManualFileLLMClient(cands_p)
    builders = list(HARD_FAMILY_BUILDERS)
    sample = builders[0]() + builders[6]()  # imp_chain3 + or_elim
    for e in sample:
        seed = TheoremSeed(
            theorem_name=e.name, theorem_statement=e.statement_fragment,
            initial_state=e.initial_state,
            template=f"example {e.statement_fragment} := by\n  __TACTIC__",
        )
        batch = client.propose_tactics(
            seed=seed, state_before=e.initial_state, num_candidates=8,
            prompt_style="diverse", temperature=0.0,
        )
        assert any(c in e.candidates for c in batch.candidates), f"no match for {e.name}"
