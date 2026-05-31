"""Mini-ELF v8 — light proof-block cleaner.

A focused, *non-templating* normaliser for generator output (seq2seq + LLM).
Operates on a list of raw candidate strings and returns a deduped, trimmed,
non-empty list. The contract is intentionally narrow so this never turns into a
hand-written template engine:

  * strip Markdown code fences (``` and ```lean) — keep what's between them;
  * drop leading "Proof:", "Tactic:" prose labels;
  * drop pure prose lines (lines that look English and contain no Lean tokens);
  * preserve multiline Lean tactic blocks (``rcases/⟨…⟩`` over several lines,
    ``intro h\n  exact …``, etc.) — we don't collapse them;
  * normalise indentation conservatively (strip the common-leading-whitespace
    prefix; do NOT rewrap braces);
  * reject empty / whitespace-only strings;
  * reject strings containing ``state_after`` (extra guard — Mini-ELF never
    reads state_after; if a generator hallucinates one, drop the candidate);
  * dedup by exact post-clean string.

Returns ``(cleaned, stats)`` so the eval can report how many candidates were
dropped and why.

The existing :mod:`tactic_sanitizer` handles single-line cleanup
(numbered-list / bullet / comment / fence stripping) for the LLM proposer; the
v8 cleaner is the **multi-line-aware** counterpart used by the v8 fusion. The
two are deliberately independent so the older path is untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Tuple


# --------------------------------------------------------------------------- #
# Regexes
# --------------------------------------------------------------------------- #

_MD_FENCE_LINE = re.compile(r"^\s*```[\w-]*\s*$")
_LABEL_PROOF = re.compile(r"^\s*(?:proof|tactic|lean|answer)\s*[:\-]\s*", re.IGNORECASE)
_PURE_PROSE = re.compile(
    r"^\s*(?:"
    r"this proof|here is|the (?:proof|theorem|tactic)|we (?:can|need|will)|"
    r"first|then|next|finally|note that|explanation|step \d+|let's"
    r")\b", re.IGNORECASE)
# A line is "lean-shaped" if it contains any of these tokens after the
# explanation filters.
_LEAN_HINT = re.compile(
    r"(?:^|\W)("
    r"exact|intro|intros|apply|cases|rcases|rfl|rewrite|rw|simp|"
    r"refine|constructor|left|right|use|assumption|"
    r"contradiction|absurd|funext|congr|"
    r":=|⟨|⟩|·|→|fun|by|"
    r"\.elim|\.intro|\.mp|\.mpr"
    r")(?:$|\W)", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #

@dataclass
class CleanerStats:
    n_in: int = 0
    n_out: int = 0
    dropped_empty: int = 0
    dropped_prose: int = 0
    dropped_state_after: int = 0
    dropped_duplicate: int = 0
    fences_removed: int = 0
    labels_removed: int = 0

    def to_dict(self) -> dict:
        return {
            "n_in": self.n_in, "n_out": self.n_out,
            "dropped_empty": self.dropped_empty,
            "dropped_prose": self.dropped_prose,
            "dropped_state_after": self.dropped_state_after,
            "dropped_duplicate": self.dropped_duplicate,
            "fences_removed": self.fences_removed,
            "labels_removed": self.labels_removed,
        }


# --------------------------------------------------------------------------- #
# Per-candidate cleanup
# --------------------------------------------------------------------------- #

def _strip_md_fences(s: str, stats: CleanerStats) -> str:
    out_lines: List[str] = []
    for line in s.splitlines():
        if _MD_FENCE_LINE.match(line):
            stats.fences_removed += 1
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def _strip_proof_label(s: str, stats: CleanerStats) -> str:
    m = _LABEL_PROOF.match(s)
    if m:
        stats.labels_removed += 1
        return s[m.end():]
    return s


def _strip_prose_lines(s: str, stats: CleanerStats) -> str:
    """Drop English-prose lines but keep Lean-shaped lines, even if they
    overlap (e.g. a comment line starting with ``--`` is left alone — the
    existing sanitizer / lean parser handles it)."""
    keep: List[str] = []
    for line in s.splitlines():
        stripped = line.strip()
        if not stripped:
            keep.append(line)  # blank lines are kept (multi-line block spacing)
            continue
        if _PURE_PROSE.match(stripped):
            stats.dropped_prose += 1
            continue
        keep.append(line)
    return "\n".join(keep)


def _normalise_indent(s: str) -> str:
    """Strip the common leading whitespace prefix across non-blank lines.
    Conservative — never rewraps brackets."""
    lines = s.splitlines()
    non_blank = [ln for ln in lines if ln.strip()]
    if not non_blank:
        return s
    common = min((len(ln) - len(ln.lstrip(" \t"))) for ln in non_blank)
    if common == 0:
        return s
    return "\n".join(
        (ln[common:] if ln.strip() else ln) for ln in lines
    )


def _contains_state_after(s: str) -> bool:
    return "state_after" in s or "state after" in s.lower()


def clean_candidate(raw: str, stats: CleanerStats) -> str:
    """Apply the per-candidate normaliser sequence. Returns ``""`` if the
    candidate should be rejected (caller handles drop counting)."""
    if raw is None:
        return ""
    s = raw.replace("\r\n", "\n").replace("\r", "\n")
    s = _strip_md_fences(s, stats)
    s = _strip_proof_label(s, stats)
    s = _strip_prose_lines(s, stats)
    s = _normalise_indent(s).strip()
    return s


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def clean_candidates(raw: Iterable[str]) -> Tuple[List[str], CleanerStats]:
    """Clean + dedup. Order is preserved (first occurrence wins)."""
    stats = CleanerStats()
    seen: set[str] = set()
    out: List[str] = []
    for r in raw:
        stats.n_in += 1
        s = clean_candidate(r, stats)
        if not s:
            stats.dropped_empty += 1
            continue
        if _contains_state_after(s):
            stats.dropped_state_after += 1
            continue
        # An all-prose candidate may survive line-filter if every line looked
        # like a prose start but the final pass discards. The dropped_prose
        # counter is incremented per-line; if everything was dropped the
        # candidate becomes empty (caught above).
        if s in seen:
            stats.dropped_duplicate += 1
            continue
        seen.add(s)
        out.append(s)
    stats.n_out = len(out)
    return out, stats


__all__ = [
    "CleanerStats",
    "clean_candidate",
    "clean_candidates",
]
