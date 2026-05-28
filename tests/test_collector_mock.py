"""End-to-end collector tests using only mock backends (no Lean, no API)."""

from __future__ import annotations

from pathlib import Path

from mini_elf_lean.collector import CollectionConfig, collect
from mini_elf_lean.config import Settings
from mini_elf_lean.io_utils import read_jsonl, write_jsonl
from mini_elf_lean.schemas import TheoremSeed


def _toy_seed() -> TheoremSeed:
    return TheoremSeed(
        theorem_name="trivial_true",
        theorem_statement="True",
        initial_state="⊢ True",
    )


def test_mock_end_to_end_writes_only_success(tmp_path: Path) -> None:
    seeds = tmp_path / "seeds.jsonl"
    out = tmp_path / "ok.jsonl"
    failed = tmp_path / "bad.jsonl"
    write_jsonl(seeds, [_toy_seed()])

    cfg = CollectionConfig(
        seeds_path=seeds,
        success_out=out,
        failed_out=failed,
        num_candidates=6,
        temperature=0.0,
        settings=Settings(llm_backend="mock", lean_backend="mock"),
    )
    summary = collect(cfg)

    assert summary.seeds_processed == 1
    assert summary.tactics_succeeded > 0
    # forbidden 'sorry' from the mock must be dropped before Lean.
    assert summary.forbidden_dropped >= 1

    ok_rows = list(read_jsonl(out))
    assert ok_rows, "expected some verified records"
    assert all(r["success"] for r in ok_rows)
    assert all(r["backend"] == "mock" for r in ok_rows)
    assert all(r["model"] == "mock" for r in ok_rows)
    # No forbidden tactic ever reaches the verified file.
    assert all("sorry" not in r["tactic"] for r in ok_rows)


def test_mock_failed_out_receives_failures(tmp_path: Path) -> None:
    # A seed whose only viable mock tactics include some failures: the mock
    # runner fails on tactics it does not special-case (e.g. 'apply h').
    seeds = tmp_path / "seeds.jsonl"
    out = tmp_path / "ok.jsonl"
    failed = tmp_path / "bad.jsonl"
    write_jsonl(seeds, [_toy_seed()])

    cfg = CollectionConfig(
        seeds_path=seeds,
        success_out=out,
        failed_out=failed,
        num_candidates=12,  # request the whole bank so failures appear
        temperature=0.0,
        settings=Settings(llm_backend="mock", lean_backend="mock"),
    )
    collect(cfg)

    failed_rows = list(read_jsonl(failed))
    assert failed_rows, "expected at least one failed attempt"
    assert all(not r["success"] for r in failed_rows)
    assert all(r["error"] for r in failed_rows)


def test_manual_file_plus_mock_end_to_end(tmp_path: Path) -> None:
    seeds = tmp_path / "seeds.jsonl"
    cand = tmp_path / "cand.jsonl"
    out = tmp_path / "ok.jsonl"
    failed = tmp_path / "bad.jsonl"

    write_jsonl(seeds, [_toy_seed()])
    write_jsonl(
        cand,
        [
            {
                "theorem_name": "trivial_true",
                "state_before": "⊢ True",
                "candidates": ["trivial", "rfl", "exact h"],
                "source": "claude_code_agent",
                "prompt_style": "diverse",
            }
        ],
    )

    cfg = CollectionConfig(
        seeds_path=seeds,
        success_out=out,
        failed_out=failed,
        num_candidates=5,
        temperature=0.0,
        manual_candidates_path=cand,
        settings=Settings(llm_backend="manual-file", lean_backend="mock"),
    )
    summary = collect(cfg)

    assert summary.tactics_attempted == 3  # trivial, rfl, exact h
    ok_rows = list(read_jsonl(out))
    # 'trivial' and 'rfl' succeed in the mock; 'exact h' fails.
    assert any(r["tactic"] == "trivial" for r in ok_rows)
    assert all(r["source"] == "claude_code_agent" for r in ok_rows)
    assert all(r["model"] == "manual-file" for r in ok_rows)
    assert all(r["prompt_style"] == "diverse" for r in ok_rows)

    failed_rows = list(read_jsonl(failed))
    assert any(r["tactic"] == "exact h" for r in failed_rows)


def test_max_seeds_limits_processing(tmp_path: Path) -> None:
    seeds = tmp_path / "seeds.jsonl"
    out = tmp_path / "ok.jsonl"
    write_jsonl(
        seeds,
        [
            TheoremSeed(theorem_name=f"t{i}", theorem_statement="True", initial_state="⊢ True")
            for i in range(5)
        ],
    )
    cfg = CollectionConfig(
        seeds_path=seeds,
        success_out=out,
        failed_out=None,
        num_candidates=3,
        temperature=0.0,
        max_seeds=2,
        settings=Settings(llm_backend="mock", lean_backend="mock"),
    )
    summary = collect(cfg)
    assert summary.seeds_processed == 2
