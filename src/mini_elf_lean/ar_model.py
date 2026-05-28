"""Character-level autoregressive encoder–decoder for tactic *generation*.

This is the project's first **true generative** tactic model: unlike the
log-linear classifier in :mod:`mini_elf_lean.neural_baseline` — which can only
emit one of the fixed tactic strings seen in training — this model decodes a
tactic **character by character**, so it can in principle produce tactic strings
that never appeared as a training label (the open-vocabulary question the
milestone is about).

Scope / honesty (unchanged from the rest of the project):

  - Input is ``theorem_statement + "\\n" + state_before`` only. ``state_after``
    is **never** read — the model is trained on theorem-level lean-cli verified
    rows where ``state_after_is_real=false``. This is tactic prediction, not
    next-state modeling.
  - Small and CPU-only by design: a (bi)GRU encoder + GRU decoder with additive
    attention, default emb=64 / hidden=128 / 1 layer. No pretraining.

The module is import-safe to *describe* but requires PyTorch to instantiate the
network. :class:`Vocab` is pure-Python and torch-free so vocab construction can
be unit-tested without torch; the ``nn.Module`` classes need ``torch``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

# Torch is the preferred (and only) backend for the network. Import lazily-ish:
# we import at module top so the nn.Modules are available, but Vocab below does
# not depend on torch, and tests gate the torch-dependent paths with
# ``pytest.importorskip("torch")``.
try:  # pragma: no cover - exercised by import, not logic
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover - only when torch isn't installed
    torch = None  # type: ignore
    nn = None  # type: ignore
    F = None  # type: ignore
    _TORCH_AVAILABLE = False


# ---------------- vocabulary (pure Python, torch-free) ----------------

PAD = "<pad>"
BOS = "<bos>"
EOS = "<eos>"
UNK = "<unk>"
SPECIALS: Tuple[str, ...] = (PAD, BOS, EOS, UNK)


class Vocab:
    """Character-level vocabulary.

    Built from the **train split only** (plus the four special tokens) so the
    vocabulary cannot leak information from val/test. Characters unseen at
    inference time map to ``<unk>``.

    The source side (``theorem_statement\\nstate_before``) is encoded as raw
    character ids with no sentinels; the target side (the tactic) is wrapped in
    ``<bos> … <eos>`` so the decoder has explicit start/stop symbols.
    """

    def __init__(self, itos: Sequence[str]) -> None:
        self.itos: List[str] = list(itos)
        self.stoi: Dict[str, int] = {c: i for i, c in enumerate(self.itos)}
        for tok in SPECIALS:
            if tok not in self.stoi:
                raise ValueError(f"vocab missing required special token {tok!r}")

    # -- special-token ids --
    @property
    def pad_id(self) -> int:
        return self.stoi[PAD]

    @property
    def bos_id(self) -> int:
        return self.stoi[BOS]

    @property
    def eos_id(self) -> int:
        return self.stoi[EOS]

    @property
    def unk_id(self) -> int:
        return self.stoi[UNK]

    def __len__(self) -> int:
        return len(self.itos)

    # -- construction --
    @classmethod
    def build(cls, texts: Iterable[str]) -> "Vocab":
        """Build from an iterable of strings (train source + target text).

        Characters are sorted so the mapping is deterministic across runs and
        machines; specials occupy ids 0..3.
        """
        chars = set()
        for t in texts:
            chars.update(t)
        ordered = list(SPECIALS) + sorted(chars)
        return cls(ordered)

    # -- encoding --
    def encode_source(self, text: str) -> List[int]:
        unk = self.unk_id
        return [self.stoi.get(c, unk) for c in text]

    def encode_target(self, tactic: str) -> List[int]:
        unk = self.unk_id
        return [self.bos_id] + [self.stoi.get(c, unk) for c in tactic] + [self.eos_id]

    def decode_target(self, ids: Sequence[int]) -> str:
        """Turn a list of token ids back into a tactic string, stopping at the
        first ``<eos>`` and dropping all special tokens."""
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
    def from_dict(cls, d: Dict) -> "Vocab":
        return cls(d["itos"])

    @classmethod
    def load(cls, path: Path) -> "Vocab":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def build_input_text(theorem_statement: str, state_before: str) -> str:
    """The single canonical source string. Mirrors ``Example.text`` in
    :mod:`mini_elf_lean.baselines` so the AR model and the other baselines see
    *identical* inputs. ``state_after`` is structurally absent here."""
    return f"{theorem_statement}\n{state_before}"


# ---------------- model config ----------------


@dataclass
class Seq2SeqConfig:
    """All architecture + tokenization sizes needed to rebuild the model.

    Persisted as ``config.json`` next to the weights so evaluation can
    reconstruct the exact network.
    """

    vocab_size: int
    embedding_dim: int = 64
    hidden_dim: int = 128
    num_layers: int = 1
    bidirectional_encoder: bool = True
    attention_dim: int = 64
    dropout: float = 0.1
    max_input_len: int = 160
    max_output_len: int = 80
    pad_id: int = 0
    bos_id: int = 1
    eos_id: int = 2

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    def save(self, path: Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_dict(cls, d: Dict) -> "Seq2SeqConfig":
        fields = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in fields})

    @classmethod
    def load(cls, path: Path) -> "Seq2SeqConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# ---------------- the network (requires torch) ----------------


def _require_torch() -> None:
    if not _TORCH_AVAILABLE:  # pragma: no cover - environment guard
        raise RuntimeError(
            "PyTorch is required to build the AR model. Install the CPU build:\n"
            "  pip install torch --index-url https://download.pytorch.org/whl/cpu"
        )


if _TORCH_AVAILABLE:

    class _AdditiveAttention(nn.Module):
        """Bahdanau additive attention. Handles the dimension mismatch between
        the decoder hidden state (``hidden``) and the (bi)encoder outputs
        (``enc_out_dim``) naturally, which is why we prefer it over dot-product
        attention for a bidirectional encoder."""

        def __init__(self, dec_dim: int, enc_dim: int, attn_dim: int) -> None:
            super().__init__()
            self.W_dec = nn.Linear(dec_dim, attn_dim, bias=False)
            self.W_enc = nn.Linear(enc_dim, attn_dim, bias=False)
            self.v = nn.Linear(attn_dim, 1, bias=False)

        def forward(self, dec_hidden, enc_outputs, src_mask):
            # dec_hidden: (B, dec_dim); enc_outputs: (B, S, enc_dim)
            # src_mask: (B, S) True where PADDING.
            scores = self.v(
                torch.tanh(self.W_dec(dec_hidden).unsqueeze(1) + self.W_enc(enc_outputs))
            ).squeeze(-1)  # (B, S)
            scores = scores.masked_fill(src_mask, float("-inf"))
            weights = torch.softmax(scores, dim=-1)  # (B, S)
            context = torch.bmm(weights.unsqueeze(1), enc_outputs).squeeze(1)  # (B, enc_dim)
            return context, weights

    class Seq2Seq(nn.Module):
        """(Bi)GRU encoder + attention + GRU decoder.

        Exposes :meth:`encode` and :meth:`decode_step` so that training
        (teacher forcing) and inference (greedy / beam search in
        :mod:`mini_elf_lean.ar_decode`) share exactly one decode implementation.
        """

        def __init__(self, config: Seq2SeqConfig) -> None:
            _require_torch()
            super().__init__()
            self.config = config
            V, E, H = config.vocab_size, config.embedding_dim, config.hidden_dim
            self.num_layers = config.num_layers
            self.num_dirs = 2 if config.bidirectional_encoder else 1
            self.embedding = nn.Embedding(V, E, padding_idx=config.pad_id)
            self.encoder = nn.GRU(
                E, H, num_layers=config.num_layers, batch_first=True,
                bidirectional=config.bidirectional_encoder,
                dropout=config.dropout if config.num_layers > 1 else 0.0,
            )
            enc_out_dim = H * self.num_dirs
            # Bridge: map concatenated encoder final states -> decoder init.
            self.bridge = nn.Linear(enc_out_dim, H)
            self.attention = _AdditiveAttention(H, enc_out_dim, config.attention_dim)
            self.decoder = nn.GRU(E + enc_out_dim, H, num_layers=config.num_layers, batch_first=True)
            self.dropout = nn.Dropout(config.dropout)
            # Output projection over [decoder_out ; context].
            self.out = nn.Linear(H + enc_out_dim, V)

        # -- encoder --
        def encode(self, src, src_lengths):
            """src: (B, S) padded token ids. Returns (enc_outputs, dec_hidden0,
            src_mask)."""
            emb = self.dropout(self.embedding(src))  # (B, S, E)
            packed = nn.utils.rnn.pack_padded_sequence(
                emb, src_lengths.cpu(), batch_first=True, enforce_sorted=False
            )
            enc_packed, hidden = self.encoder(packed)
            enc_outputs, _ = nn.utils.rnn.pad_packed_sequence(
                enc_packed, batch_first=True, total_length=src.size(1)
            )  # (B, S, H*dirs)
            dec_hidden0 = self._bridge_hidden(hidden)  # (num_layers, B, H)
            src_mask = src == self.config.pad_id  # (B, S) True where pad
            return enc_outputs, dec_hidden0, src_mask

        def _bridge_hidden(self, hidden):
            # hidden: (num_layers*dirs, B, H) -> (num_layers, B, H)
            H = self.config.hidden_dim
            B = hidden.size(1)
            hidden = hidden.view(self.num_layers, self.num_dirs, B, H)
            if self.num_dirs == 2:
                cat = torch.cat([hidden[:, 0], hidden[:, 1]], dim=-1)  # (L, B, 2H)
            else:
                cat = hidden[:, 0]  # (L, B, H)
            return torch.tanh(self.bridge(cat))  # (L, B, H)

        # -- one decoder step (shared by training + decoding) --
        def decode_step(self, prev_token, dec_hidden, enc_outputs, src_mask):
            """prev_token: (B,) ids; dec_hidden: (num_layers, B, H).
            Returns (logits (B, V), new_dec_hidden, attn_weights (B, S))."""
            emb = self.embedding(prev_token).unsqueeze(1)  # (B, 1, E)
            top = dec_hidden[-1]  # (B, H) attention query = top layer
            context, attn = self.attention(top, enc_outputs, src_mask)  # (B, enc_dim)
            gru_in = torch.cat([emb, context.unsqueeze(1)], dim=-1)  # (B, 1, E+enc_dim)
            dec_out, new_hidden = self.decoder(gru_in, dec_hidden)
            dec_out = dec_out.squeeze(1)  # (B, H)
            logits = self.out(torch.cat([dec_out, context], dim=-1))  # (B, V)
            return logits, new_hidden, attn

        # -- full teacher-forced forward (training) --
        def forward(self, src, src_lengths, tgt_in):
            """tgt_in: (B, T) decoder inputs (target shifted right, i.e. starts
            with <bos>). Returns logits (B, T, V)."""
            enc_outputs, dec_hidden, src_mask = self.encode(src, src_lengths)
            logits = []
            for t in range(tgt_in.size(1)):
                step_logits, dec_hidden, _ = self.decode_step(
                    tgt_in[:, t], dec_hidden, enc_outputs, src_mask
                )
                logits.append(step_logits)
            return torch.stack(logits, dim=1)  # (B, T, V)


def count_parameters(model) -> int:
    """Total trainable parameter count (for the config/report)."""
    return int(sum(p.numel() for p in model.parameters() if p.requires_grad))
