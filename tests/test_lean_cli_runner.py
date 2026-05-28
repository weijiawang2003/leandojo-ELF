"""Tests for LeanCliRunner.

These tests must pass whether or not a Lean toolchain is installed. We never
invoke real `lean` here; instead we monkey-patch the private hooks
(`_invoke_lean` and `_resolve_command`) so the unit under test is the runner
logic itself (template substitution, error mapping, temp-file lifecycle).
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path
from typing import Optional

import pytest

from mini_elf_lean.config import Settings
from mini_elf_lean.lean_runner import (
    LeanCliRunner,
    LeanDojoRunner,
    MockLeanRunner,
    _LeanCliTimeout,
    build_lean_runner,
)
from mini_elf_lean.schemas import TheoremSeed


# ---- helpers ----


def _proc(returncode: int, stderr: str = "", stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["fake", "lean"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _seed_with_template() -> TheoremSeed:
    return TheoremSeed(
        theorem_name="nat_refl",
        theorem_statement="(n : Nat) : n = n",
        initial_state="n : Nat\n⊢ n = n",
        imports=[],
        template="example (n : Nat) : n = n := by\n  __TACTIC__",
        placeholder="__TACTIC__",
    )


# ---- schema backward compat ----


def test_seed_schema_accepts_old_seeds_without_template() -> None:
    """Old seed JSONL must still parse — new fields are optional."""

    seed = TheoremSeed.model_validate(
        {
            "theorem_name": "refl_nat",
            "theorem_statement": "1 + 1 = 2",
            "initial_state": "⊢ 1 + 1 = 2",
        }
    )
    assert seed.template is None
    assert seed.imports == []
    assert seed.placeholder == "__TACTIC__"


def test_seed_schema_accepts_new_template_fields() -> None:
    seed = TheoremSeed.model_validate(
        {
            "theorem_name": "t",
            "theorem_statement": "True",
            "template": "example : True := by\n  HOLE",
            "placeholder": "HOLE",
            "imports": ["import Mathlib.Tactic"],
        }
    )
    assert seed.template is not None
    assert "HOLE" in seed.template
    assert seed.imports == ["import Mathlib.Tactic"]


# ---- factory ----


def test_factory_recognizes_lean_cli() -> None:
    s = Settings(lean_backend="lean-cli", llm_backend="mock")
    runner = build_lean_runner(s)
    try:
        assert isinstance(runner, LeanCliRunner)
        assert runner.name == "lean-cli"
    finally:
        runner.close()


def test_factory_normalizes_underscore_spelling() -> None:
    """`lean_cli` (underscore) should also resolve to LeanCliRunner."""

    s = Settings(lean_backend="lean_cli", llm_backend="mock")
    runner = build_lean_runner(s)
    try:
        assert isinstance(runner, LeanCliRunner)
    finally:
        runner.close()


def test_factory_still_recognizes_mock_and_leandojo_strings() -> None:
    assert isinstance(build_lean_runner(Settings(lean_backend="mock")), MockLeanRunner)
    # leandojo's constructor tries to import lean_dojo; we expect a clear
    # RuntimeError when it's not installed, not an obscure ImportError.
    try:
        build_lean_runner(Settings(lean_backend="leandojo"))
    except RuntimeError as exc:
        assert "lean-dojo" in str(exc).lower() or "lean_dojo" in str(exc).lower()
    else:
        # If lean_dojo happens to be installed, the call should return the
        # scaffold object instead of raising. Either branch is acceptable.
        pass


def test_factory_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unknown Lean backend"):
        build_lean_runner(Settings(lean_backend="not-a-real-backend"))


# ---- template substitution ----


def test_render_source_substitutes_placeholder() -> None:
    runner = LeanCliRunner()
    src = runner._render_source(_seed_with_template(), "rfl")
    assert "rfl" in src
    assert "__TACTIC__" not in src


def test_render_source_prepends_imports_with_blank_line() -> None:
    runner = LeanCliRunner()
    seed = TheoremSeed(
        theorem_name="t",
        theorem_statement="True",
        template="example : True := by\n  __TACTIC__",
        placeholder="__TACTIC__",
        imports=["import Mathlib.Tactic", "import Std"],
    )
    src = runner._render_source(seed, "trivial")
    assert src.startswith("import Mathlib.Tactic\nimport Std\n\n")
    assert "trivial" in src


def test_render_source_omits_imports_block_when_empty() -> None:
    runner = LeanCliRunner()
    src = runner._render_source(_seed_with_template(), "rfl")
    assert not src.startswith("\n")
    assert "import " not in src


# ---- start() validates template up-front ----


def test_start_requires_template() -> None:
    runner = LeanCliRunner()
    seed = TheoremSeed(theorem_name="no_template", theorem_statement="True")
    with pytest.raises(ValueError, match="requires seed.template"):
        runner.start(seed)


def test_start_requires_placeholder_to_appear_in_template() -> None:
    runner = LeanCliRunner()
    seed = TheoremSeed(
        theorem_name="bad",
        theorem_statement="True",
        template="example : True := by trivial",  # placeholder missing
        placeholder="__TACTIC__",
    )
    with pytest.raises(ValueError, match="placeholder"):
        runner.start(seed)


# ---- run_tactic happy & sad paths (subprocess mocked) ----


def test_run_tactic_returns_success_on_exit_code_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = LeanCliRunner()
    runner.start(_seed_with_template())

    seen: dict[str, object] = {}

    def fake_invoke(self: LeanCliRunner, argv: list[str], lean_file: str, *, timeout: float):
        # Confirm the temp file actually contains the substituted tactic.
        content = Path(lean_file).read_text(encoding="utf-8")
        seen["content"] = content
        seen["argv"] = argv
        seen["timeout"] = timeout
        return _proc(returncode=0)

    monkeypatch.setattr(LeanCliRunner, "_resolve_command", lambda self: ["fake-lean"])
    monkeypatch.setattr(LeanCliRunner, "_invoke_lean", fake_invoke)

    result = runner.run_tactic("⊢ n = n", "rfl", timeout=10.0)
    assert result.success is True
    assert result.proof_finished is True
    assert result.error is None
    assert result.next_state == LeanCliRunner._VERIFIED_MARKER
    assert "rfl" in seen["content"]  # type: ignore[index]
    assert seen["argv"] == ["fake-lean"]


def test_run_tactic_returns_failure_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = LeanCliRunner()
    runner.start(_seed_with_template())

    monkeypatch.setattr(LeanCliRunner, "_resolve_command", lambda self: ["fake-lean"])
    monkeypatch.setattr(
        LeanCliRunner,
        "_invoke_lean",
        lambda self, argv, lean_file, *, timeout: _proc(
            returncode=1, stderr="error: unknown tactic 'foo'"
        ),
    )

    result = runner.run_tactic("⊢ n = n", "foo", timeout=10.0)
    assert result.success is False
    assert result.proof_finished is False
    assert "unknown tactic" in (result.error or "")


def test_run_tactic_maps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = LeanCliRunner()
    runner.start(_seed_with_template())

    def fake_invoke(self, argv, lean_file, *, timeout):
        raise _LeanCliTimeout()

    monkeypatch.setattr(LeanCliRunner, "_resolve_command", lambda self: ["fake-lean"])
    monkeypatch.setattr(LeanCliRunner, "_invoke_lean", fake_invoke)

    result = runner.run_tactic("⊢ n = n", "stuck", timeout=0.1)
    assert result.success is False
    assert result.error == "timeout"


def test_run_tactic_handles_missing_command(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = LeanCliRunner(command="")  # force autodetect path
    runner.start(_seed_with_template())

    # Pretend neither lake nor lean is on PATH.
    monkeypatch.setattr("mini_elf_lean.lean_runner.shutil.which", lambda _: None)
    result = runner.run_tactic("⊢ n = n", "rfl", timeout=10.0)
    assert result.success is False
    assert "neither" in (result.error or "").lower() or "lean" in (result.error or "").lower()


def test_run_tactic_handles_missing_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = LeanCliRunner()
    runner.start(_seed_with_template())

    def fake_invoke(self, argv, lean_file, *, timeout):
        raise FileNotFoundError(2, "No such file", "lean")

    monkeypatch.setattr(LeanCliRunner, "_resolve_command", lambda self: ["lean"])
    monkeypatch.setattr(LeanCliRunner, "_invoke_lean", fake_invoke)

    result = runner.run_tactic("⊢ n = n", "rfl", timeout=10.0)
    assert result.success is False
    assert "command not found" in (result.error or "")


def test_run_tactic_without_start_returns_clean_error() -> None:
    runner = LeanCliRunner()
    result = runner.run_tactic("⊢ n = n", "rfl", timeout=10.0)
    assert result.success is False
    assert "start()" in (result.error or "")


def test_temp_file_is_cleaned_up_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = LeanCliRunner()
    runner.start(_seed_with_template())

    captured_path: dict[str, Optional[str]] = {"path": None}

    def fake_invoke(self, argv, lean_file, *, timeout):
        captured_path["path"] = lean_file
        return _proc(returncode=0)

    monkeypatch.setattr(LeanCliRunner, "_resolve_command", lambda self: ["fake-lean"])
    monkeypatch.setattr(LeanCliRunner, "_invoke_lean", fake_invoke)

    runner.run_tactic("⊢ n = n", "rfl", timeout=10.0)
    assert captured_path["path"] is not None
    assert not Path(captured_path["path"]).exists(), "temp .lean file should be deleted"


def test_temp_file_kept_when_keep_temp_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner = LeanCliRunner(keep_temp=True, working_dir=tmp_path)
    runner.start(_seed_with_template())

    captured: dict[str, Optional[str]] = {"path": None}

    def fake_invoke(self, argv, lean_file, *, timeout):
        captured["path"] = lean_file
        return _proc(returncode=0)

    monkeypatch.setattr(LeanCliRunner, "_resolve_command", lambda self: ["fake-lean"])
    monkeypatch.setattr(LeanCliRunner, "_invoke_lean", fake_invoke)

    runner.run_tactic("⊢ n = n", "rfl", timeout=10.0)
    assert captured["path"] is not None
    p = Path(captured["path"])
    assert p.exists(), "temp file should be kept when keep_temp=True"
    # Cleanup so we don't litter tmp_path between tests.
    p.unlink()


def test_command_env_var_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINI_ELF_LEAN_COMMAND", "lake env lean --some-flag")
    runner = LeanCliRunner()
    assert runner._resolve_command() == ["lake", "env", "lean", "--some-flag"]


# ---- end-to-end with the existing collector, no real Lean ----


def test_collector_uses_lean_cli_when_settings_select_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Smoke test: the collector should drive LeanCliRunner via the factory
    and successfully write verified records when subprocess returns rc=0."""

    from mini_elf_lean.collector import CollectionConfig, collect
    from mini_elf_lean.io_utils import read_jsonl, write_jsonl

    seeds_path = tmp_path / "seeds.jsonl"
    out_path = tmp_path / "ok.jsonl"
    failed_path = tmp_path / "bad.jsonl"
    write_jsonl(seeds_path, [_seed_with_template()])

    monkeypatch.setattr(LeanCliRunner, "_resolve_command", lambda self: ["fake-lean"])
    # Always succeed -- we just want to confirm the wiring.
    monkeypatch.setattr(
        LeanCliRunner,
        "_invoke_lean",
        lambda self, argv, lean_file, *, timeout: _proc(returncode=0),
    )

    settings = Settings(lean_backend="lean-cli", llm_backend="mock", tactic_timeout_s=5.0)
    cfg = CollectionConfig(
        seeds_path=seeds_path,
        success_out=out_path,
        failed_out=failed_path,
        num_candidates=3,
        temperature=0.0,
        max_depth=1,
        settings=settings,
    )
    summary = collect(cfg)
    assert summary.seeds_processed == 1
    assert summary.tactics_succeeded > 0
    rows = list(read_jsonl(out_path))
    assert all(r["success"] for r in rows)
    assert all(r["state_after"] == LeanCliRunner._VERIFIED_MARKER for r in rows)
