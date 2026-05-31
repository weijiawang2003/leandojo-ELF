"""Mini-ELF v25 — Part 1: Mathlib environment probe.

A quick, re-runnable diagnostic that records, for each path, the exact
command, return code, stdout/stderr tail, and wall time. It does **not**
fake anything: ``mathlib_available`` is true iff an ``import Mathlib``
file actually typechecks in the scratch project.

Paths (brief Part 1):
  A. **Repo Mathlib** — try ``lake env lean`` + ``import Mathlib`` inside
     ``examples/leandojo_mini_repo`` (a minimal lib with no Mathlib dep,
     so this is expected to fail; we record the failure honestly).
  B. **Scratch project** outside the repo (``../mini_elf_mathlib_probe``):
     ``--init-scratch`` writes ``lean-toolchain`` (pinned ``v4.30.0``) +
     ``lakefile.toml`` (mathlib pinned to the matching ``v4.30.0`` tag) +
     a root module. The heavy ``lake update`` / ``lake exe cache get`` are
     run *outside* this script (they take minutes) — see
     ``V25_MATHLIB_ENV_REPORT.md``; this script then verifies the result
     by compiling ``import Mathlib``.
  C. **Failure** — every command's stderr is captured verbatim so a
     failed install is reported, never mocked. Caller falls back to the
     Part 2B core-Lean surrogate.

Honesty: pinned toolchain binary for the non-lake probes (the elan
``lean`` shim hangs under sustained load — see ``V22_REPO_STATUS.md``);
no Mathlib is fabricated; nothing here writes into the main repo's lake
setup.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
PINNED_LEAN = Path.home() / ".elan/toolchains/leanprover--lean4---v4.30.0/bin/lean"
MATHLIB_URL = "https://github.com/leanprover-community/mathlib4"
MATHLIB_REV = "v4.30.0"  # tag pinned to leanprover/lean4:v4.30.0 (our toolchain)
TOOLCHAIN = "leanprover/lean4:v4.30.0"


def _run(cmd: List[str], *, cwd: Optional[Path] = None, timeout: float = 120.0,
         tail: int = 1200) -> Dict[str, Any]:
    t0 = time.perf_counter()
    rec: Dict[str, Any] = {"cmd": " ".join(cmd), "cwd": str(cwd) if cwd else None}
    try:
        proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                              capture_output=True, text=True, timeout=timeout)
        rec["returncode"] = proc.returncode
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        rec["stdout_tail"] = out[-tail:]
        rec["stderr_tail"] = err[-tail:]
        rec["ok"] = proc.returncode == 0
    except subprocess.TimeoutExpired:
        rec["returncode"] = None
        rec["stdout_tail"] = ""
        rec["stderr_tail"] = f"TIMEOUT after {timeout}s"
        rec["ok"] = False
    except FileNotFoundError as exc:
        rec["returncode"] = None
        rec["stdout_tail"] = ""
        rec["stderr_tail"] = f"command not found: {exc.filename or cmd[0]}"
        rec["ok"] = False
    rec["elapsed_s"] = round(time.perf_counter() - t0, 2)
    return rec


def _compile_snippet(lean_cmd: List[str], snippet: str, *, cwd: Optional[Path],
                     timeout: float, label: str) -> Dict[str, Any]:
    """Write ``snippet`` to a temp .lean in ``cwd`` and compile it."""
    work = cwd if cwd is not None else ROOT
    tmp = work / f"_v25_probe_{label}.lean"
    tmp.write_text(snippet, encoding="utf-8")
    try:
        rec = _run(lean_cmd + [tmp.name if cwd else str(tmp)], cwd=cwd, timeout=timeout)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    rec["snippet"] = snippet
    return rec


def init_scratch(scratch: Path) -> Dict[str, Any]:
    """Write the scratch project's lake files (no network, fast)."""
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch / "lean-toolchain").write_text(TOOLCHAIN + "\n", encoding="utf-8")
    lakefile = (
        'name = "mini_elf_mathlib_probe"\n'
        'defaultTargets = ["MiniElfMathlibProbe"]\n\n'
        "[[require]]\n"
        'name = "mathlib"\n'
        f'git = "{MATHLIB_URL}"\n'
        f'rev = "{MATHLIB_REV}"\n\n'
        "[[lean_lib]]\n"
        'name = "MiniElfMathlibProbe"\n'
    )
    (scratch / "lakefile.toml").write_text(lakefile, encoding="utf-8")
    (scratch / "MiniElfMathlibProbe.lean").write_text(
        "-- scratch root module for the v25 Mathlib probe\n", encoding="utf-8")
    return {"scratch_dir": str(scratch), "toolchain": TOOLCHAIN,
            "mathlib_rev": MATHLIB_REV, "files_written":
            ["lean-toolchain", "lakefile.toml", "MiniElfMathlibProbe.lean"]}


