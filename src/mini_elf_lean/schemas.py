"""Pydantic schemas for theorem seeds, candidate records, trace records, and run
summaries.

Trace records are the canonical unit consumed by downstream training. A record
represents a single ``(state_before, tactic, state_after)`` attempt. Only records
with ``success=True`` are positive training transitions; failed attempts share the
same shape but live in a separate file so they cannot leak into supervised labels.

Backward compatibility is a hard requirement: old seed/trace JSONL written by
earlier versions of this package must still validate. New fields are therefore
optional with sensible defaults, and ``extra="ignore"`` lets us tolerate stray
keys from hand-written candidate files.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TheoremSeed(BaseModel):
    """One starting point for proof-search trace collection.

    A seed may either be the unproved statement (Lean will give us the initial
    state) or an explicit initial proof state (useful for tests with the mock
    backend, where we want to be deterministic without a real Lean process).
    """

    model_config = ConfigDict(extra="forbid")

    theorem_name: str
    theorem_statement: str
    file_path: Optional[str] = None
    commit: Optional[str] = None
    repo_url: Optional[str] = None
    initial_state: Optional[str] = Field(
        default=None,
        description="Optional initial proof state (used by MockLeanRunner).",
    )

    # ---- LeanDojo locator (only needed for the leandojo backend) ----
    # All optional so mock / lean-cli seeds and older seed files keep working.
    full_name: Optional[str] = Field(
        default=None,
        description="Fully-qualified theorem name for LeanDojo's Theorem(); "
        "falls back to theorem_name when absent.",
    )
    theorem_pos: Optional[Dict[str, int]] = Field(
        default=None,
        description="Optional source position hint, e.g. {'line': 12, 'column': 0}.",
    )
    dojo_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form LeanDojo options carried through to metadata.",
    )

    # ---- LeanCliRunner extension ----
    # `imports` and `template` are used by LeanCliRunner to construct a full
    # `.lean` file. They are optional so the mock backend and pre-existing
    # seed files keep working unchanged.
    imports: List[str] = Field(
        default_factory=list,
        description="Lean import lines (without trailing newline) prepended to the file.",
    )
    template: Optional[str] = Field(
        default=None,
        description="Full Lean theorem body containing `placeholder` where the tactic goes.",
    )
    placeholder: str = Field(
        default="__TACTIC__",
        description="Substring of `template` replaced with the candidate tactic.",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ManualCandidateRecord(BaseModel):
    """One row of a manual / agent-authored candidate file.

    These are *proposals only*. They are matched to seeds by the
    ``ManualFileLLMClient`` and then handed to Lean for verification; nothing in
    this record is a positive label until Lean accepts the tactic.
    """

    model_config = ConfigDict(extra="ignore")

    theorem_name: str
    state_before: Optional[str] = Field(
        default=None,
        description="Proof state the candidates target. Used for exact matching.",
    )
    candidates: List[str] = Field(default_factory=list)
    source: str = "manual-file"
    prompt_style: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TraceRecord(BaseModel):
    """A single proposed, Lean-verified (or rejected) tactic attempt.

    ``success`` is the only field that decides whether this is a positive
    training transition. Failed attempts are written verbatim (to a separate
    file) so that error modes stay inspectable.
    """

    model_config = ConfigDict(extra="ignore")

    theorem_name: str
    theorem_statement: str
    state_before: str
    tactic: str
    state_after: Optional[str]
    success: bool
    proof_finished: bool
    num_goals_before: Optional[int] = None
    num_goals_after: Optional[int] = None
    state_changed: Optional[bool] = None
    error: Optional[str] = None
    timeout: bool = False

    # Provenance.
    source: str = Field(default="llm", description='Where the tactic came from, e.g. "llm".')
    model: str = Field(default="unknown", description="LLM model identifier or 'mock'.")
    backend: str = Field(default="unknown", description="Lean backend that verified it.")
    prompt_style: Optional[str] = None
    temperature: Optional[float] = None
    timestamp: str = Field(default_factory=_utcnow_iso)
    raw_llm_output: Optional[str] = None

    # Optional bookkeeping useful for multi-step traces.
    step_index: int = 0
    parent_state_hash: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CollectionSummary(BaseModel):
    """High-level numbers from a single collection run."""

    model_config = ConfigDict(extra="forbid")

    seeds_processed: int
    tactics_attempted: int
    tactics_succeeded: int
    proofs_finished: int
    duplicates_dropped: int
    forbidden_dropped: int
    timeouts: int
    elapsed_seconds: float
    llm_backend: str = "unknown"
    lean_backend: str = "unknown"

    @property
    def success_rate(self) -> float:
        return self.tactics_succeeded / self.tactics_attempted if self.tactics_attempted else 0.0
