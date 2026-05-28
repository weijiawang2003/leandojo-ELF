"""Sanitize and deduplicate proposed tactic strings.

A candidate source (LLM, manual file, ...) will, despite the system prompt,
occasionally return markdown fences, numbered lists, comments, surrounding
quotes, or `sorry`. Everything here is purely string-level; we never decide
whether a tactic is *valid* (only Lean can do that). The one semantic thing we
do is *flag* automation tactics so the evaluator can report them — we never
delete them here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

FORBIDDEN_TOKENS: Tuple[str, ...] = ("sorry", "admit", "unsafe")

# Tactics that close goals via heavy automation. We track (not delete) these so
# a dataset audit can report the automation ratio and run ablations.
AUTOMATION_TACTICS: frozenset[str] = frozenset(
    {
        "simp",
        "simp_all",
        "aesop",
        "omega",
        "linarith",
        "nlinarith",
        "ring",
        "ring_nf",
        "norm_num",
        "exact?",
        "apply?",
        "grind",
        "decide",
        "tauto",
        "polyrith",
    }
)

# Regexes used to clean per-line junk.
_NUMBERED_PREFIX = re.compile(r"^\s*\d+[.)]\s+")
_BULLET_PREFIX = re.compile(r"^\s*[-*+]\s+")
_INLINE_COMMENT = re.compile(r"\s*--.*$")
_BLOCK_COMMENT = re.compile(r"/-.*?-/", re.DOTALL)
_CODE_FENCE = re.compile(r"^\s*```.*$", re.MULTILINE)


@dataclass(frozen=True)
class SanitizeStats:
    raw_lines: int
    after_clean: int
    after_dedup: int
    after_forbidden: int

    @property
    def forbidden_dropped(self) -> int:
        return self.after_dedup - self.after_forbidden

    @property
    def duplicates_dropped(self) -> int:
        return self.after_clean - self.after_dedup


def _strip_one(line: str) -> str:
    """Clean a single candidate line (numbering, bullets, comments, quotes)."""

    line = _INLINE_COMMENT.sub("", line)
    line = _NUMBERED_PREFIX.sub("", line)
    line = _BULLET_PREFIX.sub("", line)
    line = line.strip()
    # Surrounding backticks (e.g. `simp`) or quotes (e.g. "simp", 'simp').
    for quote in ("`", '"', "'"):
        if len(line) >= 2 and line.startswith(quote) and line.endswith(quote):
            line = line[1:-1].strip()
    return line.strip("`").strip()


def split_raw_output(raw: str, prompt_style: Optional[str] = None) -> List[str]:
    """Split a raw completion string into candidate chunks.

    For most styles we split on newlines (one tactic per line). For the
    ``tactic_block`` style we split on blank lines so a multi-line block stays
    intact as one candidate.
    """

    text = _BLOCK_COMMENT.sub("", raw)
    text = _CODE_FENCE.sub("", text)

    if prompt_style == "tactic_block":
        # Blocks are separated by one or more blank lines.
        blocks = re.split(r"\n\s*\n", text)
        return [b.strip("\n") for b in blocks if b.strip()]
    return list(text.splitlines())


def sanitize_candidate_list(candidates: List[str]) -> Tuple[List[str], SanitizeStats]:
    """Clean, dedupe, and forbidden-filter an explicit list of candidates.

    Each element may be a single tactic or a multi-line tactic block; we keep
    interior newlines intact and only clean the first line's bullet/numbering.
    """

    raw_lines = len(candidates)
    cleaned: List[str] = []
    for cand in candidates:
        if cand is None:
            continue
        c = _BLOCK_COMMENT.sub("", cand)
        c = _CODE_FENCE.sub("", c)
        lines = c.splitlines()
        if not lines:
            continue
        if len(lines) == 1:
            c = _strip_one(lines[0])
        else:
            # Multi-line block: clean only the first line's leading junk and
            # trim surrounding whitespace; keep the inner structure.
            first = _strip_one(lines[0])
            rest = "\n".join(lines[1:]).rstrip()
            c = (first + "\n" + rest).strip() if first else rest.strip()
        if c:
            cleaned.append(c)
    after_clean = len(cleaned)

    seen: set[str] = set()
    deduped: List[str] = []
    for line in cleaned:
        if line in seen:
            continue
        seen.add(line)
        deduped.append(line)
    after_dedup = len(deduped)

    survivors = [ln for ln in deduped if not contains_forbidden(ln)]
    after_forbidden = len(survivors)

    return survivors, SanitizeStats(
        raw_lines=raw_lines,
        after_clean=after_clean,
        after_dedup=after_dedup,
        after_forbidden=after_forbidden,
    )


def sanitize_candidates(
    raw: str, prompt_style: Optional[str] = None
) -> Tuple[List[str], SanitizeStats]:
    """Turn one raw completion string into a clean tactic list.

    Convenience wrapper: split the raw string (style-aware) then run the same
    list sanitizer used for manual candidates, so both paths behave identically.
    """

    return sanitize_candidate_list(split_raw_output(raw, prompt_style))


def contains_forbidden(tactic: str) -> bool:
    """Whole-word match for forbidden tokens (so 'sorry' triggers but
    'sorry_hypothesis_name' does not)."""

    lowered = tactic.lower()
    for tok in FORBIDDEN_TOKENS:
        if re.search(rf"\b{re.escape(tok)}\b", lowered):
            return True
    return False


def tactic_head(tactic: str) -> str:
    """Return the leading token of a tactic, e.g. 'simp only [...]' -> 'simp'.

    For ``exact?`` / ``apply?`` the trailing ``?`` is part of the head, so we
    preserve it when present.
    """

    stripped = tactic.strip().lstrip("(").lstrip()
    if not stripped:
        return ""
    head = stripped.splitlines()[0].split()[0].rstrip(",;")
    return head


def is_automation(tactic: str) -> bool:
    """True if the tactic's head is a tracked automation tactic."""

    return tactic_head(tactic) in AUTOMATION_TACTICS
