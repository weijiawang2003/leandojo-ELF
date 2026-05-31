"""Mini-ELF v14 — token-level dataset for the seq2seq retrain.

The v8/v9/v10 / v11 char-level seq2seq used a vocabulary of individual
characters (about 50 entries per fold) and learned to *spell* tactic
heads char-by-char. Its v12/v13 failure mode is documented:
mid-token truncations like ``rcases h wi``, fused keywords like
``rwexact`` / ``refintro``, and clipped identifiers like ``refin``.

This module rebuilds the same v11 family-LOFO folds with the
:mod:`tactic_tokenizer` so a *token-level* model can be trained on
identical (state_before, tactic) pairs. The output of
:class:`TokenVocab` is a drop-in replacement for the char-level
:class:`mini_elf_lean.ar_model.Vocab`: same special tokens, same
``encode_source`` / ``encode_target`` / ``decode_target`` surface.
The existing :class:`mini_elf_lean.ar_model.Seq2Seq`,
:func:`mini_elf_lean.ar_train.train`, and
:func:`mini_elf_lean.ar_decode.beam_search` therefore work unchanged
on top of it.

Key honesty notes:
  * Input side stays ``theorem_statement\\nstate_before`` — the same
    text the v8 char model saw. ``state_after`` is never read.
  * Vocabulary is built from the **train split only** (specials +
    every token seen in any train source-text or train tactic).
    Train-OOV target tokens at inference time map to ``<unk>``.
  * Tokenisation is deterministic and lossless — a unit test pins
    ``detokenize(tokenize(s)) == s`` for every train row.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .tactic_tokenizer import TacticTokenizer, Token, detokenize, tokenize

# Reuse the char-vocab's special-token spellings so the model code does
# not need to know whether it is running over chars or tokens.
PAD = "<pad>"
BOS = "<bos>"
EOS = "<eos>"
UNK = "<unk>"
SPECIALS: Tuple[str, ...] = (PAD, BOS, EOS, UNK)


# --------------------------------------------------------------------------- #
# Row container
# --------------------------------------------------------------------------- #


@dataclass
class TokenizedRow:
    """One (state, tactic) row with token-level ids attached.

    Honesty contract:
      * ``original_tactic`` is the verbatim string from the v11 fold —
        never paraphrased or normalised.
      * ``detokenized_tactic == original_tactic`` for every row whose
        ``tokeniser_lossless`` is True. Rows where the tokeniser is
        NOT a perfect round-trip are flagged but **not dropped** so a
        later auditor can find them.
    """

    theorem_name: str
    theorem_statement: str
    state_before: str
    original_tactic: str
    source_text: str
    source_tokens: List[str]
    source_token_ids: List[int]
    target_tokens: List[str]
    target_token_ids: List[int]
    detokenized_tactic: str
    tokeniser_lossless: bool
    family: Optional[str] = None
    required_operation: Optional[str] = None
    split: str = "train"

    def to_jsonable(self) -> Dict[str, Any]:
        return {
            "theorem_name": self.theorem_name,
            "theorem_statement": self.theorem_statement,
            "state_before": self.state_before,
            "original_tactic": self.original_tactic,
            "source_text": self.source_text,
            "source_tokens": self.source_tokens,
            "source_token_ids": self.source_token_ids,
            "target_tokens": self.target_tokens,
            "target_token_ids": self.target_token_ids,
            "detokenized_tactic": self.detokenized_tactic,
            "tokeniser_lossless": self.tokeniser_lossless,
            "family": self.family,
            "required_operation": self.required_operation,
            "split": self.split,
        }


# --------------------------------------------------------------------------- #
# Token vocabulary (Vocab-compatible)
# --------------------------------------------------------------------------- #


class TokenVocab:
    """Token-level vocabulary built from the tactic tokenizer.

    Drop-in for :class:`mini_elf_lean.ar_model.Vocab`. The only
    semantic difference is that ``encode_*`` operates on
    :func:`tactic_tokenizer.tokenize` outputs rather than per
    character, so identifiers / keywords / numbers / Lean symbols are
    each one id.
    """

    SPECIALS: Tuple[str, ...] = SPECIALS

    def __init__(self, itos: Sequence[str]) -> None:
        self.itos: List[str] = list(itos)
        self.stoi: Dict[str, int] = {t: i for i, t in enumerate(self.itos)}
        for tok in SPECIALS:
            if tok not in self.stoi:
                raise ValueError(f"TokenVocab missing required special {tok!r}")

    # -- special-token ids (same names as Vocab) --
    @property
    def pad_id(self) -> int: return self.stoi[PAD]
    @property
    def bos_id(self) -> int: return self.stoi[BOS]
    @property
    def eos_id(self) -> int: return self.stoi[EOS]
    @property
    def unk_id(self) -> int: return self.stoi[UNK]

    def __len__(self) -> int:
        return len(self.itos)

    # -- construction --
    @classmethod
    def build(cls, train_texts: Iterable[str],
              train_tactics: Iterable[str]) -> "TokenVocab":
        """Build the vocabulary from *train-split only* source texts and
        tactics. Insertion order is preserved so vocab ids are
        deterministic across runs (sorted-by-frequency would have been
        nicer but order-by-first-seen is enough for a small CPU model
        and easier to debug)."""
        ordered: List[str] = list(SPECIALS)
        seen = set(ordered)
        # Walk source text first, then target — matches v0/v1's habit.
        for batch in (train_texts, train_tactics):
            for s in batch:
                for tok in tokenize(s):
                    if tok.text not in seen:
                        ordered.append(tok.text)
                        seen.add(tok.text)
        return cls(ordered)

    # -- encoding (drop-in semantics) --
    def encode_source(self, text: str) -> List[int]:
        unk = self.unk_id
        return [self.stoi.get(tok.text, unk) for tok in tokenize(text)]

    def encode_target(self, tactic: str) -> List[int]:
        unk = self.unk_id
        return ([self.bos_id]
                + [self.stoi.get(tok.text, unk) for tok in tokenize(tactic)]
                + [self.eos_id])

    def decode_target(self, ids: Sequence[int]) -> str:
        """Concatenate token texts (skip specials), stopping at the
        first ``<eos>``. Because the tokenizer's
        ``detokenize(tokenize(s)) == s`` invariant holds, this returns
        a syntactically meaningful tactic string."""
        out: List[str] = []
        special_ids = {self.pad_id, self.bos_id, self.unk_id}
        for i in ids:
            if i == self.eos_id:
                break
            if i in special_ids:
                continue
            if 0 <= i < len(self.itos):
                out.append(self.itos[i])
        return "".join(out)

    # -- persistence --
    def to_json(self) -> str:
        return json.dumps({"itos": self.itos}, ensure_ascii=False)

    def save(self, path: Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TokenVocab":
        return cls(d["itos"])

    @classmethod
    def load(cls, path: Path) -> "TokenVocab":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# --------------------------------------------------------------------------- #
# Build helpers
# --------------------------------------------------------------------------- #


def build_input_text(theorem_statement: str, state_before: str) -> str:
    """The canonical source string. Same shape as
    :func:`mini_elf_lean.ar_model.build_input_text` so the
    char-vs-token comparison is apples-to-apples."""
    return f"{theorem_statement}\n{state_before}"


def tokenise_row(row: Dict[str, Any], vocab: TokenVocab, *,
                 split: str) -> TokenizedRow:
    """Convert one raw proof-block JSON row into a TokenizedRow."""
    stmt = row.get("theorem_statement", "")
    state = row.get("state_before", "")
    tactic = row.get("tactic", "")
    src_text = build_input_text(stmt, state)

    src_toks = [t.text for t in tokenize(src_text)]
    src_ids = vocab.encode_source(src_text)
    tgt_ids = vocab.encode_target(tactic)
    # drop the leading <bos> / trailing <eos> for the human-readable view
    tgt_inner_ids = tgt_ids[1:-1]
    tgt_toks = [vocab.itos[i] if 0 <= i < len(vocab.itos) else UNK
                for i in tgt_inner_ids]

    # Round-trip sanity check on the raw token texts (no <unk> applied):
    raw_target_text = detokenize(tokenize(tactic))
    lossless = (raw_target_text == tactic)

    return TokenizedRow(
        theorem_name=row.get("theorem_name", ""),
        theorem_statement=stmt,
        state_before=state,
        original_tactic=tactic,
        source_text=src_text,
        source_tokens=src_toks,
        source_token_ids=src_ids,
        target_tokens=tgt_toks,
        target_token_ids=tgt_ids,
        detokenized_tactic=raw_target_text,
        tokeniser_lossless=lossless,
        family=row.get("family"),
        required_operation=row.get("required_operation"),
        split=split,
    )


def build_fold_vocab(train_rows: Sequence[Dict[str, Any]]) -> TokenVocab:
    """Build a :class:`TokenVocab` from the train-split rows only."""
    src_texts = [build_input_text(r.get("theorem_statement", ""),
                                  r.get("state_before", ""))
                 for r in train_rows]
    tactics = [r.get("tactic", "") for r in train_rows]
    return TokenVocab.build(src_texts, tactics)


@dataclass
class FoldStats:
    family: str
    n_train: int
    n_test: int
    vocab_size: int
    n_train_lossless: int
    n_test_lossless: int
    train_tactic_unique: int
    test_tactic_unique: int

    def to_jsonable(self) -> Dict[str, Any]:
        return {
            "family": self.family,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "vocab_size": self.vocab_size,
            "n_train_lossless": self.n_train_lossless,
            "n_test_lossless": self.n_test_lossless,
            "train_tactic_unique": self.train_tactic_unique,
            "test_tactic_unique": self.test_tactic_unique,
        }


def build_fold(*, family: str, train_rows: Sequence[Dict[str, Any]],
               test_rows: Sequence[Dict[str, Any]]) -> Tuple[
    TokenVocab, List[TokenizedRow], List[TokenizedRow], FoldStats,
]:
    """Build (vocab, train_tokenized, test_tokenized, stats) for one
    family-LOFO fold."""
    vocab = build_fold_vocab(train_rows)
    tr = [tokenise_row(r, vocab, split="train") for r in train_rows]
    te = [tokenise_row(r, vocab, split="test") for r in test_rows]
    stats = FoldStats(
        family=family,
        n_train=len(tr),
        n_test=len(te),
        vocab_size=len(vocab),
        n_train_lossless=sum(1 for r in tr if r.tokeniser_lossless),
        n_test_lossless=sum(1 for r in te if r.tokeniser_lossless),
        train_tactic_unique=len({r.original_tactic for r in tr}),
        test_tactic_unique=len({r.original_tactic for r in te}),
    )
    return vocab, tr, te, stats


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


def write_jsonl(rows: Sequence[TokenizedRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r.to_jsonable(), ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


__all__ = [
    "PAD", "BOS", "EOS", "UNK", "SPECIALS",
    "TokenizedRow", "TokenVocab", "FoldStats",
    "build_input_text", "tokenise_row", "build_fold_vocab", "build_fold",
    "write_jsonl", "read_jsonl",
]
