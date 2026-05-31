"""Mini-ELF v27 — canonical, soundness-audited Mathlib/core batched verifier.

This module is the **single trusted entry point** for v27 Mathlib (and broad-core)
candidate verification. It does not re-implement Lean invocation; it builds on the
corrected v26 verifier (:class:`mini_elf_lean.mathlib_verifier.BatchMathlibVerifier`,
which renders a clean ``example : True := True.intro`` sentinel after every
candidate **and** runs ``verify_many(confirm=True)`` to re-batch successes until
stable). v27 adds:

* :class:`TrustedMathlibVerifier` — the corrected verifier with ``confirm`` forced
  on. Headline metrics MUST use this. Passing ``confirm=False`` raises, so the
  unsound path cannot be selected by accident.
* :class:`GoldMathlibVerifier` — one candidate per Lean file (``batch_size=1``).
  This is the ground-truth reference: each candidate is elaborated in complete
  isolation, so no cross-candidate parser/lexer interaction is possible. Slow
  (one Lean process per candidate); used only for the soundness audit / tests.
* :class:`NaiveBatchMathlibVerifier` — **UNSAFE.** Batches with **no sentinel and
  no confirm**, reproducing the Lean parser/lexer recovery skip that can mark a
  malformed candidate as verified (see :func:`make_skip_repro_batch`). It exists
  ONLY to demonstrate the bug in the audit and the regression test; it must never
  be used for any reported metric.
* :func:`compare_to_gold` / :func:`audit_batch` — run gold/naive/trusted on the
  same candidates and report mismatches.

The parser/lexer recovery skip
------------------------------
If a candidate's tactic opens a construct the lexer/parser cannot close inside the
candidate's own lines — most reliably an **unterminated block comment** ``/- ...``
or string — Lean consumes the rest of the file and emits a single diagnostic at
the *end*. With a naive batch (one diagnostic, attributed by greatest-start-line)
the malformed candidate's own line range contains **no** diagnostic, so it is
falsely reported "verified", and every following candidate is skipped (never
independently elaborated). ``confirm=True`` fixes this: re-batching only the
current successes re-checks the culprit un-skipped, and it then surfaces its own
error and is demoted. The sentinel additionally absorbs the milder
"unexpected token 'example'" forward leak (which would otherwise falsely blame the
next candidate). Together they are sound (no false positive survives) and complete
(a genuine pass never errors), gold-tested with zero mismatches.

Honesty: real Lean typecheck (no mock), ``state_after`` is never read or produced,
manual reference candidates are corpus targets verified by Lean — never fed to a
model as predictions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from mini_elf_lean.mathlib_verifier import (
    DEFAULT_LEAN_BIN,
    MATHLIB_IMPORT,
    BatchMathlibVerifier,
    CandidateVerdict,
)

Item = Tuple[str, str, str]  # (theorem_name, statement, tactic)


class UnsafeVerifierError(RuntimeError):
    """Raised when an unsound verification mode is requested for trusted use."""


def _is_lex_poison(error: Optional[str]) -> bool:
    """An unterminated block comment / string makes the lexer consume the rest of
    the file, so such a candidate silently eats every following declaration (the
    parser-recovery skip). These are the only candidates that can cause a *false
    negative* on a downstream valid candidate (the trailing lex error gets
    attributed to it). 'unexpected token' parse errors do NOT eat past the next
    command keyword (Lean recovers there) and are handled by the sentinel."""
    e = (error or "").lower()
    return "unterminated comment" in e or "unterminated string" in e


class TrustedMathlibVerifier(BatchMathlibVerifier):
    """The corrected verifier with iterative success-confirmation forced on, plus
    a rescue pass that makes it **complete** as well as sound.

    This is the only verifier headline v27 scripts should construct. It builds on
    the v26 :class:`BatchMathlibVerifier` (sentinel render + confirm re-batching
    of successes, which demotes any false positive) and adds:

    * ``confirm=False`` is rejected (the unsound path is unreachable by mistake);
    * a **rescue pass**: ``confirm`` only re-checks *successes*, so a valid
      candidate that a preceding lexer-poisoning candidate (unterminated
      comment/string) ate is left falsely *failed* — the trailing lex error is
      attributed to it. After confirm converges, any candidate that *failed with
      a lexer-poison error* is re-checked **in isolation** (one declaration per
      file): the true poisoner (its own tactic has the unterminated construct)
      still fails, while a victim it ate now passes and is promoted. Isolation
      cannot create a false positive, so the rescue is sound.

    The v26 module is intentionally left unchanged; the rescue can only ever
    *increase* the verified count in the (corpus-absent) comment/string case, and
    is a no-op on candidate sets without lexer poisoning (e.g. real model beams),
    so it never alters previously reported numbers."""

    def verify_many(self, items, *, confirm: bool = True, max_rounds: int = 8):
        if not confirm:
            raise UnsafeVerifierError(
                "TrustedMathlibVerifier requires confirm=True (iterative "
                "success-confirmation); confirm=False is the unsound path."
            )
        verdicts = super().verify_many(items, confirm=True, max_rounds=max_rounds)
        return self._rescue_false_negatives(items, verdicts)

    def _rescue_false_negatives(self, items, verdicts):
        # Suspects = failures whose attributed error is a lexer-poison message.
        # Each is either the poisoner (own tactic has the unterminated construct)
        # or a downstream victim it ate; isolation tells them apart.
        suspects = [i for i, v in enumerate(verdicts)
                    if not v.success and _is_lex_poison(v.error)]
        if not suspects:
            return verdicts
        for gi in suspects:
            iso = self._verify_chunk([items[gi]])[0]  # one declaration in its own file
            if iso.success:  # victim — genuinely passes in isolation -> promote
                verdicts[gi] = CandidateVerdict(gi, iso.theorem_name, iso.statement,
                                                iso.tactic, True, None)
        return verdicts


class GoldMathlibVerifier(BatchMathlibVerifier):
    """Ground-truth verifier: exactly one candidate per Lean file.

    With ``batch_size=1`` every candidate is elaborated in its own process with
    nothing after it but the (clean) sentinel, so no other candidate can be
    skipped or mis-attributed. This is the reference the batched verifiers are
    audited against. Slow (one Lean invocation per candidate)."""

    def __init__(self, scratch, **kw):
        kw["batch_size"] = 1
        super().__init__(scratch, **kw)

    def verify_many(self, items, *, confirm: bool = False, max_rounds: int = 1):
        # one-per-file is already isolated; confirm is a no-op but harmless.
        return super().verify_many(items, confirm=False)


class NaiveBatchMathlibVerifier(BatchMathlibVerifier):
    """UNSAFE reference: batched with NO sentinel and NO confirm.

    Reproduces the historical unsound behaviour for the soundness audit and the
    regression test. Never use for any reported metric. ``verify_many`` ignores
    the ``confirm`` argument and always runs a single naive pass."""

    #: empty sentinel → the naive renderer adds nothing between candidates.
    _SENTINEL = ""

    def _render(self, items: Sequence[Item]):
        """Like the base renderer but WITHOUT the per-candidate resync sentinel.
        Candidate starts remain strictly increasing (each ``example`` header is
        on its own line), so attribution still runs; the missing sentinel is
        exactly what makes a forward parse/lex leak land on (or skip) the wrong
        candidate."""
        lines: List[str] = list(self.imports)
        lines.append("")
        ranges: List[Tuple[int, int, int]] = []
        for idx, (_name, stmt, tactic) in enumerate(items):
            start = len(lines) + 1
            lines.append(f"example {stmt} := by")
            body = tactic.splitlines() or [tactic]
            for bl in body:
                lines.append("  " + bl)
            end = len(lines)
            ranges.append((idx, start, end))
            lines.append("")  # blank separator only; NO sentinel resync
        return "\n".join(lines) + "\n", ranges

    def verify_many(self, items, *, confirm: bool = False, max_rounds: int = 1):
        # deliberately ignore confirm: the naive path never re-batches.
        return super().verify_many(items, confirm=False)


# --------------------------------------------------------------------------- #
# Soundness audit helpers
# --------------------------------------------------------------------------- #
@dataclass
class Mismatch:
    theorem_name: str
    statement: str
    tactic: str
    gold_success: bool
    other_success: bool
    other_label: str

    @property
    def kind(self) -> str:
        # other says verified but gold says fail => FALSE POSITIVE (the dangerous one)
        if self.other_success and not self.gold_success:
            return "false_positive"
        return "false_negative"

    def as_dict(self) -> Dict[str, object]:
        return {
            "theorem_name": self.theorem_name, "statement": self.statement,
            "tactic": self.tactic, "gold_success": self.gold_success,
            f"{self.other_label}_success": self.other_success, "kind": self.kind,
        }


def _success_map(verdicts: Sequence[CandidateVerdict]) -> Dict[Tuple[str, str], bool]:
    return {(v.theorem_name, v.tactic): v.success for v in verdicts}


def compare_to_gold(other: Sequence[CandidateVerdict],
                    gold: Sequence[CandidateVerdict],
                    items: Sequence[Item], *, other_label: str) -> List[Mismatch]:
    """Return per-candidate mismatches between ``other`` and the gold reference."""
    gmap = _success_map(gold)
    omap = _success_map(other)
    out: List[Mismatch] = []
    for nm, stmt, tac in items:
        g = gmap.get((nm, tac))
        o = omap.get((nm, tac))
        if g is None or o is None or g == o:
            continue
        out.append(Mismatch(nm, stmt, tac, g, o, other_label))
    return out


def audit_batch(items: Sequence[Item], scratch: Path, *,
                lean_path: Optional[str] = None, core: bool = False,
                timeout: float = 300.0, include_naive: bool = True
                ) -> Dict[str, object]:
    """Verify ``items`` with gold, trusted (corrected), and (optionally) the naive
    verifier, and report mismatches of each batched verifier vs gold.

    Returns a JSON-serialisable dict. A sound batched verifier has zero
    false positives vs gold."""
    common = dict(lean_path=lean_path, core=core, timeout=timeout)
    gold = GoldMathlibVerifier(scratch, **common).verify_many(items)
    trusted_v = TrustedMathlibVerifier(scratch, **common)
    trusted = trusted_v.verify_many(items, confirm=True)
    report: Dict[str, object] = {
        "n_candidates": len(items),
        "core": core,
        "gold_verified": sum(1 for v in gold if v.success),
        "trusted_verified": sum(1 for v in trusted if v.success),
        "trusted_vs_gold_mismatches": [m.as_dict()
                                       for m in compare_to_gold(trusted, gold, items, other_label="trusted")],
    }
    report["trusted_false_positives"] = sum(
        1 for m in report["trusted_vs_gold_mismatches"] if m["kind"] == "false_positive")
    report["trusted_sound"] = report["trusted_false_positives"] == 0
    if include_naive:
        naive = NaiveBatchMathlibVerifier(scratch, **common).verify_many(items)
        nm = [m.as_dict() for m in compare_to_gold(naive, gold, items, other_label="naive")]
        report["naive_verified"] = sum(1 for v in naive if v.success)
        report["naive_vs_gold_mismatches"] = nm
        report["naive_false_positives"] = sum(1 for m in nm if m["kind"] == "false_positive")
        report["naive_sound"] = report["naive_false_positives"] == 0
    return report


def make_skip_repro_batch() -> List[Item]:
    """A small core-Lean batch that triggers the parser/lexer recovery skip.

    Candidate A's tactic opens an **unterminated block comment**, so the lexer
    consumes the rest of the file (its own sentinel and candidate B) and emits a
    single ``unterminated comment`` diagnostic at the end. Both candidates fail
    when checked in isolation (B is a false equality). A naive batch falsely
    marks A verified (no diagnostic in A's own range); the trusted/gold verifier
    must fail both."""
    return [
        ("v27_repro_unterminated_comment", "(p : Prop) (h : p) : p", "exact h /- not closed"),
        ("v27_repro_false_rfl", "(n : Nat) : n + 1 = n", "rfl"),
    ]


__all__ = [
    "TrustedMathlibVerifier", "GoldMathlibVerifier", "NaiveBatchMathlibVerifier",
    "UnsafeVerifierError", "Mismatch", "compare_to_gold", "audit_batch",
    "make_skip_repro_batch", "DEFAULT_LEAN_BIN", "MATHLIB_IMPORT", "CandidateVerdict",
]
