"""Vocab construction + data-hygiene tests for the AR seq2seq model.

These are torch-free: :class:`mini_elf_lean.ar_model.Vocab` and the data
helpers do not need PyTorch (the module imports torch defensively), so vocab
behaviour and the "never read ``state_after``" invariant are checked even in an
environment without torch installed.
"""

from __future__ import annotations

from pathlib import Path

from mini_elf_lean.ar_model import (
    BOS,
    EOS,
    PAD,
    SPECIALS,
    UNK,
    Vocab,
    build_input_text,
)
from mini_elf_lean.ar_train import build_vocab
from mini_elf_lean.baselines import Example

SRC = Path(__file__).resolve().parents[1] / "src" / "mini_elf_lean"


def _ex(name, statement, state, tactic, split="train"):
    return Example(
        theorem_name=name, theorem_statement=statement,
        state_before=state, tactic=tactic, split=split,
    )


# ---------------- vocab construction ----------------


def test_specials_occupy_first_ids():
    v = Vocab.build(["abc", "rfl"])
    assert v.itos[:4] == [PAD, BOS, EOS, UNK]
    assert (v.pad_id, v.bos_id, v.eos_id, v.unk_id) == (0, 1, 2, 3)
    for tok in SPECIALS:
        assert tok in v.stoi


def test_vocab_is_deterministic_across_builds():
    a = Vocab.build(["exact h", "intro x"])
    b = Vocab.build(["intro x", "exact h"])  # different order, same chars
    assert a.itos == b.itos


def test_vocab_built_from_train_only_unseen_char_is_unk():
    # 'z' and 'Q' never appear in the training texts.
    v = Vocab.build(["exact h", "rfl"])
    assert "z" not in v.stoi and "Q" not in v.stoi
    ids = v.encode_source("zQ")
    assert ids == [v.unk_id, v.unk_id]


def test_build_vocab_uses_train_examples_only():
    train = [_ex("t1", "(p : Prop) : p", "p\n|- p", "exact h")]
    # A character only present in a *val* tactic must not enter the vocab.
    val = [_ex("t2", "(p : Prop) : p", "p\n|- p", "sorry@@@", split="val")]
    v = build_vocab(train)
    assert "@" not in v.stoi
    assert "exact h"  # sanity
    # everything in the train tactic/text is representable without unk
    assert v.unk_id not in v.encode_source("exact h")


# ---------------- target encode/decode round-trip ----------------


def test_encode_target_wraps_bos_eos():
    v = Vocab.build(["rfl"])
    ids = v.encode_target("rfl")
    assert ids[0] == v.bos_id and ids[-1] == v.eos_id
    assert len(ids) == len("rfl") + 2


def test_source_has_no_sentinels():
    v = Vocab.build(["rfl"])
    ids = v.encode_source("rfl")
    assert v.bos_id not in ids and v.eos_id not in ids


def test_decode_target_round_trip_and_stops_at_eos():
    v = Vocab.build(["exact ⟨hp, hq⟩", "rfl"])
    s = "exact ⟨hp, hq⟩"
    ids = v.encode_target(s)
    assert v.decode_target(ids[1:]) == s  # drop the leading BOS
    # trailing tokens after EOS are ignored
    assert v.decode_target([v.stoi["r"], v.eos_id, v.stoi["f"], v.stoi["l"]]) == "r"


def test_decode_target_skips_specials():
    v = Vocab.build(["rfl"])
    out = v.decode_target([v.pad_id, v.bos_id, v.stoi["r"], v.unk_id, v.stoi["f"]])
    assert out == "rf"


def test_vocab_json_round_trip(tmp_path):
    v = Vocab.build(["exact h", "intro x ⟨⟩"])
    p = tmp_path / "vocab.json"
    v.save(p)
    w = Vocab.load(p)
    assert w.itos == v.itos
    assert w.encode_target("exact h") == v.encode_target("exact h")


# ---------------- data hygiene: never expose state_after ----------------


def test_input_text_is_statement_then_state_before_only():
    e = _ex("t", "(p : Prop) : p", "p : Prop\n⊢ p", "exact h")
    assert build_input_text(e.theorem_statement, e.state_before) == "(p : Prop) : p\np : Prop\n⊢ p"


def test_example_has_no_state_after_attribute():
    e = _ex("t", "s", "st", "tac")
    assert not hasattr(e, "state_after")


def test_ar_source_never_accesses_state_after():
    """No AR module may read a ``state_after`` field. We look for *access*
    patterns (attribute / subscript), not the bare word — the docstrings and a
    ``uses_state_after=False`` provenance flag legitimately mention it."""
    forbidden = [
        ".state_after",
        '["state_after"]',
        "['state_after']",
        'get("state_after"',
        "get('state_after'",
    ]
    for fname in ("ar_model.py", "ar_train.py", "ar_decode.py"):
        text = (SRC / fname).read_text(encoding="utf-8")
        for pat in forbidden:
            assert pat not in text, f"{fname} accesses state_after via {pat!r}"
