"""LeanDojoRunner mapped against the REAL lean_dojo 4.x API surface.

The fakes here mirror the *exact* attribute names and `run_tac` signature found
by `inspect.signature(Dojo.run_tac)` and `cls.__annotations__` in lean_dojo
4.20.0:

  - ``Dojo.run_tac(self, state: TacticState, tactic: str) ->
       Union[TacticState, ProofFinished, LeanError, ProofGivenUp]``
  - ``TacticState`` carries ``pp`` / ``id`` / ``message`` / ``goals``
  - ``ProofFinished`` carries ``tactic_state_id`` / ``message``
  - ``LeanError`` carries ``error``
  - ``ProofGivenUp`` has no fields
  - ``DojoCrashError`` is raised (not returned) when the REPL dies

The existing ``tests/test_leandojo_runner.py`` mocked an older shape (a
``ProofFinished`` with ``.id``). These tests pin the mapping against the actual
production shape so regressions get caught even without a live LeanDojo.
"""

from __future__ import annotations

import types

import pytest

from mini_elf_lean.lean_runner import LeanDojoRunner
from mini_elf_lean.schemas import TheoremSeed


# ---- fakes matching the real API attribute names ----


class TacticState:  # name + attrs match lean_dojo.interaction.dojo.TacticState
    def __init__(self, pp: str, id: int, message: str | None = None, num_goals: int = 1) -> None:
        self.pp = pp
        self.id = id
        self.message = message
        self.goals = list(range(num_goals))  # opaque; runner only reads num_goals
        # `num_goals` is a property on the real class; expose it as a plain attr.
        self.num_goals = num_goals


class ProofFinished:  # matches real class name + `tactic_state_id` field
    def __init__(self, tactic_state_id: int, message: str | None = None) -> None:
        self.tactic_state_id = tactic_state_id
        self.message = message


class LeanError:
    def __init__(self, error: str) -> None:
        self.error = error


class ProofGivenUp:
    pass


class DojoCrashError(Exception):
    """Mirror of lean_dojo.interaction.dojo.DojoCrashError (raised, not returned)."""


class FakeDojo:
    """run_tac signature: (self, state: TacticState, tactic: str). Returns one
    of the four documented result types, or raises DojoCrashError."""

    def __init__(self, theorem, init: TacticState, plan: dict) -> None:
        self.theorem = theorem
        self._init = init
        self._plan = plan

    def __enter__(self):
        return self, self._init

    def __exit__(self, *exc) -> bool:
        return False

    def run_tac(self, state: TacticState, tactic: str):
        assert isinstance(state, TacticState), f"runner passed wrong state type: {type(state)}"
        assert isinstance(tactic, str)
        rv = self._plan.get(tactic, LeanError(f"unknown tactic '{tactic}'"))
        if isinstance(rv, BaseException):
            raise rv
        return rv() if callable(rv) else rv


def _module(init: TacticState, plan: dict):
    class LeanGitRepo:
        def __init__(self, url, commit):
            self.url, self.commit = url, commit

    class Theorem:
        def __init__(self, repo, file_path, full_name):
            self.repo, self.file_path, self.full_name = repo, file_path, full_name

    def Dojo(theorem, **_kwargs):
        return FakeDojo(theorem, init, plan)

    return types.SimpleNamespace(
        LeanGitRepo=LeanGitRepo,
        Theorem=Theorem,
        Dojo=Dojo,
        TacticState=TacticState,
        ProofFinished=ProofFinished,
        LeanError=LeanError,
        ProofGivenUp=ProofGivenUp,
        DojoCrashError=DojoCrashError,
    )


def _seed() -> TheoremSeed:
    return TheoremSeed(
        theorem_name="id_of_p",
        theorem_statement="(p : Prop) (h : p) : p",
        repo_url="https://github.com/example/leandojo-ELF",
        commit="deadbeef",
        file_path="MiniDojo.lean",
        full_name="id_of_p",
    )


# ---- mapping tests against the real API shape ----


def test_initial_state_pp_and_id_round_trip() -> None:
    init = TacticState(pp="p : Prop\nh : p\n⊢ p", id=0, num_goals=1)
    runner = LeanDojoRunner(lean_dojo_module=_module(init, {}))
    try:
        s0 = runner.start(_seed())
        assert s0 == "p : Prop\nh : p\n⊢ p"
        # Runner's state registry must store the live TacticState OBJECT, not just pp.
        assert runner._states[s0] is init
        assert isinstance(runner._states[s0], TacticState)
    finally:
        runner.close()


def test_proof_finished_captures_real_tactic_state_id() -> None:
    init = TacticState(pp="⊢ p", id=0, num_goals=1)
    finished = ProofFinished(tactic_state_id=42, message="proof complete")
    runner = LeanDojoRunner(lean_dojo_module=_module(init, {"assumption": finished}))
    try:
        s0 = runner.start(_seed())
        r = runner.run_tactic(s0, "assumption", timeout=10.0)
        assert r.success and r.proof_finished and r.num_goals == 0
        assert r.next_state == "no goals"
        assert r.metadata["result_type"] == "ProofFinished"
        # Critical: with the real field name `tactic_state_id`, the runner must
        # still record the sid in metadata (regression guard for the .id->id+tsid fix).
        assert r.metadata["tactic_state_id"] == 42
        assert r.metadata["num_goals_before"] == 1
    finally:
        runner.close()


