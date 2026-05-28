"""Top-level trace collection loop.

Flow per seed:
  1. Open a session with the Lean runner.
  2. Ask the candidate source (LLM / manual file / ...) for K candidates.
  3. Sanitize / dedupe / forbidden-filter.
  4. Run each candidate through the Lean runner, write a TraceRecord either way.
  5. (multi-step) Optionally continue from successful next states.

Core principle: the candidate source only *proposes*. A record is a positive
training transition only if Lean accepts it (``success=True``). Successful and
failed records are written to separate files so failures never leak into
supervised labels.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .config import Settings, load_settings
from .io_utils import JsonCache, append_jsonl, read_jsonl
from .lean_runner import LeanRunner, get_lean_runner, run_with_timeout
from .llm_client import LLMClient, get_llm_client
from .prompt_templates import DEFAULT_PROMPT_STYLE, PROMPT_STYLES
from .schemas import CollectionSummary, TheoremSeed, TraceRecord
from .tactic_sanitizer import sanitize_candidate_list

logger = logging.getLogger(__name__)


@dataclass
class CollectionConfig:
    seeds_path: Path
    success_out: Path
    failed_out: Optional[Path]
    num_candidates: int = 4
    temperature: float = 0.7
    max_depth: int = 1
    max_seeds: Optional[int] = None
    prompt_style: str = DEFAULT_PROMPT_STYLE
    manual_candidates_path: Optional[Path] = None
    dry_run: bool = False
    settings: Optional[Settings] = None


def _state_hash(state: str) -> str:
    return hashlib.sha1(state.encode("utf-8")).hexdigest()[:16]


def _num_goals(state: str) -> int:
    """Cheap heuristic used only for the *before* count when the runner does
    not provide one (e.g. lean-cli, which verifies whole files)."""

    if not state or state.strip() == "no goals":
        return 0
    return max(1, len([b for b in state.split("\n\n") if b.strip()]))


def _load_seeds(path: Path, max_seeds: Optional[int]) -> list:
    seeds = [TheoremSeed.model_validate(row) for row in read_jsonl(path)]
    if not seeds:
        raise SystemExit(f"No seeds loaded from {path}")
    if max_seeds is not None:
        seeds = seeds[:max_seeds]
    return seeds


def collect(cfg: CollectionConfig) -> CollectionSummary:
    settings = cfg.settings or load_settings()
    seeds = _load_seeds(cfg.seeds_path, cfg.max_seeds)
    logger.info("Loaded %d seeds from %s", len(seeds), cfg.seeds_path)

    cache = JsonCache(Path(settings.cache_dir) / "llm")
    manual_path = str(cfg.manual_candidates_path) if cfg.manual_candidates_path else None
    llm = get_llm_client(settings, cache=cache, manual_candidates_path=manual_path)
    runner = get_lean_runner(settings)

    counts = {
        "tactics_attempted": 0,
        "tactics_succeeded": 0,
        "proofs_finished": 0,
        "duplicates_dropped": 0,
        "forbidden_dropped": 0,
        "timeouts": 0,
    }
    t0 = time.perf_counter()

    try:
        for seed in seeds:
            _process_seed(seed, llm, runner, cfg, counts, settings)
    finally:
        runner.close()

    elapsed = time.perf_counter() - t0
    summary = CollectionSummary(
        seeds_processed=len(seeds),
        tactics_attempted=counts["tactics_attempted"],
        tactics_succeeded=counts["tactics_succeeded"],
        proofs_finished=counts["proofs_finished"],
        duplicates_dropped=counts["duplicates_dropped"],
        forbidden_dropped=counts["forbidden_dropped"],
        timeouts=counts["timeouts"],
        elapsed_seconds=elapsed,
        llm_backend=settings.llm_backend,
        lean_backend=settings.lean_backend,
    )
    logger.info(
        "Done. attempted=%d ok=%d finished=%d (%.1fs)",
        summary.tactics_attempted,
        summary.tactics_succeeded,
        summary.proofs_finished,
        summary.elapsed_seconds,
    )
    return summary


def _process_seed(
    seed: TheoremSeed,
    llm: LLMClient,
    runner: LeanRunner,
    cfg: CollectionConfig,
    counts: dict,
    settings: Settings,
) -> None:
    initial_state = runner.start(seed)
    frontier = [(initial_state, 0)]
    visited = set()

    while frontier:
        state, depth = frontier.pop()
        if _state_hash(state) in visited:
            continue
        visited.add(_state_hash(state))
        if depth >= cfg.max_depth:
            continue

        batch = llm.propose_tactics(
            seed=seed,
            state_before=state,
            num_candidates=cfg.num_candidates,
            prompt_style=cfg.prompt_style,
            temperature=cfg.temperature,
        )
        tactics, stats = sanitize_candidate_list(batch.candidates)
        counts["duplicates_dropped"] += stats.duplicates_dropped
        counts["forbidden_dropped"] += stats.forbidden_dropped
        if not tactics:
            logger.info("No candidates for %s at depth %d", seed.theorem_name, depth)

        for tactic in tactics:
            counts["tactics_attempted"] += 1
            if cfg.dry_run:
                logger.info("[dry-run] would run: %s :: %s", seed.theorem_name, tactic)
                continue

            result = run_with_timeout(
                runner, state, tactic, timeout=settings.tactic_timeout_s
            )
            is_timeout = result.error == "timeout"
            if is_timeout:
                counts["timeouts"] += 1

            # Backends may attach extras. A `num_goals_before` key (e.g. from
            # LeanDojo's real TacticState) is authoritative; otherwise fall back
            # to the cheap string heuristic. The rest is recorded as metadata.
            extra_meta = dict(getattr(result, "metadata", {}) or {})
            ng_before = extra_meta.pop("num_goals_before", None)
            num_goals_before = ng_before if ng_before is not None else _num_goals(state)
            state_changed = bool(result.next_state) and result.next_state != state

            record = TraceRecord(
                theorem_name=seed.theorem_name,
                theorem_statement=seed.theorem_statement,
                state_before=state,
                tactic=tactic,
                state_after=result.next_state,
                success=result.success,
                proof_finished=result.proof_finished,
                num_goals_before=num_goals_before,
                num_goals_after=result.num_goals,
                state_changed=state_changed,
                error=result.error,
                timeout=is_timeout,
                source=batch.source,
                model=batch.model,
                backend=getattr(runner, "name", settings.lean_backend),
                prompt_style=batch.prompt_style,
                temperature=cfg.temperature,
                raw_llm_output=batch.raw_output,
                step_index=depth,
                parent_state_hash=_state_hash(state),
                metadata=extra_meta,
            )

            if result.success:
                counts["tactics_succeeded"] += 1
                append_jsonl(cfg.success_out, [record])
                if result.proof_finished:
                    counts["proofs_finished"] += 1
                elif result.next_state and depth + 1 < cfg.max_depth:
                    frontier.append((result.next_state, depth + 1))
            elif cfg.failed_out is not None:
                append_jsonl(cfg.failed_out, [record])


# ---------------- CLI ----------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Collect proposed, Lean-verified tactic traces.")
    p.add_argument("--seeds", required=True, type=Path, help="Path to seeds JSONL file.")
    p.add_argument("--out", required=True, type=Path, help="Output JSONL for verified transitions.")
    p.add_argument("--failed-out", type=Path, default=None, help="Optional JSONL for failed attempts.")
    p.add_argument(
        "-k", "--k-candidates", "--num-candidates", dest="num_candidates",
        type=int, default=4, help="Candidates requested per proof state.",
    )
    p.add_argument("-t", "--temperature", type=float, default=0.7)
    p.add_argument(
        "-d", "--max-depth", type=int, default=1,
        help="Max multi-step depth. 1 = collect single transitions only.",
    )
    p.add_argument("--max-seeds", type=int, default=None, help="Process at most N seeds.")
    p.add_argument(
        "--prompt-style", choices=list(PROMPT_STYLES), default=DEFAULT_PROMPT_STYLE,
        help="Candidate prompting style (real LLM backends).",
    )
    p.add_argument(
        "--manual-candidates", type=Path, default=None,
        help="Path to a manual/agent candidate JSONL (required for --llm-backend manual-file).",
    )
    p.add_argument("--dry-run", action="store_true", help="Propose+sanitize, skip Lean execution.")
    p.add_argument(
        "--lean-backend",
        choices=["mock", "lean-cli", "leandojo"],
        default=None,
        help="Override the MINI_ELF_LEAN_BACKEND env var.",
    )
    p.add_argument(
        "--llm-backend",
        choices=["mock", "manual-file", "anthropic", "openai"],
        default=None,
        help="Override the MINI_ELF_LLM_BACKEND env var.",
    )
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase logging verbosity.")
    return p


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    level = logging.WARNING - 10 * min(args.verbose, 2)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    settings = load_settings()
    overrides = {}
    if args.lean_backend is not None:
        overrides["lean_backend"] = args.lean_backend
    if args.llm_backend is not None:
        overrides["llm_backend"] = args.llm_backend
    if overrides:
        settings = dataclasses.replace(settings, **overrides)
        logger.info(
            "Backend overrides from CLI: lean=%s llm=%s",
            settings.lean_backend, settings.llm_backend,
        )

    if settings.llm_backend.lower().replace("_", "-") == "manual-file" and not args.manual_candidates:
        print(
            "error: --llm-backend manual-file requires --manual-candidates PATH",
            file=sys.stderr,
        )
        return 2

    cfg = CollectionConfig(
        seeds_path=args.seeds,
        success_out=args.out,
        failed_out=args.failed_out,
        num_candidates=args.num_candidates,
        temperature=args.temperature,
        max_depth=args.max_depth,
        max_seeds=args.max_seeds,
        prompt_style=args.prompt_style,
        manual_candidates_path=args.manual_candidates,
        dry_run=args.dry_run,
        settings=settings,
    )
    try:
        summary = collect(cfg)
    except RuntimeError as exc:
        # e.g. lean-dojo / openai / anthropic not installed, or missing API key.
        # Surface a clean message instead of a traceback; we never fake success.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(summary.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
