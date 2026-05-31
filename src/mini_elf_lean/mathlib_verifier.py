"""Mini-ELF v26 — batched Mathlib whole-file verifier.

The v25 path verified one candidate per ``lake env lean`` subprocess. With
``import Mathlib`` that pays the ~4.7 s (warm) / ~30 s (cold) olean-load cost
**per candidate**, which does not finish overnight for a few-hundred-row corpus
plus a four-model evaluation.

This module verifies **many candidates in a single Lean invocation** by writing
one file that begins with ``import Mathlib`` and contains one anonymous
``example`` per candidate. Lean elaborates each top-level command independently
and reports errors with ``<file>:<line>:<col>: error ...`` headers, **continuing
past failures**. We attribute each error to the candidate whose line range
contains it; a candidate is *verified* iff no error (and no ``sorry`` warning)
falls in its range.

It combines both project Lean lessons (see memories):

* **direct toolchain binary**, never the elan ``lean`` shim (hang risk);
* **precomputed ``LEAN_PATH``** (one ``lake env printenv`` call), never
  ``lake env lean`` per candidate (lakefile-discovery overhead / hangs).

Honesty: this is a real ``import Mathlib`` whole-file typecheck (no mock). It is
used to verify corpus targets and to score model beams — never to inject a
proof. ``state_after`` is never read or produced.
"""

from __future__ import annotations

import bisect
import logging
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# The pinned v4.30.0 toolchain binary (matches the scratch project's
# lean-toolchain). This is the real ELF, not the ~/.elan/bin/lean shim.
DEFAULT_LEAN_BIN = (
    "/home/wangw/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
)
MATHLIB_IMPORT = "import Mathlib"

# Matches a Lean diagnostic header line:  <path>:<line>:<col>: error ...
_DIAG_RE = re.compile(r"^(?P<path>.+?):(?P<line>\d+):(?P<col>\d+): (?P<kind>error|warning)\b(?P<rest>.*)$")


@dataclass
class CandidateVerdict:
    """Per-candidate verification result from a batch."""

    index: int
    theorem_name: str
    statement: str
    tactic: str
    success: bool
    error: Optional[str]  # first diagnostic line, or None on success


def _resolve_lean_path(scratch: Path, lean_path: Optional[str]) -> str:
    """Return the Mathlib ``LEAN_PATH``. If not supplied, obtain it once via
    ``lake env printenv LEAN_PATH`` in the scratch project (the only ``lake``
    call we make — everything else uses the direct binary)."""
    if lean_path:
        return lean_path
    env_override = os.environ.get("MINI_ELF_MATHLIB_LEAN_PATH")
    if env_override:
        return env_override
    proc = subprocess.run(
        ["lake", "env", "printenv", "LEAN_PATH"],
        capture_output=True, text=True, cwd=str(scratch), timeout=180,
    )
    out = (proc.stdout or "").strip()
    if not out:
        raise RuntimeError(
            "could not obtain Mathlib LEAN_PATH from `lake env printenv "
            f"LEAN_PATH` in {scratch} (stderr: {(proc.stderr or '')[:200]})"
        )
    return out


