"""Mini-ELF v35 — the sequence velocity field and the full ELF-style model.

The velocity field ``v_θ(z_t, t, C)`` is a Transformer **decoder** over the
target token positions (bidirectional self-attention — the field is a denoiser,
not autoregressive) with **cross-attention** to the condition memory, an
**additive time embedding**, learned positional embeddings, and a
**self-conditioning** input (the previous clean-signal estimate ``ẑ1``, concat
with ``z_t`` and projected back to ``D``).

:class:`ElfV35Model` bundles the token embedding (+ tied readout), the condition
encoder, the field, and a **learned null condition** for classifier-free
guidance. :meth:`ElfV35Model.build_memory` prepends the null token to the
condition states; passing ``drop`` masks the real condition steps for the
selected batch elements, giving the unconditional path with a single forward.

All flow-matching math (interpolation, target velocity, time embedding) is
reused from :mod:`mini_elf_lean.elf_flow` so the v0 and v35 models share the
exact same, unit-tested primitives.
"""

from __future__ import annotations

from typing import Optional, Tuple

import torch
import torch.nn as nn

from .elf_flow import time_embedding  # shared, unit-tested flow-matching math
from .elf_v35_embed import (
    ConditionEncoder,
    ElfV35Config,
    TokenEmbedding,
)


class SeqVelocityField(nn.Module):
    """``v_θ(z_t, t, C, ẑ1)`` over ``(B, T, D)`` target positions.

    * **self-conditioning**: ``z_t`` is concatenated with the (detached) clean
      estimate ``ẑ1`` and projected to ``D``. When self-conditioning is off the
      caller passes zeros, so the architecture is unconditional on it.
    * **time**: a sinusoidal embedding of ``t`` is projected to ``D`` and added
      to every position.
    * **position**: learned positional embeddings over the ``max_tgt_len`` slots.
    * **cross-attention**: to the condition memory, with a key-padding mask so
      pad / dropped condition steps are ignored.

    There is **no causal mask** — the field predicts the velocity for all target
    positions simultaneously, which is what makes train-time and sample-time
    behaviour identical (the input ``z_t`` is defined at every position in both).
    """

    def __init__(self, cfg: ElfV35Config) -> None:
        super().__init__()
        self.cfg = cfg
        D = cfg.d_model
        self.in_proj = nn.Linear(2 * D, D)          # [z_t ; self_cond] → D
        self.time_mlp = nn.Sequential(
            nn.Linear(cfg.time_dim, D), nn.SiLU(), nn.Linear(D, D)
        )
        self.pos_emb = nn.Parameter(torch.zeros(1, cfg.max_tgt_len, D))
        nn.init.normal_(self.pos_emb, std=0.02)
        layer = nn.TransformerDecoderLayer(
            d_model=D, nhead=cfg.n_heads, dim_feedforward=cfg.ff_dim,
            dropout=cfg.dropout, activation="gelu", batch_first=True, norm_first=True,
        )
        self.decoder = nn.TransformerDecoder(layer, num_layers=cfg.n_layers)
        self.out = nn.Linear(D, D)

    def forward(
        self,
        z_t: torch.Tensor,                 # (B, T, D) standardized latent
        t: torch.Tensor,                   # (B,) or (B,1) time in [0,1]
        memory: torch.Tensor,              # (B, M, D) condition memory (null prepended)
        memory_pad_mask: torch.Tensor,     # (B, M) bool, True == ignore
        self_cond: Optional[torch.Tensor] = None,  # (B, T, D) or None → zeros
    ) -> torch.Tensor:
        B, T, D = z_t.shape
        if self_cond is None:
            self_cond = torch.zeros_like(z_t)
        x = self.in_proj(torch.cat([z_t, self_cond], dim=-1))   # (B, T, D)
        te = self.time_mlp(time_embedding(t, self.cfg.time_dim))  # (B, D)
        if te.size(0) == 1 and B > 1:
            te = te.expand(B, -1)
        x = x + te.unsqueeze(1) + self.pos_emb[:, :T, :]         # (B, T, D)
        h = self.decoder(
            tgt=x, memory=memory,
            tgt_mask=None,                                       # non-causal denoiser
            memory_key_padding_mask=memory_pad_mask,
        )
        return self.out(h)                                       # (B, T, D) velocity


class ElfV35Model(nn.Module):
    """Embedding + condition encoder + velocity field + learned null condition."""

    def __init__(self, cfg: ElfV35Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.embed = TokenEmbedding(cfg)
        self.cond_encoder = ConditionEncoder(cfg)
        self.field = SeqVelocityField(cfg)
        # Learned null condition token for classifier-free guidance.
        self.null_token = nn.Parameter(torch.zeros(1, 1, cfg.d_model))
        nn.init.normal_(self.null_token, std=0.02)

    # -- condition memory (with CFG dropout) --------------------------------- #

    def build_memory(
        self, cond_ids: torch.Tensor, drop: Optional[torch.Tensor] = None
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """Encode the condition and prepend the learned null token.

        Returns ``(memory (B, 1+S, D), memory_pad_mask (B, 1+S))``. ``drop`` is a
        per-batch boolean ``(B,)``; where ``True`` the real condition steps are
        masked out so only the null token is attended — the unconditional path
        used for classifier-free guidance — implemented without a second encoder
        pass."""
        states, cond_pad = self.cond_encoder(cond_ids)          # (B,S,D), (B,S)
        B = cond_ids.size(0)
        null = self.null_token.expand(B, 1, self.cfg.d_model)   # (B,1,D)
        memory = torch.cat([null, states], dim=1)               # (B, 1+S, D)
        null_mask = torch.zeros(B, 1, dtype=torch.bool, device=cond_ids.device)
        mem_pad = torch.cat([null_mask, cond_pad], dim=1)       # (B, 1+S)
        if drop is not None:
            drop = drop.to(mem_pad.device).bool()
            if drop.any():
                # mask every condition step (col >=1) for dropped rows; keep null.
                mem_pad[:, 1:] = mem_pad[:, 1:] | drop.unsqueeze(1)
        return memory, mem_pad

    # -- forward ------------------------------------------------------------- #

    def forward(
        self,
        z_t: torch.Tensor,
        t: torch.Tensor,
        *,
        cond_ids: Optional[torch.Tensor] = None,
        memory: Optional[torch.Tensor] = None,
        memory_pad_mask: Optional[torch.Tensor] = None,
        self_cond: Optional[torch.Tensor] = None,
        drop: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Predict the velocity. Either pass ``cond_ids`` (memory built here,
        honouring ``drop``) or a precomputed ``memory`` + ``memory_pad_mask``
        (sampling builds the cond/uncond memories once and reuses them across
        Euler steps)."""
        if memory is None:
            if cond_ids is None:
                raise ValueError("forward requires cond_ids or a precomputed memory")
            memory, memory_pad_mask = self.build_memory(cond_ids, drop)
        return self.field(z_t, t, memory, memory_pad_mask, self_cond)

    # -- convenience --------------------------------------------------------- #

    def embed_targets(self, tgt_ids: torch.Tensor) -> torch.Tensor:
        return self.embed.embed(tgt_ids)

    def readout_logits(self, z_raw: torch.Tensor, tau: Optional[float] = None) -> torch.Tensor:
        return self.embed.readout_logits(z_raw, tau)

    def readout_ids(self, z_raw: torch.Tensor, tau: Optional[float] = None) -> torch.Tensor:
        return self.embed.readout_ids(z_raw, tau)


__all__ = ["SeqVelocityField", "ElfV35Model"]
