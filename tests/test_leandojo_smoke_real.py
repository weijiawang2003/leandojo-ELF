"""REAL LeanDojo smoke test — opt-in, auto-skipping.

This is the one test that talks to an actual LeanDojo + Lean toolchain. It is
skipped unless ALL of the following hold, so the default suite stays green on
machines without LeanDojo (e.g. native Windows, where LeanDojo cannot run):

  1. `lean_dojo` is importable, AND
  2. env `MINI_ELF_LEANDOJO_SMOKE=1` is set (explicit opt-in), AND
  3. the chosen seed has a real repo_url + commit (not the `<...>` placeholders).

Configure via env (all optional):
  MINI_ELF_LEANDOJO_SEEDS    path to seeds JSONL (default: data/seeds/leandojo_seeds.jsonl)
  MINI_ELF_LEANDOJO_THEOREM  theorem_name to use (default: id_of_p)

See docs/LEANDOJO_SETUP.md for how to fill in the seed and run this on a
supported OS. When it runs, it verifies a real success transition and a real
failure transition through the actual LeanDojoRunner.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from mini_elf_lean.config import Settings
from mini_elf_lean.io_utils import read_jsonl
from mini_elf_lean.lean_runner import get_lean_runner
from mini_elf_lean.schemas import TheoremSeed

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LEAN_DOJO = importlib.util.find_spec("lean_dojo") is not None
_OPT_IN = os.environ.get("MINI_ELF_LEANDOJO_SMOKE") == "1"


def _load_real_seed() -> TheoremSeed:
    seeds_path = Path(
        os.environ.get("MINI_ELF_LEANDOJO_SEEDS", _REPO_ROOT / "data/seeds/leandojo_seeds.jsonl")
    )
    want = os.environ.get("MINI_ELF_LEANDOJO_THEOREM", "id_of_p")
    rows = [r for r in read_jsonl(seeds_path) if r.get("theorem_name") == want]
    if not rows:
        pytest.skip(f"no seed named {want!r} in {seeds_path}")
    seed = TheoremSeed.model_validate(rows[0])
    if not seed.repo_url or "<" in (seed.repo_url or "") or "<" in (seed.commit or ""):
        pytest.skip(
            "leandojo seed still has placeholder repo_url/commit; "
            "fill them in (see docs/LEANDOJO_SETUP.md) to run the real smoke test."
        )
    return seed


pytestmark = [
    pytest.mark.skipif(not _LEAN_DOJO, reason="lean_dojo is not installed"),
    pytest.mark.skipif(
        not _OPT_IN, reason="set MINI_ELF_LEANDOJO_SMOKE=1 to run the real LeanDojo smoke test"
    ),
]


def test_real_leandojo_success_and_failure_transitions() -> None:
    seed = _load_real_seed()
    runner = get_lean_runner(Settings(lean_backend="leandojo"))
    assert runner.name == "leandojo"
    try:
        state0 = runner.start(seed)
        assert isinstance(state0, str) and state0.strip(), "expected a real initial state"
        assert "⊢" in state0, f"initial state should contain a goal turnstile: {state0!r}"

        # --- success transition: `exact h` closes `(p : Prop) (h : p) : p` ---
        ok = runner.run_tactic(state0, "exact h", timeout=120.0)
        assert ok.success is True, f"expected success, got error={ok.error!r}"
        assert ok.proof_finished is True
        assert ok.num_goals == 0
        assert ok.next_state == "no goals"
        assert ok.metadata.get("result_type")  # e.g. "ProofFinished"

        # --- failure transition: a bogus tactic must fail cleanly ---
        bad = runner.run_tactic(state0, "this_is_not_a_tactic", timeout=120.0)
        assert bad.success is False
        assert bad.next_state is None
        assert bad.error
    finally:
        runner.close()
