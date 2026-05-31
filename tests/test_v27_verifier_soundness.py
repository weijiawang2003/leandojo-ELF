"""v27 Part 1 — verifier soundness regression tests.

Two layers:
  * Lean-free unit tests of the canonical module's structure (naive renderer omits
    the sentinel, trusted refuses the unsound path, gold is one-per-file, the
    mismatch/compare logic classifies false positives), and
  * a Lean-backed reproduction of the parser/lexer recovery skip on a tiny CORE
    batch (no Mathlib, fast): the naive verifier marks the malformed candidate
    verified (a false positive), while the trusted (confirm) and gold verifiers
    both fail it and agree.

The Lean-backed tests skip automatically if the pinned toolchain binary is absent.
No state_after anywhere.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mini_elf_lean.mathlib_batched_verifier import (
    DEFAULT_LEAN_BIN, GoldMathlibVerifier, Mismatch, NaiveBatchMathlibVerifier,
    TrustedMathlibVerifier, UnsafeVerifierError, audit_batch, compare_to_gold,
    make_skip_repro_batch,
)
from mini_elf_lean.mathlib_verifier import BatchMathlibVerifier, CandidateVerdict

ROOT = Path(__file__).resolve().parents[1]
HAS_LEAN = Path(DEFAULT_LEAN_BIN).exists()
lean_only = pytest.mark.skipif(not HAS_LEAN, reason="pinned Lean toolchain binary absent")


# --------------------------------------------------------------------------- #
# Lean-free structural unit tests
# --------------------------------------------------------------------------- #
def test_naive_render_omits_sentinel_but_keeps_strict_starts():
    v = NaiveBatchMathlibVerifier.__new__(NaiveBatchMathlibVerifier)
    v.imports = []
    src, ranges = NaiveBatchMathlibVerifier._render(v, [
        ("t0", "(n : Nat) : n + 0 = n", "rfl"),
        ("t1", "(p : Prop) (h : p) : p", "exact h"),
    ])
    lines = src.splitlines()
    assert not any("True.intro" in ln for ln in lines)  # NO sentinel (this is the bug)
    starts = [s for (_i, s, _e) in ranges]
    assert starts == sorted(starts) and len(set(starts)) == 2  # still strictly increasing
    for (_i, s, _e) in ranges:
        assert lines[s - 1].startswith("example ")


def test_corrected_render_keeps_sentinel():
    v = BatchMathlibVerifier.__new__(BatchMathlibVerifier)
    v.imports = []
    src, _ = BatchMathlibVerifier._render(v, [("t0", "(n : Nat) : n + 0 = n", "rfl")])
    assert any("True.intro" in ln for ln in src.splitlines())


def test_trusted_verifier_refuses_unsound_confirm_false():
    v = TrustedMathlibVerifier.__new__(TrustedMathlibVerifier)  # no Lean needed to hit the guard
    with pytest.raises(UnsafeVerifierError):
        v.verify_many([("t", "(n : Nat) : n = n", "rfl")], confirm=False)


def test_gold_forces_batch_size_one(tmp_path):
    # GoldMathlibVerifier sets batch_size=1 regardless of caller (core avoids lake).
    g = GoldMathlibVerifier(tmp_path, core=True)
    assert g.batch_size == 1


def test_compare_to_gold_flags_false_positive():
    items = [("a", "(p:Prop)(h:p):p", "exact h /- open"), ("b", "(n:Nat):n=n", "rfl")]
    gold = [CandidateVerdict(0, "a", items[0][1], items[0][2], False, "error"),
            CandidateVerdict(1, "b", items[1][1], items[1][2], True, None)]
    naive = [CandidateVerdict(0, "a", items[0][1], items[0][2], True, None),   # FALSE POSITIVE
             CandidateVerdict(1, "b", items[1][1], items[1][2], True, None)]
    mm = compare_to_gold(naive, gold, items, other_label="naive")
    assert len(mm) == 1 and mm[0].kind == "false_positive"
    assert mm[0].theorem_name == "a"


def test_mismatch_kind_classification():
    m_fp = Mismatch("x", "s", "t", gold_success=False, other_success=True, other_label="naive")
    m_fn = Mismatch("y", "s", "t", gold_success=True, other_success=False, other_label="naive")
    assert m_fp.kind == "false_positive" and m_fn.kind == "false_negative"


# --------------------------------------------------------------------------- #
# Lean-backed: parser/lexer recovery skip reproduction (CORE Lean, fast)
# --------------------------------------------------------------------------- #
@lean_only
def test_skip_reproduction_core():
    """A (unterminated comment) + B (false rfl): naive false-positives on A;
    trusted and gold both fail both candidates and agree."""
    os.environ.setdefault("MINI_ELF_LEAN_COMMAND", DEFAULT_LEAN_BIN)
    items = make_skip_repro_batch()
    rep = audit_batch(items, ROOT, core=True, timeout=60)
    # gold: both candidates fail in isolation
    assert rep["gold_verified"] == 0
    # the naive batch is UNSOUND: it marks the skipped/malformed candidate verified
    assert rep["naive_false_positives"] >= 1
    assert rep["naive_sound"] is False
    # the trusted (confirm) verifier is SOUND and agrees with gold
    assert rep["trusted_false_positives"] == 0
    assert rep["trusted_sound"] is True
    assert rep["trusted_verified"] == 0


@lean_only
def test_trusted_agrees_with_gold_on_mixed_core_batch():
    """A mix of valid + invalid core candidates: trusted == gold, no false
    positives, and timeout/error candidates are never counted verified."""
    os.environ.setdefault("MINI_ELF_LEAN_COMMAND", DEFAULT_LEAN_BIN)
    items = [
        ("ok_rfl", "(n : Nat) : n + 0 = n", "rfl"),
        ("ok_exact", "(p : Prop) (h : p) : p", "exact h"),
        ("bad_rfl", "(n : Nat) : n + 1 = n", "rfl"),
        ("bad_tac", "(p : Prop) : p", "exact trivial"),
        ("parse_err", "(p : Prop) (h : p) : p", "exact h /- open"),
        ("ok_after", "(p q : Prop) (h : p) : p", "exact h"),
    ]
    rep = audit_batch(items, ROOT, core=True, timeout=60)
    assert rep["trusted_false_positives"] == 0
    assert rep["trusted_vs_gold_mismatches"] == []
    # exactly the three genuine proofs verify under gold and trusted
    assert rep["gold_verified"] == 3
    assert rep["trusted_verified"] == 3


@lean_only
def test_no_state_after_in_rendered_source():
    """The verifier never renders or reads state_after."""
    v = TrustedMathlibVerifier.__new__(TrustedMathlibVerifier)
    v.imports = []
    src, _ = TrustedMathlibVerifier._render(v, [("t", "(n : Nat) : n = n", "rfl")])
    assert "state_after" not in src