def test_tactic_state_after_carries_pp_id_num_goals() -> None:
    init = TacticState(pp="⊢ p ∧ q", id=0, num_goals=1)
    after = TacticState(pp="⊢ p\n\n⊢ q", id=3, num_goals=2)
    runner = LeanDojoRunner(lean_dojo_module=_module(init, {"constructor": after}))
    try:
        s0 = runner.start(_seed())
        r = runner.run_tactic(s0, "constructor", timeout=10.0)
        assert r.success and not r.proof_finished
        assert r.next_state == "⊢ p\n\n⊢ q"
        assert r.num_goals == 2
        assert r.metadata["result_type"] == "TacticState"
        assert r.metadata["tactic_state_id"] == 3
        # The new state must be registered so it can be the parent of a next tactic.
        assert runner._states[r.next_state] is after
    finally:
        runner.close()


def test_lean_error_routes_to_failure_with_error_field() -> None:
    init = TacticState(pp="⊢ p", id=0, num_goals=1)
    err = LeanError(error="unknown identifier 'h'")
    runner = LeanDojoRunner(lean_dojo_module=_module(init, {"exact h": err}))
    try:
        s0 = runner.start(_seed())
        r = runner.run_tactic(s0, "exact h", timeout=10.0)
        assert r.success is False
        assert r.next_state is None
        assert "LeanError" in (r.error or "")
        assert "unknown identifier 'h'" in (r.error or "")
        # Pre-tactic goal count still surfaces in metadata even on failure.
        assert r.metadata["num_goals_before"] == 1
    finally:
        runner.close()


def test_proof_given_up_routes_to_failure() -> None:
    init = TacticState(pp="⊢ p", id=0, num_goals=1)
    runner = LeanDojoRunner(lean_dojo_module=_module(init, {"sorry": ProofGivenUp()}))
    try:
        s0 = runner.start(_seed())
        r = runner.run_tactic(s0, "sorry", timeout=10.0)
        assert r.success is False
        assert r.next_state is None
        assert "ProofGivenUp" in (r.error or "")
    finally:
        runner.close()


def test_dojo_crash_unexpected_eof_appends_actionable_hint() -> None:
    """The well-understood 'Lean REPL died before responding' crash must surface
    a hint pointing the user at the toolchain limitation — without swallowing
    or rewriting the original DojoCrashError message."""
    init = TacticState(pp="⊢ p", id=0, num_goals=1)
    plan = {"assumption": DojoCrashError("Unexpected EOF")}
    runner = LeanDojoRunner(lean_dojo_module=_module(init, plan))
    try:
        s0 = runner.start(_seed())
        r = runner.run_tactic(s0, "assumption", timeout=10.0)
        assert r.success is False
        # Original error text preserved verbatim.
        assert "DojoCrashError" in (r.error or "")
        assert "Unexpected EOF" in (r.error or "")
        # New hint clearly identifies the toolchain limitation.
        assert "elaboration-time IO has no stdin" in (r.error or "")
        assert "LEANDOJO_SETUP.md" in (r.error or "")
    finally:
        runner.close()


def test_dojo_crash_other_message_keeps_message_intact_no_hint() -> None:
    """Crashes that aren't the well-known stdin-EOF must NOT get the hint —
    it would mislead. Original message must survive untouched."""
    init = TacticState(pp="⊢ p", id=0, num_goals=1)
    plan = {"omega": DojoCrashError("internal protocol error: bad sid 99")}
    runner = LeanDojoRunner(lean_dojo_module=_module(init, plan))
    try:
        s0 = runner.start(_seed())
        r = runner.run_tactic(s0, "omega", timeout=10.0)
        assert r.success is False
        assert "DojoCrashError" in (r.error or "")
        assert "bad sid 99" in (r.error or "")
        assert "elaboration-time IO" not in (r.error or "")
    finally:
        runner.close()


def test_run_tac_called_with_object_not_pp_string() -> None:
    """The runner MUST pass the live TacticState object to dojo.run_tac, not its
    pretty-printed string — FakeDojo.run_tac asserts the type."""
    init = TacticState(pp="⊢ p", id=0, num_goals=1)
    runner = LeanDojoRunner(
        lean_dojo_module=_module(init, {"trivial": ProofFinished(tactic_state_id=1)})
    )
    try:
        s0 = runner.start(_seed())
        # If the runner passed s0 (a str), FakeDojo.run_tac's isinstance check fails.
        r = runner.run_tactic(s0, "trivial", timeout=10.0)
        assert r.success and r.proof_finished
    finally:
        runner.close()
