"""Make sure the basic-corpus generator emits seeds + candidates that the
ManualFileLLMClient can actually match — drift between (theorem_name,
initial_state) and (theorem_name, state_before) would silently produce an
empty corpus on collection.

This test does NOT validate the *content* of the data files on disk (they're
generated artifacts). It exercises the generator with a small synthetic
sub-corpus written to ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path

from collections import Counter

from scripts.generate_basic_corpus import Entry, all_entries, write_corpus

from mini_elf_lean.llm_client import ManualFileLLMClient
from mini_elf_lean.schemas import TheoremSeed


def _mini_entries() -> list:
    return [
        Entry(
            name="id_p",
            pattern_family="imp_identity",
            statement_fragment="(p : Prop) (h : p) : p",
            initial_state="p : Prop\nh : p\n⊢ p",
            correct=("exact h", "assumption"),
            wrong=("exact q",),
        ),
        Entry(
            name="true_const",
            pattern_family="true_intro",
            statement_fragment=": True",
            initial_state="⊢ True",
            correct=("trivial", "exact True.intro"),
            wrong=(),
        ),
    ]


def test_generator_seed_and_candidate_keys_match(tmp_path: Path) -> None:
    seeds_p = tmp_path / "seeds.jsonl"
    cands_p = tmp_path / "cands.jsonl"
    n_seeds, n_cands = write_corpus(seeds_p, cands_p, entries=_mini_entries())
    assert n_seeds == 2
    assert n_cands == 5  # id_p: 2 correct + 1 wrong; true_const: 2 correct

    seed_keys = {
        (json.loads(line)["theorem_name"], json.loads(line)["initial_state"])
        for line in seeds_p.read_text("utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    cand_keys = {
        (json.loads(line)["theorem_name"], json.loads(line)["state_before"])
        for line in cands_p.read_text("utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    # The whole point of the generator: these two sets are equal — no drift.
    assert seed_keys == cand_keys


def test_manual_file_client_can_match_generated_candidates(tmp_path: Path) -> None:
    seeds_p = tmp_path / "seeds.jsonl"
    cands_p = tmp_path / "cands.jsonl"
    write_corpus(seeds_p, cands_p, entries=_mini_entries())

    client = ManualFileLLMClient(str(cands_p))
    # Build a TheoremSeed exactly like the collector would, from the seeds file.
    rows = [
        json.loads(line)
        for line in seeds_p.read_text("utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    seed = TheoremSeed.model_validate(next(r for r in rows if r["theorem_name"] == "id_p"))

    batch = client.propose_tactics(
        seed=seed, state_before=seed.initial_state, num_candidates=4,
        prompt_style="diverse", temperature=0.0,
    )
    assert "exact h" in batch.candidates
    assert "assumption" in batch.candidates


def test_template_has_placeholder_and_no_mathlib_import(tmp_path: Path) -> None:
    seeds_p = tmp_path / "seeds.jsonl"
    cands_p = tmp_path / "cands.jsonl"
    write_corpus(seeds_p, cands_p, entries=_mini_entries())

    for line in seeds_p.read_text("utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        row = json.loads(line)
        assert "__TACTIC__" in row["template"], f"template missing placeholder: {row}"
        assert row["placeholder"] == "__TACTIC__"
        # Hard rule: this corpus must remain Mathlib-free.
        assert row["imports"] == [], f"imports must be empty (no Mathlib): {row}"
        for imp in row.get("imports", []):
            assert "Mathlib" not in imp


def test_seed_and_candidate_carry_pattern_family_metadata(tmp_path: Path) -> None:
    seeds_p = tmp_path / "seeds.jsonl"
    cands_p = tmp_path / "cands.jsonl"
    write_corpus(seeds_p, cands_p, entries=_mini_entries())

    for path, state_key in ((seeds_p, "initial_state"), (cands_p, "state_before")):
        for line in path.read_text("utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            row = json.loads(line)
            meta = row["metadata"]
            assert meta["pattern_family"] in {"imp_identity", "true_intro"}
            assert isinstance(meta["expected_success_tactics"], list)
            assert meta["expected_success_tactics"]  # non-empty


def test_metadata_does_not_break_theoremseed_schema(tmp_path: Path) -> None:
    """The seed rows must still validate as TheoremSeed (extra='forbid'); the
    family info lives inside the allowed `metadata` field, not at top level."""
    seeds_p = tmp_path / "seeds.jsonl"
    cands_p = tmp_path / "cands.jsonl"
    write_corpus(seeds_p, cands_p, entries=_mini_entries())
    for line in seeds_p.read_text("utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        seed = TheoremSeed.model_validate(json.loads(line))
        assert seed.metadata["pattern_family"]


# ---- the full corpus shape ----


def test_full_corpus_has_pattern_coverage() -> None:
    """Every family must have >=5 variants (the whole point of this milestone),
    theorem names are unique, and the corpus is in the documented size range."""
    entries = all_entries()
    assert 120 <= len(entries) <= 180, f"corpus size {len(entries)} outside 120..180"
    assert len({e.name for e in entries}) == len(entries), "duplicate theorem names"
    fam_counts = Counter(e.pattern_family for e in entries)
    assert len(fam_counts) >= 15, f"expected >=15 families, got {len(fam_counts)}"
    starved = {f: n for f, n in fam_counts.items() if n < 5}
    assert not starved, f"families with <5 variants break transfer: {starved}"


def test_every_entry_has_at_least_one_correct_candidate() -> None:
    for e in all_entries():
        assert e.correct, f"{e.name} has no intended-correct candidate"
        # candidates property must include the correct ones, dedup'd.
        assert set(e.correct).issubset(set(e.candidates))
