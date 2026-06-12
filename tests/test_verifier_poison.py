"""v42 — batched-verifier poison regression tests (the v41 false-negative bug).

v41 discovered that the trusted confirm-loop path under-reports genuine passes
when a batch contains malformed or slow candidates (observed: plan-AR 4 batched
vs 20 isolated on identical candidates, "confirm did not converge in 8 rounds").
Two demotion classes:

  * **chunk timeout** — one slow chunk fails every candidate in it at once, and
    confirm's success-rebatching REPACKS candidates across chunk boundaries, so
    a timeout in any round demotes en masse and never re-promotes;
  * **parse desync** — a parse-broken candidate in a recheck batch can leak /
    garble attribution for candidates after it.

The v42 fix is :meth:`verify_many_bisect`: verdicts are accepted only from
parse-clean, non-timed-out compiles or from singleton files (= isolation), with
parse-suspects quarantined to singletons and the remainder re-batched.

Tests:
  (i)   reproducer — the OLD path (``verify_many_legacy``) demotes known-good
        candidates; bisect-batched verifies them (this test FAILS on pre-v42 code);
  (ii)  property — bisect-batched == gold isolation on a 60-candidate mixed set
        (clean passes / clean fails / parse-broken incl. balanced-but-broken /
        lexer poison);
  (iii) the old lexer-poison classes are still handled by both paths.

Lean-backed tests use CORE Lean (no Mathlib import — fast) and skip if the
pinned toolchain binary is absent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mini_elf_lean.mathlib_batched_verifier import (
    DEFAULT_LEAN_BIN, GoldMathlibVerifier, TrustedMathlibVerifier,
    make_skip_repro_batch,
)
from mini_elf_lean.mathlib_verifier import _is_parse_class

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path("/home/wangw/code/mini_elf_mathlib_probe")
HAS_LEAN = Path(DEFAULT_LEAN_BIN).exists() and SCRATCH.exists()
lean_only = pytest.mark.skipif(not HAS_LEAN, reason="pinned Lean toolchain binary absent")


# --------------------------------------------------------------------------- #
# Lean-free: the parse-class predicate (what makes a compile untrusted)
# --------------------------------------------------------------------------- #
def test_parse_class_predicate():
    # desync-capable: parser / lexer / chunk timeout
    assert _is_parse_class("error: unexpected token ','; expected ']'")
    assert _is_parse_class("error: unexpected token 'example'; expected term")
    assert _is_parse_class("error: unexpected end of input")
    assert _is_parse_class("error: unterminated comment")
    assert _is_parse_class("error: unterminated string literal")
    assert _is_parse_class("timeout")
    # elaboration errors parse fine and cannot desync — must NOT trigger splits,
    # even when the message contains the word "expected"
    assert not _is_parse_class("error: unknown identifier 'foo'")
    assert not _is_parse_class("error: type mismatch ... but is expected to have type Nat")
    assert not _is_parse_class("error: function expected at h")
    assert not _is_parse_class("error: unsolved goals ...")
    assert not _is_parse_class("error: linarith failed to find a contradiction")
    assert not _is_parse_class(None)


# --------------------------------------------------------------------------- #
# Shared fixtures (core Lean)
# --------------------------------------------------------------------------- #
def _slow_valid(n: int):
    """A genuinely valid candidate whose kernel evaluation takes ~n/8000 s
    (calibrated: N=6000 ≈ 1.0 s, N=12000 ≈ 1.8 s per singleton file; the
    in-file marginal cost is lower, hence the N=12000 class in the timeout
    reproducer — 12 of them ≈ 18 s in one file vs the 8 s chunk timeout,
    while each singleton stays ≈ 2 s ≪ 8 s)."""
    s = n * (n - 1) // 2
    return (f"slow{n}", f": (List.range {n}).foldl Nat.add 0 = {s}",
            "set_option maxRecDepth 1000000 in decide")


GOODS = [
    ("good_rfl", "(n : Nat) : n + 0 = n", "rfl"),
    ("good_exact", "(p : Prop) (h : p) : p", "exact h"),
    ("good_comm", "(a b : Nat) : a + b = b + a", "exact Nat.add_comm a b"),
]

# grounded-proof-style malformed candidates (v41 classes); note bad_dangling and
# bad_empty_arg are DELIMITER-BALANCED — they pass v41's well_formed filter.
MALFORMED = [
    ("bad_empty_arg", "(n : Nat) : n + 0 = n", "rw [Nat.add_zero, , Nat.add_zero]"),
    ("bad_dangling", "(n : Nat) : n = n", "simpa using"),
    ("bad_unbal", "(n : Nat) : n = n", "exact (rfl"),
    ("bad_comment", "(p : Prop) (h : p) : p", "exact h /- not closed"),
    ("bad_string", "(n : Nat) : n = n", 'have s := "open\nrfl'),
]

FALSE_STMTS = [
    ("false_rfl", "(n : Nat) : n + 1 = n", "rfl"),
    ("false_simp", "(n : Nat) : n = n + 1", "simp"),
]


# --------------------------------------------------------------------------- #
# (i) Reproducer: old path demotes known-good candidates; bisect does not.
#     THIS TEST FAILS ON PRE-V42 CODE (verify_many == legacy confirm loop).
# --------------------------------------------------------------------------- #
@lean_only
def test_timeout_chunk_demotes_goods_on_legacy_but_not_bisect():
    # 12 slow-valid candidates (~1 s each) + goods; chunk wall-clock far exceeds
    # the 6 s timeout, but every singleton is far below it.
    v = TrustedMathlibVerifier(SCRATCH, core=True, timeout=8)
    batch = [_slow_valid(12000 + i) for i in range(12)] + list(GOODS)
    legacy = v.verify_many_legacy(batch)
    # the WHOLE chunk times out -> every candidate, including the trivially-good
    # ones, is falsely failed (this is the v41 under-reporting bug)
    assert all(not x.success for x in legacy), "legacy unexpectedly survived; bug fixed elsewhere?"
    assert any(x.error == "timeout" for x in legacy)
    fixed = v.verify_many_bisect(batch)
    by_name = {x.theorem_name: x for x in fixed}
    for nm, _s, _t in GOODS:
        assert by_name[nm].success, f"bisect failed known-good {nm}: {by_name[nm].error}"
    for nm in (f"slow{12000 + i}" for i in range(12)):
        assert by_name[nm].success, f"bisect failed slow-valid {nm}: {by_name[nm].error}"


@lean_only
def test_trusted_default_path_is_bisect():
    # TrustedMathlibVerifier.verify_many must route through bisect now: the same
    # timeout batch verifies fine via the public API.
    v = TrustedMathlibVerifier(SCRATCH, core=True, timeout=8)
    batch = [_slow_valid(12100 + i) for i in range(12)] + list(GOODS)
    out = v.verify_many(batch, confirm=True)
    assert all(x.success for x in out)


# --------------------------------------------------------------------------- #
# (ii) Property: bisect-batched == gold isolation on a 60-candidate mixed set
# --------------------------------------------------------------------------- #
@lean_only
def test_bisect_equals_isolated_on_mixed_60():
    base = GOODS + MALFORMED + FALSE_STMTS
    batch = []
    for rep in range(6):  # 6 × 10 = 60, names uniquified
        for nm, stmt, tac in base:
            batch.append((f"{nm}_r{rep}", stmt, tac))
    v = TrustedMathlibVerifier(SCRATCH, core=True, timeout=120)
    g = GoldMathlibVerifier(SCRATCH, core=True, timeout=120)
    bi = v.verify_many_bisect(batch)
    go = g.verify_many(batch)
    mism = [(b.theorem_name, b.success, gg.success)
            for b, gg in zip(bi, go) if b.success != gg.success]
    assert not mism, f"bisect != isolated: {mism}"
    # and the goods did verify (the test isn't vacuous)
    ok = {x.theorem_name for x in go if x.success}
    assert any(n.startswith("good_rfl") for n in ok)


# --------------------------------------------------------------------------- #
# (iv) Attribution shift: a MULTI-LINE STATEMENT used to be appended as ONE
#      bookkeeping line, silently shifting every later range in the file —
#      every later diagnostic was misattributed (false POSITIVES and false
#      negatives, with zero parse diagnostics). Found live in v42: the one
#      tier-dev statement with an embedded newline (concaveOn_id) made garbage
#      candidates "verify" in v40's batched run.
# --------------------------------------------------------------------------- #
@lean_only
def test_multiline_statements_do_not_shift_attribution():
    # 8 consecutive candidates sharing a 3-physical-line statement: under the old
    # bookkeeping each adds +2 of cumulative range shift, so tail diagnostics land
    # whole candidates away. Recorded old-code behavior (old _render + legacy):
    # ml_2/ml_4/ml_6 ('simp [h]', genuine passes) and good_tail ('exact h') all
    # DEMOTED — and on the real v40 tier-dev data the same shift produced false
    # POSITIVES (garbage candidates "verified"). The fixed render + bisect must
    # match gold isolation exactly.
    ml_stmt = "(a b : Nat)\n    (h : a = b)\n    : a + 0 = b"
    batch = [(f"ml_{i}", ml_stmt, "simp [h]" if i % 2 == 0 else "exact garbage_id")
             for i in range(8)]
    batch += [
        ("false_tail_1", "(n : Nat) : n + 1 = n", "rfl"),
        ("good_tail", "(p : Prop) (h : p) : p", "exact h"),
        ("false_tail_2", "(n : Nat) : n = n + 2", "simp"),
    ]
    v = TrustedMathlibVerifier(SCRATCH, core=True, timeout=120)
    g = GoldMathlibVerifier(SCRATCH, core=True, timeout=120)
    bi = {x.theorem_name: x.success for x in v.verify_many(batch, confirm=True)}
    go = {x.theorem_name: x.success for x in g.verify_many(batch)}
    assert bi == go, f"attribution shift: {bi} vs gold {go}"
    assert go["good_tail"] and go["ml_0"]
    assert not go["false_tail_1"] and not go["false_tail_2"] and not go["ml_1"]


# --------------------------------------------------------------------------- #
# (iii) The old lexer-poison classes are still handled by both paths
# --------------------------------------------------------------------------- #
@lean_only
def test_old_lex_poison_classes_still_handled():
    items = make_skip_repro_batch()
    v = TrustedMathlibVerifier(SCRATCH, core=True, timeout=120)
    for verdicts in (v.verify_many(items, confirm=True), v.verify_many_legacy(items)):
        assert all(not x.success for x in verdicts)  # both candidates genuinely fail
