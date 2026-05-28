"""Temporary direct-LeanDojo debug harness (not part of the test suite).

Reproduces the smoke-test path WITHOUT the project runner so we can see the raw
REPL traffic. Run inside the WSL venv:

    VERBOSE=1 .venv/bin/python scripts/debug_leandojo_direct.py

Delete after the API mismatch is diagnosed.
"""

from __future__ import annotations

import sys

from lean_dojo import Dojo, LeanGitRepo, Theorem
from lean_dojo.interaction.dojo import (
    LeanError,
    ProofFinished,
    ProofGivenUp,
    TacticState,
)

REPO_URL = "https://github.com/weijiawang2003/leandojo-ELF"
COMMIT = "15c35996a68b986e599ffd42375eef0b17fe292f"
FILE_PATH = "MiniDojo.lean"
FULL_NAME = "id_of_p"


def main() -> None:
    repo = LeanGitRepo(REPO_URL, COMMIT)
    theorem = Theorem(repo, FILE_PATH, FULL_NAME)
    print(f"repo={repo!r}")
    print(f"theorem={theorem!r}")

    with Dojo(theorem) as (dojo, state):
        # Tee the raw REPL output to stdout so we SEE what Lean prints before EOF.
        dojo.proc.logfile_read = sys.stdout
        print("=== INITIAL STATE ===")
        print("type:", type(state))
        print("repr:", repr(state))
        print("pp:\n", getattr(state, "pp", None))
        print("id:", getattr(state, "id", None))
        print("num_goals:", getattr(state, "num_goals", None))

        for tac in ("assumption", "exact h"):
            print(f"\n=== run_tac({type(state).__name__}, {tac!r}) ===")
            try:
                res = dojo.run_tac(state, tac)
                print("result type:", type(res).__name__)
                print("result repr:", repr(res))
                if isinstance(res, ProofFinished):
                    print(">>> PROOF FINISHED")
                elif isinstance(res, TacticState):
                    print(">>> NEXT STATE pp:\n", res.pp)
                elif isinstance(res, (LeanError, ProofGivenUp)):
                    print(">>> ERROR/GIVENUP:", res)
            except Exception as exc:  # noqa: BLE001 - debugging
                print(f"!!! {type(exc).__name__}: {exc}")
            # Each tac is run against the same immutable initial state, so a
            # crash on the first won't have mutated `state`.


if __name__ == "__main__":
    main()
