"""Mini-ELF v35 — embedding + condition encoder for the ELF-style flow model.

Unlike Mini-ELF v0 (:mod:`mini_elf_lean.elf_flow`), which pooled a whole tactic
into a single 48-d latent and decoded with a *separate* GRU, v35 is faithful to
ELF (arXiv 2605.10938): the flow runs over the **per-token embedding sequence**
``Z = E[ids]`` of shape ``(B, T, D)``, and discretization at ``t=1`` is done by a
**shared-weight (tied-embedding) readout** — never a separate decoder head.

This module provides the pieces that do not themselves run the flow:

* :class:`ElfV35Config` — serializable architecture sizes.
* :class:`TokenEmbedding` — the token table ``E`` *and* its tied readout. The
  readout is **nearest-embedding** (Euclidean), implemented as
  ``logit_i = (z·E_i − 0.5·‖E_i‖²) / τ``. The ``−0.5‖E_i‖²`` term is what makes
  ``argmax_i logit_i == argmin_i ‖z − E_i‖²`` (since ‖z‖² is constant across i),
  so ``embed → readout → argmax`` round-trips the embedded token exactly. A plain
  ``z·Eᵀ`` head does NOT have this property — it is a real bug, pinned by a test.
* :class:`ConditionEncoder` — a bi-GRU over the condition tokens
  (``theorem_statement`` + ``state_before``, never ``state_after``) producing
  *per-step* states (the cross-attention memory) plus a pad mask.
* :class:`LatentStats` + :func:`compute_latent_stats` — per-dim train statistics
  used to standardize ``Z1`` so the flow target and the ``N(0,I)`` noise share a
  scale; ``unstandardize(standardize(z)) == z``.
* :func:`padding_mask` — ``ids == pad_id`` boolean mask helper.

CPU-scale by design (``D≈128``, 2–4 layers). Pure-tensor; torch required.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import torch
import torch.nn as nn


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


@dataclass
class ElfV35Config:
    """Architecture sizes for the v35 flow model. Persisted as ``config.json``
    so sampling can rebuild the exact network."""

    vocab_size: int
    d_model: int = 128
    cond_hidden: int = 128       # bi-GRU hidden per direction (output 2× → proj to d_model)
    n_layers: int = 3            # transformer-decoder layers in the velocity field
    n_heads: int = 4
    ff_dim: int = 256
    dropout: float = 0.1
    time_dim: int = 64
    readout_tau: float = 0.5     # temperature for the tied nearest-embedding readout
    max_tgt_len: int = 32        # flow operates over this many target positions (incl bos/eos)
    max_cond_len: int = 96
    pad_id: int = 0
    bos_id: int = 1
    eos_id: int = 2

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    def save(self, path) -> None:
        from pathlib import Path

        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_dict(cls, d: Dict) -> "ElfV35Config":
        fields = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in fields})

    @classmethod
    def load(cls, path) -> "ElfV35Config":
        from pathlib import Path

        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# --------------------------------------------------------------------------- #
# Masks
# --------------------------------------------------------------------------- #


def padding_mask(ids: torch.Tensor, pad_id: int) -> torch.Tensor:
    """Boolean mask, ``True`` where ``ids`` is padding. Shape matches ``ids``.

    Matches the convention used by :mod:`torch.nn` attention modules
    (``*_key_padding_mask``: True == ignore)."""
    return ids == pad_id


# --------------------------------------------------------------------------- #
# Token embedding + tied nearest-embedding readout
# --------------------------------------------------------------------------- #


class TokenEmbedding(nn.Module):
    """The target token table ``E`` and its **tied** nearest-embedding readout.

    ``embed(ids)`` → ``(B, T, D)`` raw embeddings. ``readout_logits(z)`` scores
    every vocab row against ``z`` so that ``argmax`` equals the nearest embedding
    by Euclidean distance; ``readout_ids`` returns that argmax. The readout uses
    the *same* ``E`` (``self.table.weight``) — there is no separate output
    projection, which is the whole point of a tied embedding.
    """

    def __init__(self, cfg: ElfV35Config) -> None:
        super().__init__()
        self.cfg = cfg
        # No padding_idx: we want every row (including pad) to be a real,
        # learnable point so the nearest-embedding readout is well-defined
        # everywhere and the round-trip holds for every id.
        self.table = nn.Embedding(cfg.vocab_size, cfg.d_model)

    @property
    def weight(self) -> torch.Tensor:
        return self.table.weight

    def embed(self, ids: torch.Tensor) -> torch.Tensor:
        """ids ``(B, T)`` int → ``(B, T, D)`` raw embeddings."""
        return self.table(ids)

    def readout_logits(self, z: torch.Tensor, tau: Optional[float] = None) -> torch.Tensor:
        """``z`` in **raw embedding space** ``(..., D)`` → logits ``(..., V)``.

        ``logit_i = (z·E_i − 0.5·‖E_i‖²) / τ``. The constant-across-i term
        ``−‖z‖²`` is dropped (it does not change argmax / softmax over i), and
        the ``−0.5‖E_i‖²`` term turns the dot product into the negative half
        squared Euclidean distance, so ``argmax_i == argmin_i ‖z − E_i‖²``.
        """
        tau = self.cfg.readout_tau if tau is None else tau
        E = self.table.weight                      # (V, D)
        e_sq = 0.5 * (E * E).sum(dim=-1)           # (V,)
        logits = z @ E.t() - e_sq                  # (..., V) via broadcast
        return logits / tau

    def readout_ids(self, z: torch.Tensor, tau: Optional[float] = None) -> torch.Tensor:
        """Nearest-embedding decode: ``(..., D)`` → ``(...)`` int ids."""
        return self.readout_logits(z, tau).argmax(dim=-1)


# --------------------------------------------------------------------------- #
# Condition encoder (bi-GRU → per-step memory + pad mask)
# --------------------------------------------------------------------------- #


class ConditionEncoder(nn.Module):
    """Bi-GRU over the condition tokens → per-step states (cross-attention
    memory) projected to ``d_model``, plus the condition pad mask.

    The condition is ``theorem_statement`` + ``state_before`` tokenized with the
    shared vocab. ``state_after`` is structurally absent. Packing is used so the
    backward GRU direction never flows pad positions into real tokens."""

    def __init__(self, cfg: ElfV35Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.embed = nn.Embedding(cfg.vocab_size, cfg.d_model, padding_idx=cfg.pad_id)
        self.gru = nn.GRU(
            cfg.d_model, cfg.cond_hidden, num_layers=1,
            batch_first=True, bidirectional=True,
        )
        self.proj = nn.Linear(2 * cfg.cond_hidden, cfg.d_model)
        self.dropout = nn.Dropout(cfg.dropout)

    def forward(self, cond_ids: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """cond_ids ``(B, S)`` → (states ``(B, S, D)``, pad_mask ``(B, S)`` bool)."""
        pad_mask = padding_mask(cond_ids, self.cfg.pad_id)        # (B, S) True == pad
        lengths = (~pad_mask).sum(dim=1).clamp(min=1)            # (B,) at least 1
        emb = self.dropout(self.embed(cond_ids))                 # (B, S, D)
        packed = nn.utils.rnn.pack_padded_sequence(
            emb, lengths.cpu(), batch_first=True, enforce_sorted=False
        )
        out_packed, _ = self.gru(packed)
        states, _ = nn.utils.rnn.pad_packed_sequence(
            out_packed, batch_first=True, total_length=cond_ids.size(1)
        )                                                        # (B, S, 2H)
        states = self.proj(states)                               # (B, S, D)
        return states, pad_mask


# --------------------------------------------------------------------------- #
# Latent standardization
# --------------------------------------------------------------------------- #


@dataclass
class LatentStats:
    """Per-dim mean/std of the (raw) train target embeddings, so the flow target
    ``Z1`` and the ``N(0,I)`` noise live on the same scale."""

    mean: List[float]
    std: List[float]

    def tensors(self, device: str = "cpu") -> Tuple[torch.Tensor, torch.Tensor]:
        m = torch.tensor(self.mean, dtype=torch.float32, device=device)
        s = torch.tensor(self.std, dtype=torch.float32, device=device)
        return m, s

    def to_dict(self) -> Dict[str, List[float]]:
        return {"mean": self.mean, "std": self.std}

    @classmethod
    def from_dict(cls, d: Dict[str, List[float]]) -> "LatentStats":
        return cls(mean=list(d["mean"]), std=list(d["std"]))


def standardize(z: torch.Tensor, mean: torch.Tensor, std: torch.Tensor) -> torch.Tensor:
    """``(z − mean) / std``; ``mean``/``std`` broadcast over the last dim."""
    return (z - mean) / std


def unstandardize(x: torch.Tensor, mean: torch.Tensor, std: torch.Tensor) -> torch.Tensor:
    """Inverse of :func:`standardize`: ``x * std + mean``."""
    return x * std + mean


def compute_latent_stats(
    embedding: TokenEmbedding,
    token_ids: Optional[Sequence[int]] = None,
    *,
    eps: float = 1e-3,
) -> LatentStats:
    """Per-dim mean/std of the embedding rows.

    When ``token_ids`` is given (the train-target token multiset), statistics are
    over exactly those rows — the empirical ``Z1`` distribution the flow must
    hit. Otherwise statistics are over the whole table. ``std`` is floored at
    ``eps`` so standardization never divides by zero."""
    with torch.no_grad():
        if token_ids is not None and len(token_ids) > 0:
            idx = torch.tensor(list(token_ids), dtype=torch.long, device=embedding.weight.device)
            rows = embedding.table(idx)            # (N, D)
        else:
            rows = embedding.weight                # (V, D)
        mean = rows.mean(dim=0)
        std = rows.std(dim=0).clamp(min=eps)
    return LatentStats(mean=mean.tolist(), std=std.tolist())


__all__ = [
    "ElfV35Config",
    "TokenEmbedding",
    "ConditionEncoder",
    "LatentStats",
    "padding_mask",
    "standardize",
    "unstandardize",
    "compute_latent_stats",
]
