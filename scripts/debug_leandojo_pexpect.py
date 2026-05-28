"""Faithful pexpect reproduction: spawn the exact Dojo command, read the init
state, then send ONE tactic request and dump everything Lean emits until EOF.

Run in WSL venv:  .venv/bin/python scripts/debug_leandojo_pexpect.py
"""

from __future__ import annotations

from pathlib import Path

import pexpect

from lean_dojo import Dojo, LeanGitRepo, Theorem
from lean_dojo.data_extraction.trace import get_traced_repo_path

REPO_URL = "https://github.com/weijiawang2003/leandojo-ELF"
COMMIT = "15c35996a68b986e599ffd42375eef0b17fe292f"
FILE_PATH = "MiniDojo.lean"
FULL_NAME = "id_of_p"


def main() -> None:
    repo = LeanGitRepo(REPO_URL, COMMIT)
    theorem = Theorem(repo, FILE_PATH, FULL_NAME)
    traced_repo_path = get_traced_repo_path(repo, True)

    with Dojo(theorem) as (dojo, state):
        modified_path = Path(dojo.modified_file.name)
        modified_src = modified_path.read_text(encoding="utf-8")

    persistent = traced_repo_path / "MiniDojoPexpectRepl.lean"
    persistent.write_text(modified_src, encoding="utf-8")
    rel = persistent.relative_to(traced_repo_path)

    print("===== MODIFIED FILE (head) =====")
    for i, line in enumerate(modified_src.splitlines()[:20], 1):
        print(f"{i:3} | {line}")
    print("=" * 50)

    cmd = f"lake env lean --threads=1 {rel}"
    import os

    cwd = os.getcwd()
    os.chdir(traced_repo_path)
    try:
        proc = pexpect.spawn(cmd, timeout=120, maxread=1, encoding="utf-8", echo=False)
        # Read the init line (mirror Dojo._read_next_line, simplified).
        idx = proc.expect([r"REPL>.*?\n", pexpect.EOF, pexpect.TIMEOUT])
        print("init expect idx:", idx)
        print("init match:", repr(proc.after))
        print("init before:", repr(proc.before))

        req = '{"sid": 0, "cmd": "assumption"}'
        print("\n>>> sendline:", req)
        proc.sendline(req)

        # Now drain everything until EOF / timeout, printing raw.
        idx = proc.expect([pexpect.EOF, pexpect.TIMEOUT], timeout=30)
        print("post-send expect idx (0=EOF,1=TIMEOUT):", idx)
        print("post-send before (raw bytes Lean emitted):")
        print(repr(proc.before))
        proc.close(force=True)
        print("exitstatus:", proc.exitstatus, "signalstatus:", proc.signalstatus)
    finally:
        os.chdir(cwd)
        persistent.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
