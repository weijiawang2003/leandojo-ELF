"""Unit tests for the v14 token-level dataset module.

Pins the contract a future trainer will rely on:

  1. ``TokenVocab.build`` is deterministic and contains the four
     special tokens.
  2. ``encode_source`` / ``encode_target`` agree on round-trip.
  3. Targets carry ``<bos>`` / ``<eos>`` sentinels.
  4. Numeric tokens are *distinct* from identifier tokens (no
     accidental id-collisions).
  5. No ``state_after`` argument anywhere in the module surface.
  6. Malformed train rows (where the tokeniser would NOT round-trip)
     are flagged but preserved.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from mini_elf_lean import token_seq2seq_dataset as tsd
from mini_elf_lean.token_seq2seq_dataset import (
    BOS, EOS, PAD, UNK, SPECIALS, FoldStats, TokenizedRow, TokenVocab,
    build_fold, build_fold_vocab, build_input_text, read_jsonl,
    tokenise_row, write_jsonl,
)


# ----------------------------- vocab basics ---------------------------------


def test_specials_are_first_four() -> None:
    v = TokenVocab(list(SPECIALS) + ["exact", "h", "5"])
    assert v.pad_id == 0
    assert v.bos_id == 1
    assert v.eos_id == 2
    assert v.unk_id == 3
    assert len(v) == 7


def test_build_is_deterministic_in_first_seen_order() -> None:
    v = TokenVocab.build(["exact h"], ["exact h 5"])
    # specials first, then source-side new tokens, then target-side.
    head = v.itos[:4]
    assert head == list(SPECIALS)
    # After specials, "exact" then " " then "h" appear in source. "5"
    # appears only in target.
    assert "exact" in v.stoi and " " in v.stoi
    assert "h" in v.stoi and "5" in v.stoi
    # 5 must come after the source tokens
    assert v.stoi["5"] > v.stoi["exact"]


def test_construct_fails_without_specials() -> None:
    with pytest.raises(ValueError, match="missing required special"):
        TokenVocab(["foo", "bar"])


# ----------------------------- encode / decode -------------------------------


def test_encode_target_starts_with_bos_ends_with_eos() -> None:
    v = TokenVocab.build([], ["exact h 5"])
    ids = v.encode_target("exact h 5")
    assert ids[0] == v.bos_id
    assert ids[-1] == v.eos_id
    # No <bos> or <eos> in the middle
    assert v.bos_id not in ids[1:-1]
    assert v.eos_id not in ids[:-1]


def test_encode_source_has_no_special_sentinels() -> None:
    v = TokenVocab.build(["exact h"], [])
    ids = v.encode_source("exact h")
    for sid in (v.bos_id, v.eos_id, v.pad_id):
        assert sid not in ids


def test_decode_target_round_trips_after_encode() -> None:
    v = TokenVocab.build([], ["exact h 5", "rw [h]"])
    s = "exact h 5"
    ids = v.encode_target(s)
    assert v.decode_target(ids) == s
    s2 = "rw [h]"
    assert v.decode_target(v.encode_target(s2)) == s2


def test_decode_stops_at_eos_and_skips_specials() -> None:
    v = TokenVocab.build([], ["exact h"])
    ids = [v.bos_id, v.stoi["exact"], v.stoi[" "], v.stoi["h"],
           v.eos_id, v.pad_id, v.stoi["exact"]]
    out = v.decode_target(ids)
    assert out == "exact h"


def test_oov_target_token_maps_to_unk() -> None:
    v = TokenVocab.build([], ["exact h"])  # builds only with "exact"," ","h"
    ids = v.encode_target("exact mystery")  # 'mystery' is OOV
    # The OOV id must equal unk_id
    assert v.unk_id in ids
    # Decode strips <unk>, so the OOV is silently dropped (documented)
    out = v.decode_target(ids)
    assert "mystery" not in out
    assert out == "exact "


# ----------------------------- numbers vs idents -----------------------------


def test_numeric_tokens_distinct_from_identifier_tokens() -> None:
    v = TokenVocab.build([], ["exact h 13", "exact h13"])
    # "13" is a NUMBER token; "h13" is an IDENT token. They must NOT share
    # an id even though they share characters.
    assert v.stoi["13"] != v.stoi.get("h13", -1)
    # And both must be present (frozenset semantics)
    assert "13" in v.stoi
    assert "h13" in v.stoi


def test_keywords_are_separate_tokens_from_identifiers() -> None:
    """`with` is a keyword; `wi` is an identifier. They must never
    collide on the same id. This is the core property that prevents
    a token model from emitting `cases h wi`."""
    v = TokenVocab.build([], ["cases h with hn", "cases h wi"])
    assert v.stoi["with"] != v.stoi["wi"]


# ----------------------------- no state_after --------------------------------


def test_module_surface_has_no_state_after_argument() -> None:
    """The module is supposed to read only theorem_statement +
    state_before. A regression that adds `state_after` anywhere in
    the public surface fails this test."""
    public = ("TokenVocab", "build_fold", "build_fold_vocab",
              "build_input_text", "tokenise_row", "write_jsonl",
              "read_jsonl")
    for name in public:
        obj = getattr(tsd, name)
        if inspect.isclass(obj):
            for mname, m in inspect.getmembers(obj, predicate=inspect.isfunction):
                if mname.startswith("_"):
                    continue
                sig = inspect.signature(m)
                assert "state_after" not in sig.parameters, (
                    f"{name}.{mname} has state_after parameter")
        elif inspect.isfunction(obj):
            sig = inspect.signature(obj)
            assert "state_after" not in sig.parameters, (
                f"{name} has state_after parameter")


def test_build_input_text_does_not_consume_state_after_field() -> None:
    """``build_input_text`` is *positional* over (statement, state_before)
    only. If a future caller passes state_after it should not silently
    leak into the input — the function signature has no slot for it."""
    sig = inspect.signature(build_input_text)
    assert list(sig.parameters) == ["theorem_statement", "state_before"]


# ----------------------------- tokenise_row contract -------------------------


def test_tokenise_row_preserves_original_tactic_and_round_trip_flag() -> None:
    vocab = TokenVocab.build(["⊢ p → p"], ["intro h\n  exact h"])
    row = {
        "theorem_name": "t",
        "theorem_statement": "(p : Prop) : p → p",
        "state_before": "⊢ p → p",
        "tactic": "intro h\n  exact h",
        "family": "implication",
    }
    r = tokenise_row(row, vocab, split="train")
    assert r.original_tactic == row["tactic"]
    assert r.detokenized_tactic == row["tactic"]
    assert r.tokeniser_lossless is True
    assert r.family == "implication"
    assert r.target_token_ids[0] == vocab.bos_id
    assert r.target_token_ids[-1] == vocab.eos_id


def test_build_fold_returns_consistent_stats(tmp_path: Path) -> None:
    rows = [
        {"theorem_name": "t1", "theorem_statement": "(p:Prop):p→p",
         "state_before": "⊢ p → p", "tactic": "intro h\n  exact h"},
        {"theorem_name": "t2", "theorem_statement": "(q:Prop):q→q",
         "state_before": "⊢ q → q", "tactic": "intro h\n  exact h"},
    ]
    vocab, tr, te, stats = build_fold(family="impl", train_rows=rows,
                                      test_rows=rows[:1])
    assert stats.n_train == 2 and stats.n_test == 1
    assert stats.vocab_size == len(vocab)
    assert stats.n_train_lossless == 2
    assert stats.n_test_lossless == 1
    assert stats.train_tactic_unique == 1  # both rows have the same tactic


# ----------------------------- persistence ---------------------------------


def test_vocab_save_load_round_trip(tmp_path: Path) -> None:
    v = TokenVocab.build(["a"], ["b c"])
    p = tmp_path / "vocab.json"
    v.save(p)
    v2 = TokenVocab.load(p)
    assert v.itos == v2.itos
    assert v.stoi == v2.stoi
    assert v.pad_id == v2.pad_id


def test_jsonl_round_trip_preserves_token_ids(tmp_path: Path) -> None:
    rows = [
        {"theorem_name": "t1", "theorem_statement": "stmt",
         "state_before": "⊢ p", "tactic": "exact h"},
    ]
    vocab, tr, _te, _stats = build_fold(family="fam", train_rows=rows,
                                        test_rows=[])
    p = tmp_path / "train.jsonl"
    write_jsonl(tr, p)
    loaded = read_jsonl(p)
    assert loaded[0]["original_tactic"] == "exact h"
    assert loaded[0]["target_token_ids"][0] == vocab.bos_id
    assert loaded[0]["target_token_ids"][-1] == vocab.eos_id
