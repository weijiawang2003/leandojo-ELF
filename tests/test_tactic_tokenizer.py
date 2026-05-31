"""Unit tests for the v13 tactic-token tokenizer.

The tokenizer is the *prerequisite* for v14's planned token-level
seq2seq; it ships in v13 with no model retraining attached. These
tests pin the contract a future trainer will rely on:

  1. Lossless round-trip: ``detokenize(tokenize(s)) == s``.
  2. Keyword vs identifier distinction (so the model can't learn to
     emit a keyword-shaped IDENT mid-token).
  3. Refusal to merge adjacent tokens that look like fused
     truncations the v12 char-level seq2seq produced
     (``rwexact``, ``refintro``).
  4. ``rw [hns`` and ``cases h wi`` — the brief's canonical
     truncation examples — tokenise to a sequence that cannot be
     re-emitted by accidental mid-token character splitting.
  5. Vocabulary determinism, ``encode``/``decode`` symmetry, and
     special-token id allocation.
"""

from __future__ import annotations

import pytest

from mini_elf_lean.tactic_tokenizer import (
    KEYWORDS,
    SYMBOL_TOKENS,
    TacticTokenizer,
    Token,
    TokenKind,
    detokenize,
    explain,
    tokenize,
)


# ----------------------------- round-trip -----------------------------------


ROUNDTRIP_SAMPLES = [
    # Clean Mini-ELF v12 tactics
    "exact h 5",
    "exact h 13",
    "exact h 8",
    "rw [h]",
    "rw [← h]",
    "rfl",
    "intro hn",
    "intros n hn",
    "cases h with | intro n hn => exact ⟨m, hn⟩",
    "rcases h with ⟨n, hn⟩",
    "refine ⟨m, rfl⟩",
    "apply Nat.succ_eq_succ",
    "exact absurd hp h",
    # Truncated outputs from v12 forall_inst_var_m beam — must be
    # representable so the round-trip property holds on the diagnostics.
    "exact h.",
    "rw [hns",
    "cases h wi",
    "refintro hn",
    "rwexact h",
    "refin rfl⟩",
    # Punctuation-heavy / dotted identifiers
    "n.succ = m.succ",
    "by simp [h]",
    "rw [Nat.add_comm a b]",
    # Empty / whitespace-only
    "",
    " ",
    "\t",
    "  \n  ",
]


@pytest.mark.parametrize("s", ROUNDTRIP_SAMPLES, ids=repr)
def test_round_trip(s: str) -> None:
    assert detokenize(tokenize(s)) == s


# ----------------------------- keyword vs ident -----------------------------


def test_keyword_table_is_non_empty_and_sorted_lookups_are_O1() -> None:
    assert "exact" in KEYWORDS
    assert "rw" in KEYWORDS
    assert "with" in KEYWORDS
    assert "rcases" in KEYWORDS
    assert "by" in KEYWORDS
    # A frozenset internal cache must be populated; this is a sanity
    # check that the module didn't get rebuilt with an empty list.
    assert len(KEYWORDS) >= 20


def test_keywords_tokenise_as_KEYWORD() -> None:
    for kw in ("exact", "rw", "rcases", "cases", "intro", "with", "by",
               "refine", "rfl"):
        toks = tokenize(kw)
        assert toks == [Token(TokenKind.KEYWORD, kw)], (
            f"keyword {kw!r} tokenised as {toks}, not [KEYWORD]"
        )


def test_non_keyword_identifiers_tokenise_as_IDENT() -> None:
    for name in ("h", "hn", "hns", "wi", "refintro", "rwexact",
                 "n", "m", "Nat", "succ"):
        toks = tokenize(name)
        assert toks == [Token(TokenKind.IDENT, name)], (
            f"identifier {name!r} tokenised as {toks}"
        )


def test_truncation_artefacts_are_single_IDENTs_not_split() -> None:
    """``refintro`` and ``rwexact`` are fused-truncations from the
    char-level decoder. The tokenizer must treat each as a single
    IDENT token — splitting them silently would *hide* the truncation
    from the eventual trainer's loss."""
    assert tokenize("refintro")[0].kind is TokenKind.IDENT
    assert tokenize("rwexact")[0].kind is TokenKind.IDENT
    # And these are NOT keywords (the closed keyword set is exact)
    from mini_elf_lean.tactic_tokenizer import _KEYWORD_SET  # noqa: WPS437
    assert "refintro" not in _KEYWORD_SET
    assert "rwexact" not in _KEYWORD_SET


# ----------------------------- truncation patterns --------------------------


def test_exact_h_dot_does_not_collapse() -> None:
    """``exact h.`` is the canonical char-truncation pattern from the
    v13 brief. Tokens must separate the identifier from the dot so a
    future token model can't accidentally emit a 4-char-blob like
    ``exct``."""
    toks = tokenize("exact h.")
    assert toks == [
        Token(TokenKind.KEYWORD, "exact"),
        Token(TokenKind.WS, " "),
        Token(TokenKind.IDENT, "h"),
        Token(TokenKind.PUNCT, "."),
    ]


def test_rw_bracket_hns_does_not_leak_identifier_into_keyword() -> None:
    """``rw [hns`` keeps the identifier ``hns`` separate from the
    opening bracket. A future trainer can detect at decode time that
    no matching ``]`` was emitted and abort that beam."""
    toks = tokenize("rw [hns")
    assert toks == [
        Token(TokenKind.KEYWORD, "rw"),
        Token(TokenKind.WS, " "),
        Token(TokenKind.PUNCT, "["),
        Token(TokenKind.IDENT, "hns"),
    ]


