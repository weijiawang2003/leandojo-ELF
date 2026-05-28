"""Tests for LeanDojoRunner.

LeanDojo itself is NOT installed in this environment (and would need a Lean
toolchain + a pre-traced repo). So every test here injects a *fake* lean_dojo
module that mimics the duck-typed shapes the runner relies on:

  - an ongoing state is any object with a ``.pp`` attribute (``TacticState``);
  - a finished proof is a class literally named ``ProofFinished``;
  - anything else (e.g. ``LeanError``) is treated as an error.

This lets us test the runner's logic (session lifecycle, state registry, result
mapping, error routing) without faking a real Lean run.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

from mini_elf_lean.config import Settings
from mini_elf_lean.lean_runner import LeanDojoRunner, get_lean_runner
from mini_elf_lean.schemas import TheoremSeed

_LEAN_DOJO_INSTALLED = importlib.util.find_spec("lean_dojo") is not None


# ---- fake lean_dojo objects ----


class FakeTacticState:
    def __init__(self, pp: str, num_goals: int | None = None, id: int = 0) -> None:
        self.pp = pp
        if num_goals is not None:
            self.num_goals = num_goals
        self.id = id


class ProofFinished:  # name matters: runner matches on the class name
    def __init__(self, id: int = 1, message: str = "no goals") -> None:
        self.id = id
        self.message = message


class LeanError:  # error-like: no `.pp`, carries an `.error` message
    def __init__(self, error: str = "lean error") -> None:
        self.error = error


class FakeDojo:
    """Context manager + run_tac, scripted by a {tactic: result|callable} map."""

    def __init__(self, theorem, init_state, transitions, calls) -> None:
        self.theorem = theorem
        self._init = init_state
        self._transitions = transitions
        self._calls = calls

    def __enter__(self):
        return self, self._init

    def __exit__(self, *exc):
        self._calls.append(("exit",))
        return False

    def run_tac(self, state, tactic):
        self._calls.append(("run_tac", getattr(state, "pp", None), tactic))
        fn = self._transitions.get(tactic)
        if fn is None:
            return LeanError(f"unknown tactic '{tactic}'")
        return fn(state) if callable(fn) else fn


def make_fake_module(init_state, transitions, *, record=None, calls=None):
    calls = calls if calls is not None else []

    class LeanGitRepo:
        def __init__(self, url, commit):
            self.url, self.commit = url, commit

    class Theorem:
        def __init__(self, repo, file_path, full_name):
            self.repo, self.file_path, self.full_name = repo, file_path, full_name
            if record is not None:
                record["full_name"] = full_name
                record["file_path"] = file_path

    def Dojo(theorem, **kwargs):
        if record is not None:
            record["dojo_kwargs"] = kwargs
        return FakeDojo(theorem, init_state, transitions, calls)

    return types.SimpleNamespace(
        LeanGitRepo=LeanGitRepo,
        Theorem=Theorem,
        Dojo=Dojo,
        ProofFinished=ProofFinished,
        LeanError=LeanError,
        TacticState=FakeTacticState,
    )


def _dojo_seed(**overrides) -> TheoremSeed:
    base = dict(
        theorem_name="and_comm_toy",
        theorem_statement="(p q : Prop) : p ∧ q → q ∧ p",
        repo_url="https://github.com/example/repo",
        commit="abc123",
        file_path="Example/Basic.lean",
        full_name="Example.and_comm_toy",
    )
    base.update(overrides)
    return TheoremSeed(**base)


# ---- missing import ----


@pytest.mark.skipif(_LEAN_DOJO_INSTALLED, reason="lean_dojo is actually installed here")
def test_missing_lean_dojo_gives_clear_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="lean-dojo"):
        LeanDojoRunner()  # no injected module -> real import -> clean error


@pytest.mark.skipif(_LEAN_DOJO_INSTALLED, reason="lean_dojo is actually installed here")
def test_factory_leandojo_missing_is_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="lean-dojo"):
        get_lean_runner(Settings(lean_backend="leandojo"))


# ---- seed validation ----


def test_start_requires_repo_commit_filepath() -> None:
    fake = make_fake_module(FakeTacticState("⊢ True", 1), {})
    runner = LeanDojoRunner(lean_dojo_module=fake)
    with pytest.raises(ValueError, match="repo_url, commit, and file_path"):
        runner.start(TheoremSeed(theorem_name="t", theorem_statement="True"))


def test_start_uses_full_name_when_present() -> None:
    rec: dict = {}
    fake = make_fake_module(FakeTacticState("⊢ True", 1), {}, record=rec)
    runner = LeanDojoRunner(lean_dojo_module=fake)
    try:
        runner.start(_dojo_seed())
        assert rec["full_name"] == "Example.and_comm_toy"
    finally:
        runner.close()


def test_start_falls_back_to_theorem_name() -> None:
    rec: dict = {}
    fake = make_fake_module(FakeTacticState("⊢ True", 1), {}, record=rec)
    runner = LeanDojoRunner(lean_dojo_module=fake)
    try:
        runner.start(_dojo_seed(full_name=None))
        assert rec["full_name"] == "and_comm_toy"
    finally:
        runner.close()


# ---- result mapping ----


def test_ongoing_tactic_returns_true_state_after() -> None:
    init = FakeTacticState("p q : Prop\nh : p ∧ q\n⊢ q ∧ p", num_goals=1)
    after = FakeTacticState("p q : Prop\nhp : p\nhq : q\n⊢ q ∧ p", num_goals=1, id=7)
    fake = make_fake_module(init, {"rcases h with ⟨hp, hq⟩": after})
    runner = LeanDojoRunner(lean_dojo_module=fake)
    try:
        state0 = runner.start(_dojo_seed())
        assert state0 == "p q : Prop\nh : p ∧ q\n⊢ q ∧ p"
        res = runner.run_tactic(state0, "rcases h with ⟨hp, hq⟩", timeout=10.0)
        assert res.success
        assert res.proof_finished is False
        assert res.next_state == "p q : Prop\nhp : p\nhq : q\n⊢ q ∧ p"
        assert res.num_goals == 1
        assert res.metadata["num_goals_before"] == 1
        assert res.metadata["result_type"] == "FakeTacticState"
        assert res.metadata["tactic_state_id"] == 7
    finally:
        runner.close()


def test_proof_finished_maps_to_completion() -> None:
    init = FakeTacticState("⊢ q ∧ p", num_goals=1)
    fake = make_fake_module(init, {"exact ⟨hq, hp⟩": ProofFinished()})
    runner = LeanDojoRunner(lean_dojo_module=fake)
    try:
        state0 = runner.start(_dojo_seed())
        res = runner.run_tactic(state0, "exact ⟨hq, hp⟩", timeout=10.0)
        assert res.success
        assert res.proof_finished is True
        assert res.next_state == "no goals"
        assert res.num_goals == 0
        assert res.metadata["result_type"] == "ProofFinished"
    finally:
        runner.close()


def test_lean_error_routes_to_failure() -> None:
    init = FakeTacticState("⊢ q ∧ p", num_goals=1)
    fake = make_fake_module(init, {})  # any tactic -> LeanError(unknown tactic)
    runner = LeanDojoRunner(lean_dojo_module=fake)
    try:
        state0 = runner.start(_dojo_seed())
        res = runner.run_tactic(state0, "garbage", timeout=10.0)
        assert res.success is False
        assert res.next_state is None
        assert "LeanError" in (res.error or "")
        assert "unknown tactic" in (res.error or "")
    finally:
        runner.close()


def test_run_tac_exception_is_caught_not_fatal() -> None:
    init = FakeTacticState("⊢ True", num_goals=1)

    def boom(_state):
        raise RuntimeError("dojo crashed")

    fake = make_fake_module(init, {"boom": boom})
    runner = LeanDojoRunner(lean_dojo_module=fake)
    try:
        state0 = runner.start(_dojo_seed())
        res = runner.run_tactic(state0, "boom", timeout=10.0)
        assert res.success is False
        assert "RuntimeError" in (res.error or "")
        assert "dojo crashed" in (res.error or "")
    finally:
        runner.close()


# ---- state registry / multi-candidate fan-out ----


def test_multiple_candidates_run_from_same_initial_state() -> None:
    init = FakeTacticState("⊢ q ∧ p", num_goals=1)
    after = FakeTacticState("⊢ q\n⊢ p", num_goals=2)
    fake = make_fake_module(init, {"constructor": after, "tauto": ProofFinished()})
    runner = LeanDojoRunner(lean_dojo_module=fake)
    try:
        state0 = runner.start(_dojo_seed())
        r1 = runner.run_tactic(state0, "constructor", timeout=10.0)
        # Running a *second* candidate from the same starting state must work.
        r2 = runner.run_tactic(state0, "tauto", timeout=10.0)
        assert r1.success and r1.num_goals == 2 and not r1.proof_finished
        assert r2.success and r2.proof_finished
        # The new state from r1 is now registered and runnable.
        assert r1.next_state in runner._states
    finally:
        runner.close()


def test_run_tactic_without_start_returns_clean_error() -> None:
    fake = make_fake_module(FakeTacticState("⊢ True", 1), {})
    runner = LeanDojoRunner(lean_dojo_module=fake)
    res = runner.run_tactic("⊢ True", "trivial", timeout=10.0)
    assert res.success is False
    assert "start()" in (res.error or "")


def test_unknown_state_string_returns_clean_error() -> None:
    fake = make_fake_module(FakeTacticState("⊢ True", 1), {})
    runner = LeanDojoRunner(lean_dojo_module=fake)
    try:
        runner.start(_dojo_seed())
        res = runner.run_tactic("⊢ some other state never seen", "trivial", timeout=10.0)
        assert res.success is False
        assert "no live TacticState" in (res.error or "")
    finally:
        runner.close()


def test_close_exits_dojo_session() -> None:
    calls: list = []
    init = FakeTacticState("⊢ True", num_goals=1)
    fake = make_fake_module(init, {}, calls=calls)
    runner = LeanDojoRunner(lean_dojo_module=fake)
    runner.start(_dojo_seed())
    runner.close()
    assert ("exit",) in calls
    # Idempotent: a second close must not raise.
    runner.close()


# ---- end-to-end through the collector (fake leandojo) ----


def test_collector_records_true_transitions_with_fake_leandojo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The collector + manual-file candidates + a fake-backed LeanDojoRunner must
    write verified records carrying real state_after and a true num_goals_before."""

    import mini_elf_lean.collector as collector_mod
    from mini_elf_lean.io_utils import read_jsonl, write_jsonl

    init = FakeTacticState("p q : Prop\nh : p ∧ q\n⊢ q ∧ p", num_goals=1)
    after = FakeTacticState("p q : Prop\nhp : p\nhq : q\n⊢ q ∧ p", num_goals=1, id=2)
    fake = make_fake_module(
        init,
        {
            "rcases h with ⟨hp, hq⟩": after,
            "exact ⟨h.2, h.1⟩": ProofFinished(),
            # "bogus" -> LeanError (default)
        },
    )
    fake_runner = LeanDojoRunner(lean_dojo_module=fake)
    monkeypatch.setattr(collector_mod, "get_lean_runner", lambda settings: fake_runner)

    seeds = tmp_path / "seeds.jsonl"
    cand = tmp_path / "cand.jsonl"
    out = tmp_path / "ok.jsonl"
    failed = tmp_path / "bad.jsonl"
    write_jsonl(seeds, [_dojo_seed()])
    # No state_before -> unambiguous name-only match (one record for the theorem).
    write_jsonl(
        cand,
        [
            {
                "theorem_name": "and_comm_toy",
                "candidates": ["rcases h with ⟨hp, hq⟩", "exact ⟨h.2, h.1⟩", "bogus"],
                "source": "claude_code_agent",
                "prompt_style": "diverse",
            }
        ],
    )

    cfg = collector_mod.CollectionConfig(
        seeds_path=seeds,
        success_out=out,
        failed_out=failed,
        num_candidates=5,
        temperature=0.0,
        manual_candidates_path=cand,
        settings=Settings(llm_backend="manual-file", lean_backend="leandojo"),
    )
    summary = collector_mod.collect(cfg)

    assert summary.tactics_attempted == 3
    ok = list(read_jsonl(out))
    bad = list(read_jsonl(failed))

    assert all(r["backend"] == "leandojo" for r in ok)
    assert all(r["num_goals_before"] == 1 for r in ok)  # from the real TacticState
    # rcases -> ongoing real state_after (not a placeholder)
    rcases = [r for r in ok if r["tactic"].startswith("rcases")][0]
    assert rcases["state_after"] == "p q : Prop\nhp : p\nhq : q\n⊢ q ∧ p"
    assert rcases["state_changed"] is True
    assert rcases["proof_finished"] is False
    assert rcases["metadata"]["result_type"] == "FakeTacticState"
    # exact -> finished
    assert any(r["proof_finished"] for r in ok)
    # bogus -> failure
    assert any(r["tactic"] == "bogus" and not r["success"] for r in bad)