class BatchMathlibVerifier:
    """Verify candidate tactics against ``import Mathlib`` in batches.

    Parameters
    ----------
    scratch : Path
        The external Mathlib scratch lake project.
    lean_bin : str
        Direct toolchain ``lean`` binary (defaults to the pinned v4.30.0 ELF).
    lean_path : str | None
        Mathlib ``LEAN_PATH``; computed once from the scratch project if None.
    timeout : float
        Wall-clock timeout for one batch invocation (seconds).
    batch_size : int
        Max candidates per Lean file (chunked beyond this).
    imports : sequence of str
        Import lines prepended to every batch file.
    """

    def __init__(
        self,
        scratch: Path,
        *,
        lean_bin: str = DEFAULT_LEAN_BIN,
        lean_path: Optional[str] = None,
        timeout: float = 300.0,
        batch_size: int = 80,
        imports: Optional[Sequence[str]] = None,
        core: bool = False,
    ) -> None:
        """``core=True`` verifies plain core-Lean theorems: no ``import
        Mathlib`` and no ``LEAN_PATH`` (the direct binary alone), used for the
        broad-core tier of the routed system."""
        self.scratch = Path(scratch)
        self.lean_bin = lean_bin
        self.timeout = timeout
        self.batch_size = batch_size
        self.core = core
        if imports is None:
            imports = () if core else (MATHLIB_IMPORT,)
        self.imports = [i for i in imports if i.strip()]
        self.lean_path = "" if core else _resolve_lean_path(self.scratch, lean_path)
        self.n_invocations = 0
        self.total_lean_seconds = 0.0

    # -- file rendering / parsing --------------------------------------- #

    #: A guaranteed-parse-clean, guaranteed-elaborate-clean resync declaration
    #: placed after every candidate. If a candidate's tactic is a parse error
    #: that runs past its own lines, Lean reports "unexpected token 'example'"
    #: at the *next* command keyword — which is now this sentinel, NOT the next
    #: real candidate. Because the sentinel's line is not a candidate start, the
    #: leaked diagnostic is attributed to the preceding (culprit) candidate by
    #: greatest-start-<=-line, so a parse error can never exonerate its author
    #: or falsely blame the next candidate.
    _SENTINEL = "example : True := True.intro"

    def _render(self, items: Sequence[Tuple[str, str, str]]
                ) -> Tuple[str, List[Tuple[int, int, int]]]:
        """Build the batch source and a list of (index, start_line, end_line)
        (1-indexed, inclusive) for each candidate ``example`` block. Candidate
        starts are strictly increasing; sentinel lines sit between them."""
        lines: List[str] = list(self.imports)
        lines.append("")  # blank separator after imports
        ranges: List[Tuple[int, int, int]] = []
        for idx, (_name, stmt, tactic) in enumerate(items):
            start = len(lines) + 1  # 1-indexed line of the `example` header
            lines.append(f"example {stmt} := by")
            body = tactic.splitlines() or [tactic]
            for bl in body:
                lines.append("  " + bl)
            end = len(lines)  # last line of this candidate's block
            ranges.append((idx, start, end))
            lines.append(self._SENTINEL)  # resync point (absorbs forward leaks)
            lines.append("")
        return "\n".join(lines) + "\n", ranges

    def _parse_diagnostics(self, tmp_path: str, stdout: str, stderr: str
                           ) -> List[Tuple[int, str]]:
        """Return a list of (line_number, message) for error / `sorry`-warning
        diagnostics belonging to this file, sorted by line."""
        diags: List[Tuple[int, str]] = []
        base = os.path.basename(tmp_path)
        for blob in (stderr, stdout):
            if not blob:
                continue
            for raw in blob.splitlines():
                m = _DIAG_RE.match(raw)
                if not m:
                    continue
                if base not in m.group("path") and tmp_path not in m.group("path"):
                    continue
                kind = m.group("kind")
                rest = m.group("rest").strip()
                ln = int(m.group("line"))
                if kind == "error":
                    diags.append((ln, ("error: " + rest).strip()[:200]))
                elif kind == "warning" and "sorry" in rest.lower():
                    diags.append((ln, ("warning: " + rest).strip()[:200]))
        diags.sort(key=lambda x: x[0])
        return diags

    @staticmethod
    def _attribute(starts: List[int], diags: List[Tuple[int, str]]
                   ) -> Dict[int, List[str]]:
        """Attribute each (line, msg) diagnostic to the candidate with the
        greatest ``start_line <= line``. Robust to a parse error that desyncs
        Lean's command boundary and reports past a candidate's own range: the
        leaked diagnostic still lands on the offending (preceding) candidate,
        never exonerating it. ``starts`` must be strictly increasing."""
        attributed: Dict[int, List[str]] = {i: [] for i in range(len(starts))}
        if not starts:
            return attributed
        first = starts[0]
        for ln, msg in diags:
            if ln < first:
                continue  # diagnostic before the first candidate (import preamble)
            pos = bisect.bisect_right(starts, ln) - 1
            if pos >= 0:
                attributed[pos].append(msg)
        return attributed

    @staticmethod
    def _pick_error(in_range: List[str]) -> Optional[str]:
        """From all diagnostics in a candidate's line range, surface the most
        informative one: a root-cause error (unknown id/tactic, type mismatch,
        parse error) is preferred over a downstream 'unsolved goals' symptom."""
        if not in_range:
            return None
        for msg in in_range:
            low = msg.lower()
            if "unsolved goals" in low or "no goals" in low:
                continue
            return msg
        return in_range[0]

    def _verify_chunk(self, items: Sequence[Tuple[str, str, str]]
                      ) -> List[CandidateVerdict]:
        source, ranges = self._render(items)
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".lean", prefix="v26_mathlib_batch_",
            delete=False, encoding="utf-8",
        )
        try:
            fh.write(source)
            fh.close()
            env = dict(os.environ)
            if self.lean_path:
                env["LEAN_PATH"] = self.lean_path
            else:
                env.pop("LEAN_PATH", None)
            t0 = time.perf_counter()
            try:
                proc = subprocess.run(
                    [self.lean_bin, fh.name],
                    capture_output=True, text=True, timeout=self.timeout, env=env,
                )
                timed_out = False
            except subprocess.TimeoutExpired as exc:
                proc = None
                timed_out = True
                stdout = exc.stdout or ""
                stderr = exc.stderr or ""
            elapsed = time.perf_counter() - t0
            self.n_invocations += 1
            self.total_lean_seconds += elapsed

            if timed_out:
                return [CandidateVerdict(idx, items[i][0], items[i][1], items[i][2],
                                         False, "timeout")
                        for i, (idx, _s, _e) in enumerate(ranges)]
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            diags = self._parse_diagnostics(fh.name, stdout, stderr)

            starts = [start for (_idx, start, _end) in ranges]  # strictly increasing
            attributed = self._attribute(starts, diags)

            out: List[CandidateVerdict] = []
            for i, (idx, _start, _end) in enumerate(ranges):
                name, stmt, tactic = items[i]
                err = self._pick_error(attributed[i])
                out.append(CandidateVerdict(idx, name, stmt, tactic,
                                            err is None, err))
            return out
        finally:
            if os.environ.get("MINI_ELF_LEAN_KEEP_TEMP", "") in ("", "0", "false", "False"):
                try:
                    os.unlink(fh.name)
                except OSError:
                    pass

    # -- public API ----------------------------------------------------- #

    def _batch_verdicts(self, items: Sequence[Tuple[str, str, str]]
                        ) -> List[CandidateVerdict]:
        """One chunked verification pass; verdicts aligned to ``items``."""
        verdicts: List[CandidateVerdict] = []
        base = 0
        for start in range(0, len(items), self.batch_size):
            chunk = list(items[start:start + self.batch_size])
            for v in self._verify_chunk(chunk):
                verdicts.append(CandidateVerdict(base + v.index, v.theorem_name,
                                                 v.statement, v.tactic, v.success, v.error))
            base += len(chunk)
        return verdicts

    def verify_many(self, items: Sequence[Tuple[str, str, str]], *,
                    confirm: bool = True, max_rounds: int = 8
                    ) -> List[CandidateVerdict]:
        """Verify a list of (theorem_name, statement, tactic), chunked at
        ``batch_size``, returning verdicts in input order.

        Lean's parser recovery can *skip* a malformed declaration that follows
        a candidate whose tactic is a top-level parse error — the skipped
        declaration then has no diagnostic and would be falsely reported as
        verified. ``confirm=True`` (default) eliminates this: it re-batches only
        the current successes and demotes any that now show an error, iterating
        until a round produces no new failures. The earliest desyncing candidate
        in any file always has its own error reported (nothing precedes it to
        skip it), so each non-converged round removes >=1 candidate and its
        victim is re-checked un-skipped next round. This is sound (no false
        positives survive) and complete (genuine passes never error)."""
        if not items:
            return []
        verdicts = self._batch_verdicts(items)
        if not confirm:
            return verdicts
        for _ in range(max_rounds):
            succ_idx = [i for i, v in enumerate(verdicts) if v.success]
            if not succ_idx:
                break
            recheck = self._batch_verdicts([items[i] for i in succ_idx])
            changed = 0
            for j, rv in enumerate(recheck):
                if not rv.success:
                    gi = succ_idx[j]
                    verdicts[gi] = CandidateVerdict(gi, rv.theorem_name, rv.statement,
                                                    rv.tactic, False, rv.error or "skipped->confirmed fail")
                    changed += 1
            if changed == 0:
                break
        else:
            logger.warning("verify_many: confirm did not converge in %d rounds", max_rounds)
        return verdicts

    def verify_one(self, theorem_name: str, statement: str, tactic: str
                   ) -> Dict[str, object]:
        """Single-candidate convenience wrapper (used for warmup / dict API)."""
        v = self.verify_many([(theorem_name, statement, tactic)])[0]
        return {"success": v.success, "error": v.error}

    def warmup(self) -> bool:
        """Trigger the cold olean load once so later batches are warm."""
        v = self.verify_one("__v26_warmup__", "(n : Nat) : n + 0 = n", "rfl")
        return bool(v["success"])


__all__ = [
    "BatchMathlibVerifier", "CandidateVerdict",
    "DEFAULT_LEAN_BIN", "MATHLIB_IMPORT",
]