def probe(scratch: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {"paths": {}}

    # --- toolchain versions ---
    out["paths"]["lean_version"] = _run([str(PINNED_LEAN), "--version"], timeout=30)
    out["paths"]["lake_version"] = _run(["lake", "--version"], timeout=30)

    # --- Path A: repo Mathlib (leandojo_mini_repo, no mathlib dep) ---
    repo_proj = ROOT / "examples" / "leandojo_mini_repo"
    a: Dict[str, Any] = {"project": str(repo_proj)}
    if repo_proj.exists():
        a["lake_env_version"] = _run(["lake", "env", "lean", "--version"],
                                     cwd=repo_proj, timeout=90)
        a["import_mathlib"] = _compile_snippet(
            ["lake", "env", "lean"], "import Mathlib\n#check Nat\n",
            cwd=repo_proj, timeout=90, label="repo_mathlib")
        a["mathlib_importable"] = bool(a["import_mathlib"].get("ok"))
    else:
        a["error"] = "leandojo_mini_repo missing"
        a["mathlib_importable"] = False
    out["paths"]["A_repo"] = a

    # --- Path B: scratch project ---
    b: Dict[str, Any] = {"scratch_dir": str(scratch), "exists": scratch.exists()}
    pkg = scratch / ".lake" / "packages" / "mathlib"
    b["mathlib_package_cloned"] = pkg.exists()
    manifest = scratch / "lake-manifest.json"
    b["manifest_present"] = manifest.exists()
    if scratch.exists() and (scratch / "lakefile.toml").exists():
        b["lake_env_version"] = _run(["lake", "env", "lean", "--version"],
                                     cwd=scratch, timeout=120)
        # full Mathlib import + a couple of trivial Mathlib-tier checks
        b["import_mathlib"] = _compile_snippet(
            ["lake", "env", "lean"],
            "import Mathlib\nexample (n : Nat) : n + 0 = n := by simp\n",
            cwd=scratch, timeout=300, label="scratch_mathlib")
        b["mathlib_importable"] = bool(b["import_mathlib"].get("ok"))
        # lighter probe: a single Mathlib leaf module (cheaper than full import)
        b["import_mathlib_logic"] = _compile_snippet(
            ["lake", "env", "lean"],
            "import Mathlib.Logic.Basic\nexample (p : Prop) (h : p) : p := h\n",
            cwd=scratch, timeout=180, label="scratch_logic")
    else:
        b["mathlib_importable"] = False
    out["paths"]["B_scratch"] = b

    out["mathlib_available"] = bool(
        out["paths"]["A_repo"].get("mathlib_importable")
        or out["paths"]["B_scratch"].get("mathlib_importable"))
    out["pinned_lean"] = str(PINNED_LEAN)
    out["mathlib_url"] = MATHLIB_URL
    out["mathlib_rev"] = MATHLIB_REV
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scratch-dir", default=str(ROOT.parent / "mini_elf_mathlib_probe"))
    ap.add_argument("--init-scratch", action="store_true",
                    help="write the scratch project lake files, then probe")
    ap.add_argument("--out", default=str(ROOT / "data" / "baselines"
                                         / "v25_mathlib_env_probe.json"))
    args = ap.parse_args(argv)

    scratch = Path(args.scratch_dir).resolve()
    result: Dict[str, Any] = {}
    if args.init_scratch:
        result["init_scratch"] = init_scratch(scratch)
    result.update(probe(scratch))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"mathlib_available={result.get('mathlib_available')}  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
