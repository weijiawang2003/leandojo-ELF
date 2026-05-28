"""Mini-ELF v0 — the continuous latent space (Option A).

Two small char-level networks define the space the flow model transports into:

  - :class:`TacticAutoencoder` — encodes a tactic *string* to a fixed latent
    vector and decodes a latent back to a string (a bottlenecked seq2seq AE).
    This is what makes Mini-ELF *generative*: an arbitrary latent decodes to a
    tactic string, including strings never seen as a label.
  - :class:`ConditionEncoder` — encodes the prompt
    ``theorem_statement + "\\n" + state_before`` to a conditioning vector.

Honesty (unchanged across the project): the AE encodes/decodes the **tactic**;
the condition encoder reads only statement + ``state_before``. ``state_after`` is
never touched (the dataset loader doesn't expose it; a test greps the sources).
This is still theorem-level tactic prediction — *not* next-state modeling.

Small + CPU-only by design: latent 48, cond 128, single-layer GRUs. Requires
PyTorch (optional extra ``.[ar]``); :class:`mini_elf_lean.ar_model.Vocab` is
reused for the shared char vocabulary.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Sequence

import torch
import torch.nn as nn

from .ar_model import Vocab, build_input_text  # reused char vocab + input format


# ---------------- config ----------------


@dataclass
class ElfEmbedConfig:
    vocab_size: int
    latent_dim: int = 48
    cond_dim: int = 128
    ae_emb: int = 48
    ae_hidden: int = 96
    cond_emb: int = 48
    cond_hidden: int = 128
    dropout: float = 0.1
    max_tactic_len: int = 80
    max_cond_len: int = 160
    pad_id: int = 0
    bos_id: int = 1
    eos_id: int = 2

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, d: Dict) -> "ElfEmbedConfig":
        fields = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in fields})


# ---------------- tactic autoencoder ----------------


class TacticAutoencoder(nn.Module):
    """Bottlenecked char-level seq2seq autoencoder: tactic → latent → tactic.

    The encoder's final GRU hidden state is linearly projected to the latent;
    the decoder is conditioned on that latent at every step (concatenated to the
    char embedding and to the output projection). One :meth:`decode_step` is
    shared by teacher-forced training and greedy decoding.
    """

    def __init__(self, cfg: ElfEmbedConfig) -> None:
        super().__init__()
        self.cfg = cfg
        V, E, H, L = cfg.vocab_size, cfg.ae_emb, cfg.ae_hidden, cfg.latent_dim
        self.embedding = nn.Embedding(V, E, padding_idx=cfg.pad_id)
        self.encoder = nn.GRU(E, H, batch_first=True)
        self.to_latent = nn.Linear(H, L)
        self.from_latent = nn.Linear(L, H)
        self.decoder = nn.GRU(E + L, H, batch_first=True)
        self.out = nn.Linear(H + L, V)
        self.dropout = nn.Dropout(cfg.dropout)

    def encode(self, src, src_len):
        emb = self.dropout(self.embedding(src))
        packed = nn.utils.rnn.pack_padded_sequence(
            emb, src_len.cpu(), batch_first=True, enforce_sorted=False
        )
        _, hidden = self.encoder(packed)  # (1, B, H)
        return self.to_latent(hidden[-1])  # (B, L)

    def init_hidden(self, z):
        return torch.tanh(self.from_latent(z)).unsqueeze(0)  # (1, B, H)

    def decode_step(self, prev, hidden, z):
        emb = self.embedding(prev).unsqueeze(1)  # (B, 1, E)
        inp = torch.cat([emb, z.unsqueeze(1)], dim=-1)  # (B, 1, E+L)
        out, hidden = self.decoder(inp, hidden)
        out = out.squeeze(1)  # (B, H)
        logits = self.out(torch.cat([out, z], dim=-1))  # (B, V)
        return logits, hidden

    def forward(self, src, src_len, tgt_in):
        """Teacher-forced reconstruction. Returns (logits (B,T,V), z (B,L))."""
        z = self.encode(src, src_len)
        hidden = self.init_hidden(z)
        logits = []
        for t in range(tgt_in.size(1)):
            step, hidden = self.decode_step(tgt_in[:, t], hidden, z)
            logits.append(step)
        return torch.stack(logits, dim=1), z

    @torch.no_grad()
    def decode_greedy(self, z, vocab: Vocab, *, max_len: int) -> List[str]:
        """Greedy-decode a batch of latents ``z`` (B, L) to tactic strings."""
        self.eval()
        device = z.device
        b = z.size(0)
        hidden = self.init_hidden(z)
        prev = torch.full((b,), vocab.bos_id, dtype=torch.long, device=device)
        done = [False] * b
        outs: List[List[int]] = [[] for _ in range(b)]
        for _ in range(max_len):
            logits, hidden = self.decode_step(prev, hidden, z)
            nxt = logits.argmax(dim=-1)
            for i in range(b):
                if done[i]:
                    continue
                tok = int(nxt[i].item())
                if tok == vocab.eos_id:
                    done[i] = True
                else:
                    outs[i].append(tok)
            if all(done):
                break
            prev = nxt
        return [vocab.decode_target(o) for o in outs]


# ---------------- condition encoder ----------------


class ConditionEncoder(nn.Module):
    """Bi-GRU over ``theorem_statement\\nstate_before`` → conditioning vector."""

    def __init__(self, cfg: ElfEmbedConfig) -> None:
        super().__init__()
        self.cfg = cfg
        V, E, H, C = cfg.vocab_size, cfg.cond_emb, cfg.cond_hidden, cfg.cond_dim
        self.embedding = nn.Embedding(V, E, padding_idx=cfg.pad_id)
        self.gru = nn.GRU(E, H, batch_first=True, bidirectional=True)
        self.proj = nn.Linear(2 * H, C)
        self.dropout = nn.Dropout(cfg.dropout)

    def forward(self, src, src_len):
        emb = self.dropout(self.embedding(src))
        packed = nn.utils.rnn.pack_padded_sequence(
            emb, src_len.cpu(), batch_first=True, enforce_sorted=False
        )
        _, hidden = self.gru(packed)  # (2, B, H)
        cat = torch.cat([hidden[0], hidden[1]], dim=-1)  # (B, 2H)
        return self.proj(cat)  # (B, C)


# ---------------- encoding helpers (shared by train + sample) ----------------


def encode_tactic_batch(tactics: Sequence[str], vocab: Vocab, max_len: int, device: str):
    """Pad a batch of tactic strings to (src, src_len) of raw char ids."""
    pad = vocab.pad_id
    ids = [vocab.encode_source(t)[:max_len] or [pad] for t in tactics]
    m = max(len(s) for s in ids)
    src = torch.tensor([s + [pad] * (m - len(s)) for s in ids], dtype=torch.long, device=device)
    src_len = torch.tensor([len(s) for s in ids], dtype=torch.long)
    return src, src_len


def encode_tactic_targets(tactics: Sequence[str], vocab: Vocab, max_len: int, device: str):
    """(tgt_in, tgt_out) for teacher-forced reconstruction (bos … eos)."""
    pad = vocab.pad_id
    seqs = []
    for t in tactics:
        s = vocab.encode_target(t)[:max_len]
        if s[-1] != vocab.eos_id:
            s[-1] = vocab.eos_id
        seqs.append(s)
    m = max(len(s) for s in seqs)
    tgt = torch.tensor([s + [pad] * (m - len(s)) for s in seqs], dtype=torch.long, device=device)
    return tgt[:, :-1], tgt[:, 1:]


def encode_condition_batch(texts: Sequence[str], vocab: Vocab, max_len: int, device: str):
    pad = vocab.pad_id
    ids = [vocab.encode_source(t)[:max_len] or [pad] for t in texts]
    m = max(len(s) for s in ids)
    src = torch.tensor([s + [pad] * (m - len(s)) for s in ids], dtype=torch.long, device=device)
    src_len = torch.tensor([len(s) for s in ids], dtype=torch.long)
    return src, src_len


def build_vocab_for_elf(train_examples) -> Vocab:
    """Char vocab from the **train split only**: both prompt text and tactics."""
    texts: List[str] = []
    for e in train_examples:
        texts.append(build_input_text(e.theorem_statement, e.state_before))
        texts.append(e.tactic)
    return Vocab.build(texts)
