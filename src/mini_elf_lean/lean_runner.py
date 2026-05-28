"""LeanRunner interface, plus Mock / LeanCli / LeanDojo implementations.

Pipeline code MUST only use the `LeanRunner` Protocol. The LeanDojo backend is
fully isolated here so the rest of the project remains usable without a Lean
toolchain installed. The LeanCli backend is the lightweight bridge between
the mock and LeanDojo: it shells out to `lean` (or `lake env lean`) on a
temp file built from the seed's `template` + the candidate tactic.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from .config import Settings
from .schemas import TheoremSeed

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TacticResult:
    """Unified result returned by every LeanRunner backend.

    ``metadata`` is an optional bag for backend-specific extras (e.g. LeanDojo's
    true ``num_goals_before`` and tactic-state id). The collector merges it into
    the trace record and treats a ``num_goals_before`` key as an authoritative
    override of its own heuristic count. Mock / lean-cli leave it empty.
    """

    next_state: Optional[str]
    proof_finished: bool
    error: Optional[str]
    num_goals: int
    elapsed_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.error is None


class LeanRunner(Protocol):
    name: str

    def start(self, seed: TheoremSeed) -> str:
        """Open a proof session for `seed` and return the initial state."""

    def run_tactic(self, state: str, tactic: str, *, timeout: float) -> TacticResult:
        """Run `tactic` from `state` and return the unified result."""

    def close(self) -> None:
        """Release any backend resources held by the runner."""


# ---------------- Mock ----------------


def _count_goals(state: str) -> int:
    """Cheap heuristic for the mock backend."""

    if not state or state.strip() == "no goals":
        return 0
    return max(1, len([b for b in state.split("\n\n") if b.strip()]))


class MockLeanRunner:
    """Deterministic runner with hand-written rules.

    The mock implements just enough behavior to exercise the full pipeline:
    - `rfl`, `decide`, `trivial`, `omega`, `norm_num` finish a goal.
    - `intro` / `intros` "consume" a quantifier line, producing a new state.
    - `simp` reduces goal count by 1 when there are goals.
    - Anything else fails with a generic error so failure paths are tested.
    """

    name = "mock"

    _FINISHERS = {"rfl", "decide", "trivial", "omega", "norm_num"}

    def start(self, seed: TheoremSeed) -> str:
        if seed.initial_state is not None:
            return seed.initial_state
        return f"\u22a2 {seed.theorem_statement}"

    def run_tactic(self, state: str, tactic: str, *, timeout: float) -> TacticResult:
        t0 = time.perf_counter()
        head = tactic.split()[0] if tactic.strip() else ""

        if head in self._FINISHERS:
            return TacticResult(
                next_state="no goals",
                proof_finished=True,
                error=None,
                num_goals=0,
                elapsed_ms=(time.perf_counter() - t0) * 1000,
            )

        if head in {"intro", "intros"}:
            new_state = state.replace("\u22a2 \u2200", "\u22a2", 1).replace("\u22a2 \u2192", "\u22a2", 1)
            if new_state == state:
                new_state = state + "\nh : _"
            return TacticResult(
                next_state=new_state,
                proof_finished=False,
                error=None,
                num_goals=_count_goals(new_state),
                elapsed_ms=(time.perf_counter() - t0) * 1000,
            )

        if head == "simp":
            cur = _count_goals(state)
            if cur <= 1:
                return TacticResult(
                    next_state="no goals",
                    proof_finished=True,
                    error=None,
                    num_goals=0,
                    elapsed_ms=(time.perf_counter() - t0) * 1000,
                )
            blocks = [b for b in state.split("\n\n") if b.strip()]
            new_state = "\n\n".join(blocks[:-1])
            return TacticResult(
                next_state=new_state,
                proof_finished=False,
                error=None,
                num_goals=_count_goals(new_state),
                elapsed_ms=(time.perf_counter() - t0) * 1000,
            )

        return TacticResult(
            next_state=None,
            proof_finished=False,
            error=f"mock: unknown tactic '{head}'",
            num_goals=_count_goals(state),
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    def close(self) -> None:
        return None


# ---------------- LeanCli (real Lean subprocess on whole templates) ----------------


class LeanCliRunner:
    """Verify a tactic by substituting it into the seed template and running
    `lean` (or `lake env lean`) on the resulting temp file.

    The lean-cli backend is intentionally coarse-grained: a tactic is judged
    successful iff the *whole file* typechecks. It therefore does not yet
    yield intermediate proof states the way LeanDojo will. That is fine for
    the first milestone -- we just want a real-Lean verified dataset before
    investing in LeanDojo setup.

    Configuration:
      - ``MINI_ELF_LEAN_COMMAND`` -- override the lean command (e.g.
        ``lake env lean``). Whitespace tokens become argv entries.
      - ``MINI_ELF_LEAN_KEEP_TEMP=1`` -- keep generated .lean files for
        debugging instead of unlinking them.
    """

    name = "lean-cli"
    _VERIFIED_MARKER = "<verified by lean-cli>"
    _MAX_DIAG_BYTES = 1500

    def __init__(
        self,
        *,
        command: Optional[str] = None,
        keep_temp: Optional[bool] = None,
        working_dir: Optional[Path] = None,
    ) -> None:
        self._command_str = command if command is not None else os.environ.get(
            "MINI_ELF_LEAN_COMMAND", ""
        )
        if keep_temp is None:
            keep_temp = os.environ.get("MINI_ELF_LEAN_KEEP_TEMP", "") not in (
                "", "0", "false", "False",
            )
        self._keep_temp = bool(keep_temp)
        self._working_dir = working_dir
        self._current_seed: Optional[TheoremSeed] = None

    def start(self, seed: TheoremSeed) -> str:
        if not seed.template:
            raise ValueError(
                f"LeanCliRunner requires seed.template. Seed {seed.theorem_name!r} has none."
            )
        if seed.placeholder not in seed.template:
            raise ValueError(
                f"Seed {seed.theorem_name!r}: placeholder {seed.placeholder!r} not "
                f"found in template."
            )
        self._current_seed = seed
        return seed.initial_state if seed.initial_state else f"\u22a2 {seed.theorem_statement}"

    def run_tactic(self, state: str, tactic: str, *, timeout: float) -> TacticResult:
        t0 = time.perf_counter()
        seed = self._current_seed
        if seed is None:
            return self._fail(t0, "LeanCliRunner: start() was not called before run_tactic")

        try:
            source = self._render_source(seed, tactic)
        except ValueError as exc:
            return self._fail(t0, str(exc))

        try:
            argv = self._resolve_command()
        except RuntimeError as exc:
            return self._fail(t0, str(exc))

        tmp_path = self._write_temp_file(source)
        try:
            proc = self._invoke_lean(argv, tmp_path, timeout=timeout)
        except _LeanCliTimeout:
            return self._fail(t0, "timeout")
        except FileNotFoundError as exc:
            return self._fail(t0, f"command not found: {exc.filename or argv[0]}")
        except OSError as exc:
            return self._fail(t0, f"subprocess error: {exc!r}")
        finally:
            self._cleanup_temp(tmp_path)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        truncated_tactic = (tactic[:60] + "...") if len(tactic) > 60 else tactic
        logger.debug(
            "lean-cli rc=%d theorem=%s tactic=%r elapsed_ms=%.1f",
            proc.returncode,
            seed.theorem_name,
            truncated_tactic,
            elapsed_ms,
        )

        if proc.returncode == 0:
            return TacticResult(
                next_state=self._VERIFIED_MARKER,
                proof_finished=True,
                error=None,
                num_goals=0,
                elapsed_ms=elapsed_ms,
            )

        diag = self._collect_diagnostics(proc)
        return TacticResult(
            next_state=None,
            proof_finished=False,
            error=diag or f"exit code {proc.returncode}",
            num_goals=1,
            elapsed_ms=elapsed_ms,
        )

    def close(self) -> None:
        self._current_seed = None

    # ---- internals ----

    def _render_source(self, seed: TheoremSeed, tactic: str) -> str:
        if not seed.template or seed.placeholder not in seed.template:
            raise ValueError(
                f"Seed {seed.theorem_name!r}: template/placeholder invalid at run time."
            )
        body = seed.template.replace(seed.placeholder, tactic)
        imports_block = "\n".join(line for line in seed.imports if line.strip())
        if imports_block:
            return imports_block + "\n\n" + body + "\n"
        return body + "\n"

    def _resolve_command(self) -> list:
        if self._command_str:
            return shlex.split(self._command_str)
        if shutil.which("lake"):
            return ["lake", "env", "lean"]
        if shutil.which("lean"):
            return ["lean"]
        raise RuntimeError(
            "lean-cli backend: neither `lake` nor `lean` was found on PATH. "
            "Install a Lean toolchain (e.g. via elan: https://lean-lang.org) "
            "or set MINI_ELF_LEAN_COMMAND."
        )

    def _write_temp_file(self, source: str) -> str:
        fh = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".lean",
            prefix="mini_elf_lean_",
            delete=False,
            encoding="utf-8",
            dir=str(self._working_dir) if self._working_dir else None,
        )
        try:
            fh.write(source)
        finally:
            fh.close()
        return fh.name

    def _invoke_lean(self, argv, lean_file, *, timeout):
        try:
            return subprocess.run(
                argv + [lean_file],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self._working_dir) if self._working_dir else None,
            )
        except subprocess.TimeoutExpired as exc:
            raise _LeanCliTimeout() from exc

    def _cleanup_temp(self, path):
        if self._keep_temp:
            logger.debug("lean-cli: keeping temp file %s", path)
            return
        try:
            os.unlink(path)
        except OSError as exc:
            logger.warning("lean-cli: could not unlink temp file %s: %s", path, exc)

    def _collect_diagnostics(self, proc):
        parts = []
        if proc.stderr:
            parts.append(proc.stderr)
        if proc.stdout:
            parts.append(proc.stdout)
        diag = "\n".join(parts).strip()
        if len(diag) > self._MAX_DIAG_BYTES:
            diag = diag[: self._MAX_DIAG_BYTES] + "...[truncated]"
        return diag

    def _fail(self, t0, msg):
        return TacticResult(
            next_state=None,
            proof_finished=False,
            error=msg,
            num_goals=1,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )


class _LeanCliTimeout(Exception):
    """Internal signal for subprocess timeouts, kept out of the public API."""


# ---------------- LeanDojo (real proof-state transitions) ----------------


def _import_lean_dojo():
    """Import lean_dojo, turning a missing package into a clear RuntimeError."""

    try:
        import lean_dojo  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "lean-dojo is not installed. `pip install lean-dojo` and set up a "
            "Lean toolchain + traced repo before selecting "
            "MINI_ELF_LEAN_BACKEND=leandojo. See the lean-dojo-integration skill."
        ) from exc
    return lean_dojo


class LeanDojoRunner:
    """Real Lean execution backed by LeanDojo, giving TRUE proof-state
    transitions ``state_before -> tactic -> state_after``.

    Unlike ``LeanCliRunner`` (which only confirms a whole template file
    typechecks), this backend opens an interactive ``Dojo`` session for a
    theorem and runs each candidate tactic against a live ``TacticState``,
    returning the actual resulting state and goal count.

    Interface note: the ``LeanRunner`` protocol passes proof *states as strings*,
    but LeanDojo needs the live ``TacticState`` *object*. We bridge this by
    keeping a registry mapping each state's pretty-printed string back to its
    ``TacticState`` object. ``start()`` seeds the registry with the initial
    state; every successful tactic registers its resulting state too. Because
    LeanDojo ``TacticState`` handles are immutable, multiple candidates can be
    run from the same state (the collector's per-state fan-out works unchanged).

    LeanDojo class/attribute names vary across versions, so result mapping is
    duck-typed rather than ``isinstance``-based: a result with a ``.pp``
    attribute is an ongoing ``TacticState``; a ``ProofFinished`` closes the
    goal; anything else is treated as an error (``LeanError`` / ``TacticError``
    / ``ProofGivenUp`` / ``Dojo*Error`` / ...).
    """

    name = "leandojo"

    def __init__(self, *, lean_dojo_module=None, hard_timeout: Optional[float] = None) -> None:
        # Allow tests to inject a fake module; otherwise import the real one.
        self._ld = lean_dojo_module if lean_dojo_module is not None else _import_lean_dojo()
        self._hard_timeout = hard_timeout
        self._dojo = None
        self._dojo_cm = None
        self._states: dict = {}      # pp string -> live TacticState object
        self._seed: Optional[TheoremSeed] = None

    # ---- session lifecycle ----

    def start(self, seed: TheoremSeed) -> str:
        if not (seed.repo_url and seed.commit and seed.file_path):
            raise ValueError(
                "LeanDojo seeds need repo_url, commit, and file_path "
                f"(theorem {seed.theorem_name!r} is missing one of them)."
            )
        self.close()  # ensure no leaked previous session

        full_name = seed.full_name or seed.theorem_name
        ld = self._ld
        repo = ld.LeanGitRepo(seed.repo_url, seed.commit)
        theorem = ld.Theorem(repo, seed.file_path, full_name)
        self._dojo_cm = self._make_dojo(theorem)
        self._dojo, init_state = self._dojo_cm.__enter__()
        self._seed = seed

        pp = self._pp(init_state)
        self._states = {pp: init_state}
        return pp

    def _make_dojo(self, theorem):
        if self._hard_timeout:
            try:
                return self._ld.Dojo(theorem, hard_timeout=self._hard_timeout)
            except TypeError:  # older LeanDojo without the kwarg
                pass
        return self._ld.Dojo(theorem)

    def run_tactic(self, state: str, tactic: str, *, timeout: float) -> TacticResult:
        t0 = time.perf_counter()
        if self._dojo is None:
            return self._fail(t0, "LeanDojoRunner: start() was not called before run_tactic")

        before = self._states.get(state)
        if before is None:
            return self._fail(
                t0,
                "LeanDojoRunner: no live TacticState for the given state string; "
                "state strings must originate from this runner's start()/run_tactic().",
            )

        try:
            result = self._dojo.run_tac(before, tactic)
        except Exception as exc:  # noqa: BLE001 - never let a backend error kill the loop
            logger.debug("leandojo run_tac raised for %r: %r", tactic[:60], exc)
            return self._fail(t0, f"{type(exc).__name__}: {exc}", before=before, state=state)

        return self._map_result(result, before=before, state_before=state, t0=t0)

    def close(self) -> None:
        if self._dojo_cm is not None:
            try:
                self._dojo_cm.__exit__(None, None, None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error closing LeanDojo session: %s", exc)
        self._dojo_cm = None
        self._dojo = None
        self._states = {}
        self._seed = None

    # ---- result mapping (duck-typed; version-tolerant) ----

    def _map_result(self, result, *, before, state_before: str, t0: float) -> TacticResult:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        name = type(result).__name__
        before_goals = self._goal_count(before, state_before)
        meta: Dict[str, Any] = {"result_type": name}
        if before_goals is not None:
            meta["num_goals_before"] = before_goals
        sid = getattr(result, "id", None)
        if sid is not None:
            meta["tactic_state_id"] = sid

        # 1. Proof completed.
        if name == "ProofFinished" or getattr(result, "proof_finished", None) is True:
            return TacticResult(
                next_state="no goals", proof_finished=True, error=None,
                num_goals=0, elapsed_ms=elapsed_ms, metadata=meta,
            )

        # 2. Ongoing tactic state (has a pretty-printed form).
        if hasattr(result, "pp"):
            pp = self._pp(result)
            ng = self._goal_count(result, pp)
            ng = 0 if ng is None else ng
            self._states[pp] = result  # register so multi-step / fan-out works
            return TacticResult(
                next_state=pp, proof_finished=(ng == 0), error=None,
                num_goals=ng, elapsed_ms=elapsed_ms, metadata=meta,
            )

        # 3. Anything else is an error-like result.
        msg = (
            getattr(result, "error", None)
            or getattr(result, "message", None)
            or str(result)
        )
        return TacticResult(
            next_state=None, proof_finished=False, error=f"{name}: {msg}",
            num_goals=before_goals if before_goals is not None else 1,
            elapsed_ms=elapsed_ms, metadata=meta,
        )

    @staticmethod
    def _pp(state) -> str:
        pp = getattr(state, "pp", None)
        return str(pp) if pp is not None else str(state)

    @staticmethod
    def _goal_count(state, pp: Optional[str]) -> Optional[int]:
        n = getattr(state, "num_goals", None)
        if isinstance(n, int):
            return n
        if pp is None:
            return None
        s = pp.strip()
        if not s or s == "no goals":
            return 0
        # Each goal in LeanDojo's pp output carries a turnstile.
        return max(1, s.count("⊢"))

    def _fail(self, t0: float, msg: str, *, before=None, state: Optional[str] = None) -> TacticResult:
        meta: Dict[str, Any] = {}
        if before is not None and state is not None:
            bg = self._goal_count(before, state)
            if bg is not None:
                meta["num_goals_before"] = bg
        return TacticResult(
            next_state=None, proof_finished=False, error=msg,
            num_goals=meta.get("num_goals_before", 1),
            elapsed_ms=(time.perf_counter() - t0) * 1000, metadata=meta,
        )


# ---------------- Timeout wrapper ----------------


def run_with_timeout(runner, state, tactic, *, timeout):
    """Run `runner.run_tactic` on a worker thread and enforce a wall-clock
    timeout. The worker may keep running after timeout (we cannot kill a
    Python thread cleanly), but the collector loop continues."""

    result = []
    error = []

    def _target():
        try:
            result.append(runner.run_tactic(state, tactic, timeout=timeout))
        except BaseException as exc:
            error.append(exc)

    th = threading.Thread(target=_target, daemon=True)
    t0 = time.perf_counter()
    th.start()
    th.join(timeout=timeout)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    if th.is_alive():
        return TacticResult(
            next_state=None,
            proof_finished=False,
            error="timeout",
            num_goals=0,
            elapsed_ms=elapsed_ms,
        )
    if error:
        return TacticResult(
            next_state=None,
            proof_finished=False,
            error=f"exception: {error[0]!r}",
            num_goals=0,
            elapsed_ms=elapsed_ms,
        )
    return result[0]


# ---------------- Factory ----------------


def get_lean_runner(settings: Settings):
    """Construct the Lean runner named by ``settings.lean_backend``.

    Backends: ``mock`` | ``lean-cli`` | ``leandojo``. The ``lean_command``
    setting (from ``MINI_ELF_LEAN_COMMAND``) is threaded into the lean-cli
    runner so the rest of the pipeline never touches Lean config directly.
    """

    # Normalize a few common spellings so users don't get tripped up by
    # underscore vs hyphen (env vars vs CLI flags often diverge here).
    raw = settings.lean_backend.lower().strip()
    backend = raw.replace("_", "-")
    if backend == "mock":
        return MockLeanRunner()
    if backend == "lean-cli":
        return LeanCliRunner(command=settings.lean_command)
    if backend == "leandojo":
        return LeanDojoRunner()
    raise ValueError(
        f"Unknown Lean backend: {settings.lean_backend!r}. "
        "Expected one of: mock, lean-cli, leandojo."
    )


# Backwards-compatible alias.
build_lean_runner = get_lean_runner
