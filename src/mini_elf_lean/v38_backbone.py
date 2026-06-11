"""Mini-ELF v38 — shared, param-matched Transformer backbone for the 3-way study.

The three families (continuous flow A, masked-discrete diffusion B, autoregressive
C) all use THIS trunk so they are param-matched by construction at each scale. The
design is a **prefix-LM**: the sequence is ``[clean condition tokens][target
slots]``. What differs per family is only how the target slots are filled and the
attention mask + head:

* **A (flow)**   target slots = noised continuous embeddings ``z_t``; bidirectional;
  + additive time embedding; head predicts the **clean target embedding x̂** (x-pred,
  NOT velocity — ELF arXiv:2605.10938 warns v-pred fails with a shared readout).
* **B (MDLM)**   target slots = token embeddings with some replaced by ``[MASK]``;
  bidirectional; head = tied nearest-embedding logits; predict the masked tokens.
* **C (AR)**     full ``[cond][bos tgt… eos]`` with a causal mask; head = tied
  logits; next-token CE on target positions. Block size L'=1 ≡ AR.

The token embedding ``E`` is shared and the discretization head is the **tied
nearest-embedding readout** ``(z·E − ½‖E‖²)/τ`` (so argmax == nearest embedding;
the v35 round-trip property). ``[MASK]`` occupies id ``vocab_size`` (appended) and
is excluded from the readout. CPU/GPU; bf16/fp16-friendly (no custom autograd).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Dict, Optional

import torch
import torch.nn as nn


def time_embedding(t: torch.Tensor, dim: int) -> torch.Tensor:
    """Sinusoidal embedding of t∈[0,1] → (B, dim)."""
    t = t.reshape(-1).float()
    half = dim // 2
    freqs = torch.exp(-math.log(10000.0) * torch.arange(half, device=t.device, dtype=torch.float32) / max(half, 1))
    args = t.unsqueeze(1) * freqs.unsqueeze(0) * 1000.0
    emb = torch.cat([torch.sin(args), torch.cos(args)], dim=-1)
    if emb.size(1) < dim:
        emb = torch.cat([emb, torch.zeros(emb.size(0), dim - emb.size(1), device=t.device)], dim=-1)
    return emb


@dataclass
class V38Config:
    vocab_size: int           # real token vocab (excludes MASK)
    d_model: int = 512
    n_layers: int = 8
    n_heads: int = 8
    ff_mult: int = 4
    dropout: float = 0.0
    max_cond_len: int = 96
    max_tgt_len: int = 32
    time_dim: int = 128
    readout_tau: float = 1.0   # argmax (flow decode) is tau-invariant; 1.0 stabilizes AR/MDLM CE
    pad_id: int = 0
    bos_id: int = 1
    eos_id: int = 2

    @property
    def mask_id(self) -> int:
        return self.vocab_size            # appended slot for [MASK]

    @property
    def table_size(self) -> int:
        return self.vocab_size + 1        # +1 for [MASK]

    @property
    def max_seq_len(self) -> int:
        return self.max_cond_len + self.max_tgt_len

    def to_json(self):
        import json
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, d: Dict) -> "V38Config":
        f = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in f})


SCALE_PRESETS = {
    "10M":  dict(d_model=256, n_layers=4, n_heads=4),   # v41 plan generators (~10M w/ small plan task)
    "30M":  dict(d_model=512, n_layers=8, n_heads=8),
    "100M": dict(d_model=768, n_layers=12, n_heads=12),
    "200M": dict(d_model=1024, n_layers=16, n_heads=16),
    "tiny": dict(d_model=128, n_layers=2, n_heads=4),   # smoke tests
}


class _Block(nn.Module):
    def __init__(self, cfg: V38Config):
        super().__init__()
        self.n1 = nn.LayerNorm(cfg.d_model)
        self.attn = nn.MultiheadAttention(cfg.d_model, cfg.n_heads, dropout=cfg.dropout, batch_first=True)
        self.n2 = nn.LayerNorm(cfg.d_model)
        self.mlp = nn.Sequential(
            nn.Linear(cfg.d_model, cfg.ff_mult * cfg.d_model), nn.GELU(),
            nn.Linear(cfg.ff_mult * cfg.d_model, cfg.d_model),
        )

    def forward(self, x, attn_mask, key_padding_mask):
        h = self.n1(x)
        a, _ = self.attn(h, h, h, attn_mask=attn_mask, key_padding_mask=key_padding_mask, need_weights=False)
        x = x + a
        x = x + self.mlp(self.n2(x))
        return x


class V38Trunk(nn.Module):
    """Shared trunk + shared token table + tied nearest-embedding readout."""

    def __init__(self, cfg: V38Config):
        super().__init__()
        self.cfg = cfg
        self.tok_emb = nn.Embedding(cfg.table_size, cfg.d_model)
        nn.init.normal_(self.tok_emb.weight, std=0.02)   # standard small init (tied readout stability)
        self.pos_emb = nn.Parameter(torch.zeros(1, cfg.max_seq_len, cfg.d_model))
        nn.init.normal_(self.pos_emb, std=0.02)
        self.time_mlp = nn.Sequential(nn.Linear(cfg.time_dim, cfg.d_model), nn.SiLU(),
                                      nn.Linear(cfg.d_model, cfg.d_model))
        self.blocks = nn.ModuleList(_Block(cfg) for _ in range(cfg.n_layers))
        self.norm_f = nn.LayerNorm(cfg.d_model)

    # -- embeddings --
    def embed_tokens(self, ids: torch.Tensor) -> torch.Tensor:
        return self.tok_emb(ids)

    @property
    def E(self) -> torch.Tensor:
        return self.tok_emb.weight                       # (table_size, D)

    def set_embeddings(self, weight: torch.Tensor, freeze: bool) -> None:
        with torch.no_grad():
            self.tok_emb.weight.copy_(weight)
        self.tok_emb.weight.requires_grad_(not freeze)

    # -- tied nearest-embedding readout over the REAL vocab (excludes MASK) --
    def readout_logits(self, z: torch.Tensor, tau: Optional[float] = None) -> torch.Tensor:
        tau = self.cfg.readout_tau if tau is None else tau
        E = self.tok_emb.weight[: self.cfg.vocab_size]   # (V, D) — drop MASK row
        e_sq = 0.5 * (E * E).sum(dim=-1)
        return (z @ E.t() - e_sq) / tau

    def readout_ids(self, z: torch.Tensor, tau: Optional[float] = None) -> torch.Tensor:
        return self.readout_logits(z, tau).argmax(dim=-1)

    # -- trunk forward --
    def forward(self, inputs_embeds: torch.Tensor, *, causal: bool,
                key_padding_mask: Optional[torch.Tensor] = None,
                time: Optional[torch.Tensor] = None) -> torch.Tensor:
        B, T, _ = inputs_embeds.shape
        x = inputs_embeds + self.pos_emb[:, :T, :]
        if time is not None:
            te = self.time_mlp(time_embedding(time, self.cfg.time_dim))   # (B, D)
            x = x + te.unsqueeze(1)
        attn_mask = None
        if causal:
            attn_mask = torch.triu(torch.full((T, T), float("-inf"), device=x.device), diagonal=1)
        for blk in self.blocks:
            x = blk(x, attn_mask, key_padding_mask)
        return self.norm_f(x)


def count_params(m: nn.Module) -> int:
    return int(sum(p.numel() for p in m.parameters()))


__all__ = ["V38Config", "V38Trunk", "SCALE_PRESETS", "time_embedding", "count_params"]
