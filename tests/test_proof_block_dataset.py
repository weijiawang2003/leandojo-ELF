"""Tests for :mod:`mini_elf_lean.proof_block_dataset`."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import List

import pytest


@pytest.fixture
def synth_rows():
    """A tiny synthetic pool with four families spread across two operations."""
    from mini_elf_lean.proof_block_dataset import ProofBlockRow
    rows: List[ProofBlockRow] = []
    fixtures = [
        # neg_exfalso: contradiction op
        ("neg_a", "neg_exfalso",       "contradiction", "exact absurd hp hnp"),
        ("neg_b", "neg_exfalso",       "contradiction", "contradiction"),
        # neg_or_cases: contradiction op too (sibling)
        ("neg_c", "neg_or_cases",      "contradiction", "cases h with h h"),
        # forall_inst: instantiate_forall op
        ("fa_a",  "forall_inst",       "instantiate_forall", "exact h 0"),
        # exists_elim_conj: destruct_exists op
        ("ex_a",  "exists_elim_conj",  "destruct_exists",    "obtain ⟨n, hp, hq⟩ := h"),
    ]
    for i, (thm, fam, op, tac) in enumerate(fixtures):
        rows.append(ProofBlockRow(
            theorem_name=thm,
            theorem_statement=f"theorem {thm} : True",
            state_before=f"⊢ goal for {thm}",
            tactic=tac,
            family=fam,
            required_operation=op,
            corpus_source="planner_blind",
            tactic_source="verified",
        ))
    return rows


def test_family_holdout_isolates_held_family(synth_rows):
    from mini_elf_lean.proof_block_dataset import (
        assert_family_holdout, build_family_holdout,
    )
    rows = build_family_holdout(synth_rows, "neg_exfalso")
    train = [r for r in rows if r.split == "train"]
    test  = [r for r in rows if r.split == "test"]
    assert {r.family for r in train} == {"neg_or_cases", "forall_inst", "exists_elim_conj"}
    assert {r.family for r in test}  == {"neg_exfalso"}
    assert_family_holdout(rows, "neg_exfalso")  # no-throw = invariant holds


def test_operation_holdout_isolates_held_op(synth_rows):
    from mini_elf_lean.proof_block_dataset import (
        assert_operation_holdout, build_operation_holdout,
    )
    rows = build_operation_holdout(synth_rows, "contradiction")
    train = [r for r in rows if r.split == "train"]
    test  = [r for r in rows if r.split == "test"]
    assert {r.required_operation for r in train} <= {"instantiate_forall", "destruct_exists"}
    assert {r.required_operation for r in test} == {"contradiction"}
    assert_operation_holdout(rows, "contradiction")


def test_donorless_eval_pulls_pb_families(synth_rows):
    from mini_elf_lean.proof_block_dataset import (
        PB_FAMILIES, build_donorless_eval,
    )
    rows = build_donorless_eval(synth_rows)
    pb = set(PB_FAMILIES)
    for r in rows:
        if r.family in pb:
            assert r.split == "test"
        else:
            assert r.split == "train"


def test_interpolation_theorem_level_no_leakage(synth_rows):
    """A theorem must not appear in more than one split."""
    from mini_elf_lean.proof_block_dataset import (
        assert_no_theorem_leakage, build_interpolation,
    )
    # Inflate to several rows per theorem to test the cross-split guard
    inflated = []
    for r in synth_rows:
        inflated.append(r)
        # second tactic for the same theorem
        from mini_elf_lean.proof_block_dataset import ProofBlockRow
        inflated.append(ProofBlockRow(**{**r.__dict__, "tactic": r.tactic + " -- alt"}))
    rows = build_interpolation(inflated, train_frac=0.4, val_frac=0.2)
    # Each theorem in exactly one split
    seen = {}
    for r in rows:
        s = seen.setdefault(r.theorem_name, r.split)
        assert s == r.split
    assert_no_theorem_leakage(rows)


def test_no_state_after_in_emitted_rows(synth_rows):
    from mini_elf_lean.proof_block_dataset import (
        assert_no_state_after, build_interpolation,
    )
    rows = build_interpolation(synth_rows)
    # ProofBlockRow has no state_after field; cross-check on the dict form too
    for r in rows:
        d = r.to_dict()
        for k in d:
            assert not k.startswith("state_after"), k
    assert_no_state_after(rows)


def test_tactics_nonempty(synth_rows):
    from mini_elf_lean.proof_block_dataset import assert_nonempty_tactics
    assert_nonempty_tactics(synth_rows)
    # Negative case
    from mini_elf_lean.proof_block_dataset import ProofBlockRow
    bad = list(synth_rows) + [ProofBlockRow(
        theorem_name="z", theorem_statement="", state_before="", tactic="   ",
        family=None, required_operation="unknown",
        corpus_source="basic", tactic_source="verified",
    )]
    with pytest.raises(AssertionError):
        assert_nonempty_tactics(bad)


def test_write_regime_roundtrip(tmp_path, synth_rows):
    from mini_elf_lean.proof_block_dataset import (
        build_interpolation, write_regime,
    )
    rows = build_interpolation(synth_rows)
    out_dir = tmp_path / "regime"
    counts = write_regime(rows, out_dir)
    assert (out_dir / "manifest.json").exists()
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["n_total"] == len(rows)
    # Each split file is a flat jsonl with the same keys as ProofBlockRow.to_dict
    for s in counts:
        assert (out_dir / f"{s}.jsonl").exists()
        for line in (out_dir / f"{s}.jsonl").read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            assert d["tactic"]
            assert "state_after" not in d