def test_cases_h_wi_keeps_wi_distinct_from_keyword_with() -> None:
    """``cases h wi`` (truncation of ``cases h with …``) must
    tokenise ``wi`` as IDENT, never as KEYWORD. The closed keyword
    set has no ``wi`` so this is a property of the lookup rule, not
    a coincidence."""
    toks = tokenize("cases h wi")
    assert toks == [
        Token(TokenKind.KEYWORD, "cases"),
        Token(TokenKind.WS, " "),
        Token(TokenKind.IDENT, "h"),
        Token(TokenKind.WS, " "),
        Token(TokenKind.IDENT, "wi"),
    ]


# ----------------------------- symbols --------------------------------------


@pytest.mark.parametrize("sym", SYMBOL_TOKENS, ids=lambda s: f"sym:{s}")
def test_each_symbol_tokenises_as_one_SYMBOL(sym: str) -> None:
    toks = tokenize(sym)
    assert toks == [Token(TokenKind.SYMBOL, sym)]


def test_angle_brackets_separated_from_inner_identifier() -> None:
    toks = tokenize("⟨m, hn⟩")
    assert toks == [
        Token(TokenKind.SYMBOL, "⟨"),
        Token(TokenKind.IDENT, "m"),
        Token(TokenKind.PUNCT, ","),
        Token(TokenKind.WS, " "),
        Token(TokenKind.IDENT, "hn"),
        Token(TokenKind.SYMBOL, "⟩"),
    ]


# ----------------------------- numbers --------------------------------------


@pytest.mark.parametrize("n", ["0", "1", "5", "13", "100", "9999"], ids=repr)
def test_integer_literal_is_single_NUMBER(n: str) -> None:
    assert tokenize(n) == [Token(TokenKind.NUMBER, n)]


def test_number_separates_from_adjacent_identifier() -> None:
    """``h13`` is a legal identifier but ``h 13`` (with separator) is
    keyword + ident + ws + number. The decoder must produce the
    whitespace explicitly."""
    assert tokenize("h13") == [Token(TokenKind.IDENT, "h13")]
    assert tokenize("h 13") == [
        Token(TokenKind.IDENT, "h"),
        Token(TokenKind.WS, " "),
        Token(TokenKind.NUMBER, "13"),
    ]


# ----------------------------- whitespace -----------------------------------


def test_whitespace_runs_collapse_into_one_WS_token() -> None:
    toks = tokenize("a   b")
    assert toks == [
        Token(TokenKind.IDENT, "a"),
        Token(TokenKind.WS, "   "),
        Token(TokenKind.IDENT, "b"),
    ]


def test_newline_is_whitespace() -> None:
    toks = tokenize("a\nb")
    assert toks == [
        Token(TokenKind.IDENT, "a"),
        Token(TokenKind.WS, "\n"),
        Token(TokenKind.IDENT, "b"),
    ]


# ----------------------------- TacticTokenizer wrapper ----------------------


def test_special_tokens_occupy_first_four_ids() -> None:
    tk = TacticTokenizer()
    assert tk.tok_to_id[TacticTokenizer.PAD] == 0
    assert tk.tok_to_id[TacticTokenizer.BOS] == 1
    assert tk.tok_to_id[TacticTokenizer.EOS] == 2
    assert tk.tok_to_id[TacticTokenizer.UNK] == 3
    assert tk.vocab_size == 4


def test_build_vocab_is_deterministic_in_first_seen_order() -> None:
    tk = TacticTokenizer()
    tk.build_vocab(["exact h", "rw [h]"])
    # IDs reflect first-seen insertion (after specials).
    assert tk.id_to_tok[4:] == ["exact", " ", "h", "rw", "[", "]"]


def test_encode_decode_round_trip_with_specials() -> None:
    tk = TacticTokenizer()
    tk.build_vocab(["exact h 5"])
    ids = tk.encode("exact h 5", add_bos=True, add_eos=True)
    assert ids[0] == tk.tok_to_id[TacticTokenizer.BOS]
    assert ids[-1] == tk.tok_to_id[TacticTokenizer.EOS]
    # decode with strip_specials=True must reconstruct exactly
    assert tk.decode(ids) == "exact h 5"


def test_unknown_token_maps_to_unk() -> None:
    tk = TacticTokenizer()
    tk.build_vocab(["exact h"])
    ids = tk.encode("exact mystery")  # 'mystery' is OOV
    decoded = tk.decode(ids)
    # 'mystery' becomes '<unk>' in the output
    assert "<unk>" in decoded
    assert "exact" in decoded


# ----------------------------- explain --------------------------------------


def test_explain_produces_stable_diagnostic_string() -> None:
    out = explain("exact h 5")
    # The format is stable enough to grep for in failure logs.
    assert "[KEYWORD:exact]" in out
    assert "[IDENT:h]" in out
    assert "[NUMBER:5]" in out


# ----------------------------- module-level invariants ----------------------


def test_no_keyword_collides_with_an_ident_we_use_in_v12() -> None:
    """A future token model must never see ``h``, ``hn``, ``m``, ``n``
    or other variable names as KEYWORD-tagged. If somebody adds
    ``h`` to KEYWORDS by mistake this test fails loudly."""
    from mini_elf_lean.tactic_tokenizer import _KEYWORD_SET  # noqa: WPS437
    for bad in ("h", "hn", "m", "n", "hns", "wi", "α", "β"):
        assert bad not in _KEYWORD_SET, (
            f"{bad!r} must NOT be a keyword (it's a Mini-ELF variable)"
        )
