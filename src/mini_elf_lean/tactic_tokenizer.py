"""Mini-ELF v13 — tactic-token tokenizer.

The v8/v9/v10 char-level seq2seq has a well-documented failure mode
(see ``docs/V13_TIMEOUT_RERUN_REPORT.md`` §3): it produces mid-token
truncations like ``rcases h wi`` (clipped ``with``), ``rwexact h``
(fused ``rw`` + ``exact``), ``refin rfl⟩`` (clipped ``refine``), and
``refintro hn`` (fused ``refine`` + ``intro``). Once the decoder has
chosen those characters the candidate is unrecoverable — no
post-processing rule can splice the missing characters back.

This module provides a deterministic tokenizer over the Mini-ELF tactic
surface so a future token-level seq2seq (``v14``) cannot make those
mistakes by construction: each token is the smallest atomic unit
(keyword, identifier, number, Lean symbol, punctuation, whitespace
chunk) and the decoder either emits it whole or not at all.

The module is intentionally pure-Python and stand-alone:

* No PyTorch dependency — used by data preprocessors and tests.
* No lean dependency — purely textual.
* No state — every public call is a function on a string.

Public surface:

* :data:`KEYWORDS` — the closed set of tactic-keyword tokens recognised
  by the tokenizer. Adding to this set is the supported way to extend
  the vocabulary; identifiers fall through to ``IDENT`` automatically.
* :data:`SYMBOL_TOKENS` — multi-byte Unicode symbol clusters Lean cares
  about (``⟨``, ``⟩``, ``→`` etc.) tokenised as single tokens.
* :class:`TokenKind` — coarse-grained class tag attached to each token.
* :class:`Token` — ``(kind, text)`` dataclass.
* :func:`tokenize` — string → list[Token].
* :func:`detokenize` — list[Token] → string (exact round-trip on every
  input ``tokenize`` accepts).
* :class:`TacticTokenizer` — convenience wrapper combining both, plus
  the integer-indexed vocabulary builder a future trainer will need.

Round-trip guarantee: for any input ``s``,
``detokenize(tokenize(s)) == s``. This is pinned by the unit tests in
``tests/test_tactic_tokenizer.py``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "KEYWORDS",
    "SYMBOL_TOKENS",
    "TokenKind",
    "Token",
    "tokenize",
    "detokenize",
    "TacticTokenizer",
]


# ---- vocabulary ----------------------------------------------------------


#: Closed set of Lean 4 tactic / structural keywords the Mini-ELF
#: corpus uses through v12. Order is insignificant for tokenisation
#: but stable for vocabulary indexing.
KEYWORDS: Tuple[str, ...] = (
    # tactic heads
    "exact", "intro", "intros", "apply", "rw", "rcases", "cases",
    "refine", "constructor", "exists", "use", "have", "show",
    "simp", "simp_all", "omega", "decide", "trivial", "rfl",
    "linarith", "norm_num", "ring", "aesop", "tauto",
    "exfalso", "absurd", "contradiction",
    # structural keywords appearing inside tactic blocks
    "by", "with", "at", "in", "let", "fun", "match",
    # combinators
    "all_goals", "any_goals", "first", "try", "repeat", "skip",
)
_KEYWORD_SET = frozenset(KEYWORDS)


#: Multi-codepoint Unicode glyphs Lean uses as single logical tokens.
#: Ordered so longer prefixes are tested first when scanning.
SYMBOL_TOKENS: Tuple[str, ...] = (
    # angle brackets for anonymous constructors
    "⟨", "⟩",
    # logical connectives
    "∧", "∨", "¬", "↔",
    # arrow / mapsto / forall / exists / pi-sigma
    "→", "↦", "∀", "∃", "Π", "Σ",
    # equality / inequality
    "≤", "≥", "≠", "≈",
    # set / type symbols Mini-ELF doesn't use yet but a future
    # corpus likely will
    "∈", "∉", "⊆", "⊂", "∪", "∩", "⊕", "⊗",
)
_SYMBOL_SET = frozenset(SYMBOL_TOKENS)


#: Single-char punctuation marks treated as standalone tokens. ``.``
#: is included so identifiers like ``n.succ`` tokenise as
#: ``[n][.][succ]`` (three tokens, never one mid-token blob like
#: ``n.suc``).
PUNCTUATION: Tuple[str, ...] = tuple("()[]{},:;.|=<>+-*/!?@&~^%$#'\"\\")
_PUNCT_SET = frozenset(PUNCTUATION)


# ---- token type ----------------------------------------------------------


class TokenKind(str, Enum):
    """Coarse-grained class for each token. Encoded as ``str`` for
    JSON serialisation friendliness."""

    KEYWORD = "KEYWORD"
    IDENT = "IDENT"
    NUMBER = "NUMBER"
    SYMBOL = "SYMBOL"
    PUNCT = "PUNCT"
    WS = "WS"


@dataclass(frozen=True)
class Token:
    """``(kind, text)`` — the smallest tokeniser output unit.

    Equality and hashing are derived from both fields so
    ``[Token(IDENT, "h"), Token(IDENT, "h")] == [Token(IDENT, "h"),
    Token(IDENT, "h")]``.
    """

    kind: TokenKind
    text: str


# ---- scanner -------------------------------------------------------------


# Identifiers: Lean allows Unicode letters, digits, underscores, primes
# and a small set of subscripts. We keep the regex compatible with
# Python's ``re`` (no `regex` dependency) but use Unicode categories
# generously so symbols outside our explicit symbol list still
# tokenise as IDENT runs rather than dribbling out char-by-char.
_IDENT_HEAD = re.compile(r"[^\W\d_]|_", re.UNICODE)
_IDENT_CHAR = re.compile(r"[^\W]|['_]", re.UNICODE)
_NUMBER_RE = re.compile(r"\d+")
_WS_RE = re.compile(r"[ \t\n\r\f\v]+")


def _peek_symbol(s: str, i: int) -> Optional[str]:
    """Return a multi-codepoint symbol starting at ``i`` if any."""
    for sym in SYMBOL_TOKENS:
        if s.startswith(sym, i):
            return sym
    return None


def tokenize(s: str) -> List[Token]:
    """Split a tactic string into atomic tokens.

    The tokeniser is **lossless**: ``detokenize(tokenize(s)) == s`` for
    every ``s`` we recognise. Whitespace is preserved verbatim as a
    single ``WS`` token per contiguous run (a future trainer can
    choose to drop it).

    Unknown bytes are emitted one-at-a-time as ``PUNCT`` tokens so the
    round-trip property holds even on input the tokenizer was not
    explicitly designed for.
    """
    out: List[Token] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]

        # 1. Whitespace runs
        m = _WS_RE.match(s, i)
        if m:
            out.append(Token(TokenKind.WS, m.group(0)))
            i = m.end()
            continue

        # 2. Multi-char Lean symbol clusters (⟨, →, ≤, …)
        sym = _peek_symbol(s, i)
        if sym is not None:
            out.append(Token(TokenKind.SYMBOL, sym))
            i += len(sym)
            continue

        # 3. Numeric literals
        m = _NUMBER_RE.match(s, i)
        if m:
            out.append(Token(TokenKind.NUMBER, m.group(0)))
            i = m.end()
            continue

        # 4. Identifiers / keywords (start with a non-digit word char)
        if _IDENT_HEAD.match(c):
            j = i + 1
            while j < n and _IDENT_CHAR.match(s[j]):
                j += 1
            word = s[i:j]
            kind = TokenKind.KEYWORD if word in _KEYWORD_SET else TokenKind.IDENT
            out.append(Token(kind, word))
            i = j
            continue

        # 5. Single-char punctuation (closed set)
        if c in _PUNCT_SET:
            out.append(Token(TokenKind.PUNCT, c))
            i += 1
            continue

        # 6. Fallback: any other glyph (e.g. an emoji) — emit verbatim
        # as PUNCT one codepoint at a time, so we never lose data.
        # Unicode combining marks would attach to the previous token
        # but Lean tactics don't use them in practice.
        out.append(Token(TokenKind.PUNCT, c))
        i += 1

    return out


def detokenize(tokens: Sequence[Token]) -> str:
    """Concatenate token ``text`` fields. Inverse of :func:`tokenize`
    on every input :func:`tokenize` accepts."""
    return "".join(t.text for t in tokens)


# ---- convenience wrapper -------------------------------------------------


class TacticTokenizer:
    """Bag of helpers a future trainer will want: integer-indexed
    vocabulary, encode / decode by id, and the raw tokenise /
    detokenise pair.

    The vocabulary is **derivable from a corpus** — call
    :meth:`build_vocab` on the training tactics to obtain the closed
    set of identifiers/numbers/keywords/symbols used, then freeze it.
    Out-of-vocabulary tokens at inference time are mapped to
    ``<unk>``; whitespace is mapped to its own ``<ws>`` token id so a
    bag-of-tokens model can simply drop it.
    """

    UNK = "<unk>"
    PAD = "<pad>"
    BOS = "<bos>"
    EOS = "<eos>"

    def __init__(self) -> None:
        self.tok_to_id: Dict[str, int] = {}
        self.id_to_tok: List[str] = []
        # Special tokens always occupy the first four ids in this order.
        for special in (self.PAD, self.BOS, self.EOS, self.UNK):
            self.tok_to_id[special] = len(self.id_to_tok)
            self.id_to_tok.append(special)

    # ----- tokenization (no vocab needed) -----

    @staticmethod
    def tokenize(s: str) -> List[Token]:
        return tokenize(s)

    @staticmethod
    def detokenize(tokens: Sequence[Token]) -> str:
        return detokenize(tokens)

    # ----- vocabulary ops -----

    def add_token(self, text: str) -> int:
        """Register ``text`` if new and return its integer id."""
        i = self.tok_to_id.get(text)
        if i is not None:
            return i
        i = len(self.id_to_tok)
        self.tok_to_id[text] = i
        self.id_to_tok.append(text)
        return i

    def build_vocab(self, tactics: Iterable[str]) -> None:
        """Walk ``tactics`` and add every token's text to the vocab.
        Preserves first-seen ordering for deterministic builds."""
        for s in tactics:
            for t in tokenize(s):
                self.add_token(t.text)

    def encode(self, s: str, *, add_bos: bool = False,
               add_eos: bool = False) -> List[int]:
        ids: List[int] = []
        if add_bos:
            ids.append(self.tok_to_id[self.BOS])
        unk = self.tok_to_id[self.UNK]
        for t in tokenize(s):
            ids.append(self.tok_to_id.get(t.text, unk))
        if add_eos:
            ids.append(self.tok_to_id[self.EOS])
        return ids

    def decode(self, ids: Sequence[int], *,
               strip_specials: bool = True) -> str:
        out: List[str] = []
        specials = {self.PAD, self.BOS, self.EOS} if strip_specials else set()
        for i in ids:
            if 0 <= i < len(self.id_to_tok):
                txt = self.id_to_tok[i]
                if txt in specials:
                    continue
                out.append(txt)
            else:
                out.append(self.UNK)
        return "".join(out)

    @property
    def vocab_size(self) -> int:
        return len(self.id_to_tok)


# ---- diagnostics ---------------------------------------------------------


def explain(s: str) -> str:
    """Return a human-readable rendering of ``tokenize(s)``. Useful
    when debugging char-truncation regressions in candidate output."""
    parts = []
    for t in tokenize(s):
        if t.kind is TokenKind.WS:
            parts.append(f"[WS{len(t.text)}]")
        else:
            parts.append(f"[{t.kind.value}:{t.text}]")
    return "".join(parts)


# A small canary: make sure the symbol list is consistent with the
# frozen set so future edits don't silently break tokenization.
def _selfcheck() -> None:
    for sym in SYMBOL_TOKENS:
        assert sym in _SYMBOL_SET, f"symbol {sym!r} missing from frozenset"
        # Every symbol should consist of non-ASCII characters
        # (otherwise it would clash with the PUNCT scanner).
        assert any(ord(ch) > 127 for ch in sym), (
            f"symbol {sym!r}: at least one codepoint must be non-ASCII"
        )
    # Identifier head regex must reject digits and ASCII punctuation
    assert _IDENT_HEAD.match("9") is None
    assert _IDENT_HEAD.match("(") is None
    # ...and accept underscore + ASCII letters + Unicode letters
    assert _IDENT_HEAD.match("_") is not None
    assert _IDENT_HEAD.match("h") is not None
    assert _IDENT_HEAD.match("α") is not None


_selfcheck()
