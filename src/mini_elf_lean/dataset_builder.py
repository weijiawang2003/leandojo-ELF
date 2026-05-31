"""Verified-trace → modeling-ready dataset builder.

This is the bridge between the collector's raw ``TraceRecord`` JSONL output and
whatever next-tactic model we train. It does **only** three jobs:

  1. classify each record by *how real its verification was*,
  2. filter against an explicit, declared policy,
  3. write a small set of dataset artifacts (next-tactic JSONL, plain-tactic
     text, theorem-level splits, build summary).

The classification is the load-bearing piece. The collector's ``success=True``
is necessary but not sufficient — we also have to record what ``state_after``
actually means for that backend, so downstream code can't accidentally train a
state-transition model on lean-cli's placeholder string or on the mock backend's
synthesized states. We record this per row as ``verification_quality``:

  - ``real``           — leandojo, with a state_after that came from a real
                         ``TacticState.pp`` (or ``"no goals"`` on ProofFinished).
  - ``theorem-level``  — lean-cli, whole-file typecheck; state_after is the
                         ``<verified by lean-cli>`` placeholder.
  - ``mock``           — heuristic, NOT real verification.

Mock records are excluded by default (``allow_mock=False``). LeanDojo records
with ``success=False`` or a missing/placeholder ``state_after`` are dropped from
the next-tactic file even when included as failed examples elsewhere — we never
fabricate a next state.

Splits are by ``theorem_name``, not by record, so all transitions of one
theorem land in the same split. The assignment is deterministic (hash-based)
and stable as new theorems are added — existing splits do not shift.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .io_utils import read_jsonl
from .schemas import TraceRecord

logger = logging.getLogger(__name__)

# The lean-cli runner writes this placeholder into state_after because it can
# only confirm a *whole file* typechecks; there is no intermediate proof state.
LEAN_CLI_PLACEHOLDER = "<verified by lean-cli>"

# Backends the builder knows how to grade. Anything outside this set is treated
# as unknown and excluded (with a counted reason) so we never silently include
# a record whose verification semantics we haven't audited.
KNOWN_BACKENDS = ("mock", "lean-cli", "leandojo")


@dataclass(frozen=True)
class BuildFilters:
    """Explicit, declared filtering policy. Defaults are conservative: keep
    only Lean-verified successes, deduplicate, no length cap."""

    backends: Tuple[str, ...] = ("lean-cli", "leandojo")
    allow_mock: bool = False
    include_failed: bool = False
    include_proof_finished: bool = True
    max_tactic_len: Optional[int] = None
    max_state_len: Optional[int] = None
    dedup: bool = True


@dataclass(frozen=True)
class SplitConfig:
    """Deterministic theorem-name → split assignment. Fractions need not sum
    to exactly 1.0; we bucket by cumulative thresholds. Seeded for stability."""

    train: float = 0.8
    val: float = 0.1
    test: float = 0.1
    seed: int = 42

    def __post_init__(self) -> None:
        for name, v in (("train", self.train), ("val", self.val), ("test", self.test)):
            if v < 0 or v > 1:
                raise ValueError(f"split fraction {name}={v} out of [0,1]")
        total = self.train + self.val + self.test
        if total <= 0:
            raise ValueError("split fractions sum to zero")


@dataclass
class BuildSummary:
    """Machine-readable build report. ``excluded`` is keyed by reason so we can
    explain *why* a record was dropped — silent drops would defeat the audit
    purpose of this layer."""

    inputs: List[str] = field(default_factory=list)
    output_dir: str = ""
    records_read: int = 0
    records_invalid: int = 0
    records_included: int = 0
    excluded: Dict[str, int] = field(default_factory=dict)
    by_backend: Dict[str, int] = field(default_factory=dict)
    by_verification_quality: Dict[str, int] = field(default_factory=dict)
    unique_theorems: int = 0
    unique_tactics: int = 0
    splits: Dict[str, int] = field(default_factory=dict)
    filters: Dict[str, Any] = field(default_factory=dict)
    split_config: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, str] = field(default_factory=dict)

    def bump_excluded(self, reason: str) -> None:
        self.excluded[reason] = self.excluded.get(reason, 0) + 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inputs": self.inputs,
            "output_dir": self.output_dir,
            "records_read": self.records_read,
            "records_invalid": self.records_invalid,
            "records_included": self.records_included,
            "excluded": dict(sorted(self.excluded.items())),
            "by_backend": dict(sorted(self.by_backend.items())),
            "by_verification_quality": dict(sorted(self.by_verification_quality.items())),
            "unique_theorems": self.unique_theorems,
            "unique_tactics": self.unique_tactics,
            "splits": dict(sorted(self.splits.items())),
            "filters": self.filters,
            "split_config": self.split_config,
            "outputs": dict(sorted(self.outputs.items())),
        }


# ---------------- classification ----------------


def _verification_quality(rec: TraceRecord) -> Optional[str]:
    """Return ``"real" | "theorem-level" | "mock"`` or ``None`` if the record
    is too malformed/unknown to classify. Pure function — no I/O."""

    backend = (rec.backend or "").lower()
    if backend == "leandojo":
        # We require a non-placeholder state_after for a real label. For a
        # finished proof state_after is conventionally "no goals" (LeanDojo's
        # documented terminal pp) — also acceptable as real.
        if rec.state_after is None:
            return None  # malformed: success but no state_after isn't usable
        if rec.state_after == LEAN_CLI_PLACEHOLDER:
            return None  # backend marker mismatch — refuse to classify
        return "real"
    if backend == "lean-cli":
        # By design state_after is the placeholder; do not promote to real.
        return "theorem-level"
    if backend == "mock":
        return "mock"
    return None


def _record_includable(
    rec: TraceRecord, filters: BuildFilters, summary: BuildSummary
) -> Tuple[bool, Optional[str]]:
    """Apply policy to one record. Returns (included, verification_quality).
    Increments ``summary.excluded`` with the *first* reason that excluded it,
    so a single record is counted once."""

    backend = (rec.backend or "").lower()
    if backend not in KNOWN_BACKENDS:
        summary.bump_excluded(f"unknown_backend:{backend or '<empty>'}")
        return False, None
    if backend not in filters.backends:
        summary.bump_excluded("backend_filter")
        return False, None

    quality = _verification_quality(rec)
    if quality is None:
        summary.bump_excluded("unverifiable_classification")
        return False, None

    if quality == "mock" and not filters.allow_mock:
        summary.bump_excluded("mock_disallowed")
        return False, None

    if not rec.success:
        if not filters.include_failed:
            summary.bump_excluded("failed_excluded")
            return False, None
    if rec.proof_finished and not filters.include_proof_finished:
        summary.bump_excluded("proof_finished_excluded")
        return False, None

    if filters.max_tactic_len is not None and len(rec.tactic) > filters.max_tactic_len:
        summary.bump_excluded("tactic_too_long")
        return False, None
    if filters.max_state_len is not None:
        for s in (rec.state_before, rec.state_after):
            if s is not None and len(s) > filters.max_state_len:
                summary.bump_excluded("state_too_long")
                return False, None

    return True, quality


# ---------------- split assignment ----------------


def _theorem_split(name: str, cfg: SplitConfig) -> str:
    """Hash ``name`` into [0,1) deterministically (mixed with ``cfg.seed``)
    and bucket by cumulative fractions. New theorems do not shift existing
    assignments because the hash depends only on (name, seed)."""

    h = hashlib.sha256(f"{name}|{cfg.seed}".encode("utf-8")).hexdigest()
    x = int(h[:16], 16) / float(1 << 64)
    total = cfg.train + cfg.val + cfg.test
    tr = cfg.train / total
    va = cfg.val / total
    if x < tr:
        return "train"
    if x < tr + va:
        return "val"
    return "test"


def _record_fingerprint(rec: TraceRecord) -> str:
    """Dedup key + a small content hash for traceability. We dedup on
    (theorem, state_before, tactic) — the same tactic applied to the same
    state of the same theorem should count once, even if collected twice."""

    return hashlib.sha256(
        f"{rec.theorem_name}\x00{rec.state_before}\x00{rec.tactic}".encode("utf-8")
    ).hexdigest()


# ---------------- builder ----------------


def build_dataset(
    inputs: Sequence[Path],
    output_dir: Path,
    *,
    filters: BuildFilters = BuildFilters(),
    splits: SplitConfig = SplitConfig(),
    split_override: Optional[Dict[str, str]] = None,
    split_strategy: str = "hash",
    theorem_meta: Optional[Dict[str, Dict[str, Any]]] = None,
    corpus_source: Optional[str] = None,
) -> BuildSummary:
    """Build dataset artifacts from one or more trace JSONL files.

    Returns a ``BuildSummary``. Outputs (always written, possibly empty):

      - ``output_dir/next_tactic.jsonl``
      - ``output_dir/plain_tactics.txt``
      - ``output_dir/theorem_splits.json``
      - ``output_dir/summary.json``

    ``split_override`` (``theorem_name -> split``) replaces the default hash split
    when provided (used by the v2 split strategies); theorems absent from it fall
    back to the hash. ``theorem_meta`` / ``corpus_source`` are attached to each row
    under a ``metadata`` key so the combined corpus and per-difficulty metrics are
    self-describing.
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    split_override = split_override or {}
    theorem_meta = theorem_meta or {}

    summary = BuildSummary(
        inputs=[str(p) for p in inputs],
        output_dir=str(output_dir),
        filters={
            "backends": list(filters.backends),
            "allow_mock": filters.allow_mock,
            "include_failed": filters.include_failed,
            "include_proof_finished": filters.include_proof_finished,
            "max_tactic_len": filters.max_tactic_len,
            "max_state_len": filters.max_state_len,
            "dedup": filters.dedup,
        },
        split_config={
            "train": splits.train, "val": splits.val, "test": splits.test, "seed": splits.seed,
            "strategy": split_strategy,
        },
    )

    seen_keys: set[str] = set()
    rows: List[Dict[str, Any]] = []
    theorem_split: Dict[str, str] = {}

    for path in inputs:
        for raw in read_jsonl(path):
            summary.records_read += 1
            try:
                rec = TraceRecord.model_validate(raw)
            except Exception as exc:  # noqa: BLE001 - schema details vary by source
                summary.records_invalid += 1
                logger.warning("Invalid record in %s: %s", path, exc)
                continue

            include, quality = _record_includable(rec, filters, summary)
            if not include or quality is None:
                continue

            fp = _record_fingerprint(rec)
            if filters.dedup and fp in seen_keys:
                summary.bump_excluded("duplicate")
                continue
            seen_keys.add(fp)

            if rec.theorem_name not in theorem_split:
                theorem_split[rec.theorem_name] = (
                    split_override.get(rec.theorem_name)
                    or _theorem_split(rec.theorem_name, splits)
                )
            split = theorem_split[rec.theorem_name]

            # state_after_is_real captures whether downstream training can
            # treat state_after as an actual proof state. It is the most
            # important per-row flag; conservative by design.
            state_after_is_real = quality == "real" and rec.state_after is not None

            row: Dict[str, Any] = {
                "theorem_name": rec.theorem_name,
                "theorem_statement": rec.theorem_statement,
                "state_before": rec.state_before,
                "tactic": rec.tactic,
                "state_after": rec.state_after,
                "state_after_is_real": state_after_is_real,
                "proof_finished": rec.proof_finished,
                "num_goals_before": rec.num_goals_before,
                "num_goals_after": rec.num_goals_after,
                "success": rec.success,
                "backend": rec.backend,
                "verification_quality": quality,
                "split": split,
                "source_record_hash": fp,
            }
            if theorem_meta or corpus_source is not None:
                tm = dict(theorem_meta.get(rec.theorem_name, {}))
                if corpus_source is not None:
                    tm["corpus_source"] = corpus_source
                row["metadata"] = tm
            rows.append(row)
            summary.records_included += 1
            summary.by_backend[rec.backend] = summary.by_backend.get(rec.backend, 0) + 1
            summary.by_verification_quality[quality] = (
                summary.by_verification_quality.get(quality, 0) + 1
            )

    # ---- write outputs (always, even when empty) ----
    next_tactic_path = output_dir / "next_tactic.jsonl"
    plain_path = output_dir / "plain_tactics.txt"
    splits_path = output_dir / "theorem_splits.json"
    summary_path = output_dir / "summary.json"

    with next_tactic_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            fh.write("\n")

    # plain_tactics.txt: deduplicated, sorted for reproducibility. We keep this
    # file even when next_tactic.jsonl carries duplicates (filters.dedup=False)
    # because vocab/tokenizer building should always work on the distinct set.
    distinct_tactics = sorted({row["tactic"] for row in rows})
    with plain_path.open("w", encoding="utf-8") as fh:
        for t in distinct_tactics:
            # tactics can be multi-line; collapse newlines so the file is one
            # tactic per text-file line. (The full multi-line tactic lives in
            # next_tactic.jsonl; this file is for byte/vocab work.)
            fh.write(t.replace("\n", "\\n"))
            fh.write("\n")

    # By-split theorem lists, sorted, plus the config that produced them.
    split_lists: Dict[str, List[str]] = {"train": [], "val": [], "test": []}
    for thm, split in theorem_split.items():
        split_lists[split].append(thm)
    for k in split_lists:
        split_lists[k].sort()
    splits_payload = {
        **split_lists,
        "seed": splits.seed,
        "split_fractions": {"train": splits.train, "val": splits.val, "test": splits.test},
        "strategy": split_strategy,
    }
    with splits_path.open("w", encoding="utf-8") as fh:
        json.dump(splits_payload, fh, indent=2, sort_keys=True, ensure_ascii=False)

    summary.unique_theorems = len(theorem_split)
    summary.unique_tactics = len(distinct_tactics)
    summary.splits = {k: len(v) for k, v in split_lists.items()}
    summary.outputs = {
        "next_tactic": str(next_tactic_path),
        "plain_tactics": str(plain_path),
        "theorem_splits": str(splits_path),
        "summary": str(summary_path),
    }
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary.to_dict(), fh, indent=2, sort_keys=True, ensure_ascii=False)

    return summary


# ---------------- helpers ----------------


def expand_inputs(paths: Iterable[str]) -> List[Path]:
    """Expand glob patterns and validate that each path resolves to a file.

    Accepts both already-shell-expanded paths and explicit glob patterns
    (helpful on Windows shells that don't auto-glob). Raises FileNotFoundError
    if a literal path is missing — silent skip would mean a silent dataset shrink.
    """

    import glob

    out: List[Path] = []
    for raw in paths:
        if any(ch in raw for ch in "*?["):
            matches = sorted(glob.glob(raw))
            if not matches:
                raise FileNotFoundError(f"no files matched glob {raw!r}")
            out.extend(Path(m) for m in matches)
        else:
            p = Path(raw)
            if not p.exists():
                raise FileNotFoundError(f"input not found: {raw!r}")
            out.append(p)
    return out
