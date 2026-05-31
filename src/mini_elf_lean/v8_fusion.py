"""Mini-ELF v8 — candidate-source fusion.

Combines v8's heterogeneous proposers into a single ranked candidate list while
preserving each proposer's *own* internal score. The fusion is intentionally
simple and transparent — it is **policy**, not a learned ranker:

  * For each query, every active proposer is asked for ``top_k`` candidates.
  * Candidates are tagged with their source label
    (``proof_block_seq2seq``, ``retrieval``, ``retrieval_v7_abstract``,
    ``llm_proposer``, ``planner``, ``witness``, ``retrieval_reconcretized``).
  * Source priority decides ordering when same-family donor support is present
    vs absent:

      ``donor_available=True``  →
          retrieval-first  →  abstraction  →  seq2seq  →  llm  →  planner  →  witness
      ``donor_available=False`` →
          seq2seq-first    →  llm           →  abstraction → retrieval → planner → witness

  * Within a source-tier, items keep the proposer's own rank.
  * After interleaving, the cleaner (Part 4) is applied and duplicates are
    removed.

This is the only place the "same-family donor available" signal acts as a
ranker condition — exactly the v7 audit dimension v8 has to honour.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from .proposer import CandidateProposer, ProposedCandidate
from .proof_block_cleaner import clean_candidates

logger = logging.getLogger(__name__)


# Canonical priority tables. Lower index = higher priority.
DONOR_AVAILABLE_PRIORITY = (
    "retrieval_v7_abstract",
    "retrieval_reconcretized",
    "retrieval",
    "retrieval_adapted",
    "proof_block_seq2seq",
    "llm_proposer",
    "planner",
    "witness",
)
DONORLESS_PRIORITY = (
    "proof_block_seq2seq",
    "llm_proposer",
    "retrieval_v7_abstract",
    "retrieval_reconcretized",
    "retrieval",
    "retrieval_adapted",
    "planner",
    "witness",
)


@dataclass
class FusionResult:
    candidates: List[ProposedCandidate]
    sources_used: Dict[str, int] = field(default_factory=dict)
    cleaner_stats: Dict[str, int] = field(default_factory=dict)


def _priority_index(table: Sequence[str], source: str) -> int:
    try:
        return table.index(source)
    except ValueError:
        # Unknown sources go to the end — they keep their relative order
        # among themselves via the second sort key.
        return len(table) + 1


def fuse(
    proposers: Sequence[CandidateProposer],
    theorem_statement: str,
    state_before: str,
    *,
    theorem_name: Optional[str] = None,
    donor_available: bool = True,
    top_k: int = 10,
    per_source_k: int = 10,
    clean: bool = True,
    propose_kwargs: Optional[Dict[str, Any]] = None,
) -> FusionResult:
    """Run every proposer once, interleave by source priority, clean, dedup,
    truncate to ``top_k``."""
    propose_kwargs = propose_kwargs or {}
    bag: List[ProposedCandidate] = []
    sources_used: Dict[str, int] = {}
    for prop in proposers:
        if hasattr(prop, "available") and not prop.available():
            continue
        try:
            cands = prop.propose(theorem_statement, state_before,
                                  theorem_name=theorem_name,
                                  max_candidates=per_source_k,
                                  top_k=per_source_k,
                                  **propose_kwargs)
        except TypeError:
            # Some proposers reject kwargs they don't know — retry minimal.
            try:
                cands = prop.propose(theorem_statement, state_before,
                                      max_candidates=per_source_k)
            except Exception as exc:  # noqa: BLE001
                logger.warning("proposer %s failed: %s", prop, exc)
                continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("proposer %s failed: %s", prop, exc)
            continue
        if not cands:
            continue
        for c in cands:
            bag.append(c)
            sources_used[c.source] = sources_used.get(c.source, 0) + 1

    if not bag:
        return FusionResult([], sources_used)

    table = DONOR_AVAILABLE_PRIORITY if donor_available else DONORLESS_PRIORITY
    # Stable: sort by (priority, original index inside source).
    # We reconstruct the per-source running index here so the first item from
    # each source goes ahead of the second, etc.
    per_source_seen: Dict[str, int] = {}
    keyed: List[tuple[int, int, ProposedCandidate]] = []
    for c in bag:
        idx = per_source_seen.get(c.source, 0)
        per_source_seen[c.source] = idx + 1
        keyed.append((_priority_index(table, c.source), idx, c))
    keyed.sort(key=lambda triple: (triple[0], triple[1]))

    # Cleaner pass
    if clean:
        raw_tacs = [c.tactic for _p, _i, c in keyed]
        cleaned, stats = clean_candidates(raw_tacs)
        cleaner_stats = stats.to_dict()
    else:
        cleaned = [c.tactic for _p, _i, c in keyed]
        cleaner_stats = {}

    # Map cleaned tactics back to candidates (preserving the first occurrence)
    first_by_tac: Dict[str, ProposedCandidate] = {}
    for _p, _i, c in keyed:
        if c.tactic not in first_by_tac:
            first_by_tac[c.tactic] = c
    out: List[ProposedCandidate] = []
    seen: set = set()
    # Take cleaned items in cleaner order; map each back via raw tactic when
    # possible (the cleaner may have trimmed whitespace, so we accept either).
    raw_to_clean = dict(zip([c.tactic for _p, _i, c in keyed], cleaned + [""] * (len(keyed) - len(cleaned))))
    for _p, _i, c in keyed:
        cleaned_t = raw_to_clean.get(c.tactic) or clean_candidates([c.tactic])[0]
        cleaned_t = cleaned_t[0] if isinstance(cleaned_t, list) else cleaned_t
        if not cleaned_t:
            continue
        if cleaned_t in seen:
            continue
        seen.add(cleaned_t)
        out.append(ProposedCandidate(
            tactic=cleaned_t, source=c.source, score=c.score,
            metadata={**(c.metadata or {}),
                      "fusion_priority": _priority_index(table, c.source),
                      "donor_available_hint": donor_available},
        ))
        if len(out) >= top_k:
            break

    return FusionResult(out, sources_used, cleaner_stats)


# --------------------------------------------------------------------------- #
# Donor-availability hint
# --------------------------------------------------------------------------- #

def family_in_pool(family: Optional[str], pool_families: set) -> bool:
    """Convenience predicate the eval uses to decide which priority table to
    apply. If ``family`` is None (unknown), we conservatively report False —
    treating it as donorless gives the generative proposer a fair shot."""
    if family is None:
        return False
    return family in pool_families


__all__ = [
    "DONOR_AVAILABLE_PRIORITY",
    "DONORLESS_PRIORITY",
    "FusionResult",
    "fuse",
    "family_in_pool",
]
