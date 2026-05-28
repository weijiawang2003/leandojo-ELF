"""Reproduce the LeanDojo REPL OUTSIDE pexpect to capture the real Lean error.

We open a Dojo to let it build the modified `.lean` REPL file, copy that file's
contents into a persistent file in the traced-repo working dir, then run
`lake env lean` on it ourselves, piping the JSON request via stdin and capturing
stdout AND stderr separately. pexpect merges/hides stderr; this does not.

Run in WSL venv:  .venv/bin/python scripts/debug_leandojo_manual_repl.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

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
    print("traced_repo_path:", traced_repo_path)

    # Let Dojo build the modified REPL file, then snapshot its contents.
    with Dojo(theorem) as (dojo, state):
        modified_path = Path(dojo.modified_file.name)
        modified_src = modified_path.read_text(encoding="utf-8")
        print("modified file:", modified_path)

    persistent = traced_repo_path / "MiniDojoDebugRepl.lean"
    persistent.write_text(modified_src, encoding="utf-8")
    rel = persistent.relative_to(traced_repo_path)
    print("wrote persistent copy:", persistent)

    cmd = ["lake", "env", "lean", "--threads=1", str(rel)]
    stdin_payload = '{"sid": 0, "cmd": "assumption"}\nexit\n'
    print("cmd:", " ".join(cmd))
    print("stdin:", repr(stdin_payload))
    print("=" * 60)
    proc = subprocess.run(
        cmd,
        cwd=str(traced_repo_path),
        input=stdin_payload,
        capture_output=True,
        text=True,
        timeout=300,
    )
    print("returncode:", proc.returncode)
    print("----- STDOUT -----")
    print(proc.stdout)
    print("----- STDERR -----")
    print(proc.stderr)

    persistent.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
