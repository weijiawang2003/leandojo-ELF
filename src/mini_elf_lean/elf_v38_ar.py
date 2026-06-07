"""Mini-ELF v38 — Family C: matched autoregressive baseline (the current winner).

A prefix-LM decoder over the shared :class:`V38Trunk`: sequence ``[cond][bos … eos
pad]`` with a causal mask; next-token CE on the target positions; tied
nearest-embedding readout. Block size ``L'=1`` of the diffusion families reduces
to exactly this. K candidates are produced by temperature sampling (so the
candidate-diversity comparison with A/B is matched), deduped and frequency-ranked.
"""

from __future__ import annotations

import zlib
from typing import Dict, List, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from .v38_backbone import V38Config, V38Trunk


class ARModel(nn.Module):
    family = "ar"

    def __init__(self, cfg: V38Config):
        super().__init__()
        self.cfg = cfg
        self.trunk = V38Trunk(cfg)

    def loss(self, batch: Dict[str, torch.Tensor]) -> torch.Tensor:
        cfg = self.cfg
        cond_ids, cond_pad = batch["cond_ids"], batch["cond_pad"]
        tgt_ids, tgt_pad = batch["tgt_ids"], batch["tgt_pad"]
        Sc = cond_ids.size(1)
        seq = torch.cat([cond_ids, tgt_ids], dim=1)
        kpm = torch.cat([cond_pad, tgt_pad], dim=1)
        h = self.trunk(self.trunk.embed_tokens(seq), causal=True, key_padding_mask=kpm)
        # predict tgt_ids[:,1:] from hidden at [bos … t_{n-1}] = positions Sc .. Sc+Tt-2
        pred_h = h[:, Sc : Sc + tgt_ids.size(1) - 1, :]
        logits = self.trunk.readout_logits(pred_h)
        targets = tgt_ids[:, 1:]
        return F.cross_entropy(logits.reshape(-1, logits.size(-1)), targets.reshape(-1),
                               ignore_index=cfg.pad_id)

    @torch.no_grad()
    def generate(self, cond_ids: torch.Tensor, *, n_samples: int, prompt: str = "",
                 seed: int = 0, temperature: float = 1.0, device: str = "cpu",
                 **_) -> torch.Tensor:
        """Temperature-sampled AR decode. cond_ids (1,Sc) → ids (K, max_tgt_len)
        (the generated target tokens, bos stripped, eos→pad-tail)."""
        cfg = self.cfg
        self.eval()
        K = max(n_samples, 1)
        Sc, Tt = cfg.max_cond_len, cfg.max_tgt_len
        cond = cond_ids.expand(K, -1).to(device)
        cond_pad = cond == cfg.pad_id
        g = torch.Generator(device=device)
        g.manual_seed((seed ^ zlib.crc32(prompt.encode())) & 0x7FFFFFFF)
        out = torch.full((K, Tt), cfg.pad_id, dtype=torch.long, device=device)
        out[:, 0] = cfg.bos_id
        finished = torch.zeros(K, dtype=torch.bool, device=device)
        for k in range(1, Tt):
            seq = torch.cat([cond, out[:, :k]], dim=1)
            kpm = torch.cat([cond_pad, out[:, :k] == cfg.pad_id], dim=1)
            kpm[:, Sc] = False  # bos is real
            h = self.trunk(self.trunk.embed_tokens(seq), causal=True, key_padding_mask=kpm)
            logits = self.trunk.readout_logits(h[:, -1, :]) / max(temperature, 1e-6)
            probs = logits.softmax(dim=-1)
            nxt = torch.multinomial(probs, 1, generator=g).squeeze(-1)
            nxt = torch.where(finished, torch.full_like(nxt, cfg.pad_id), nxt)
            out[:, k] = nxt
            finished = finished | (nxt == cfg.eos_id)
            if bool(finished.all()):
                break
        return out


__all__ = ["ARModel"]
