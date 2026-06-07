"""Mini-ELF v38 — Family B: masked discrete diffusion (MDLM-style).

Absorbing-state ([MASK]) forward process over the SAME token vocab; a bidirectional
trunk predicts the original tokens at masked positions; continuous-time masked
ELBO with the linear schedule α_t = 1−t (MDLM, Sahoo et al. arXiv:2406.07524).
This is the formulation the data-constrained crossover literature credits
(any-order masking = implicit data augmentation; Prabhudesai arXiv:2507.15857).
Generation is MaskGIT-style confidence unmasking (start all-[MASK], commit the
most-confident positions over N steps). Block size L'=1 of the family reduces to
AR; L'=max is full diffusion.

Loss (linear schedule): per example sample t~U(ε,1), mask each target position iid
w.p. t (over the full fixed target block so the model learns the eos/pad tail too),
predict masked tokens, weight per-token CE by the MDLM factor 1/t, average over
masked tokens. ``state_after`` never read.
"""

from __future__ import annotations

import zlib
from typing import Dict

import torch
import torch.nn as nn
import torch.nn.functional as F

from .v38_backbone import V38Config, V38Trunk


class MDLMModel(nn.Module):
    family = "mdlm"

    def __init__(self, cfg: V38Config, *, t_eps: float = 1e-3) -> None:
        super().__init__()
        self.cfg = cfg
        self.trunk = V38Trunk(cfg)
        self.t_eps = t_eps

    def loss(self, batch: Dict[str, torch.Tensor]) -> torch.Tensor:
        cfg = self.cfg
        cond_ids, cond_pad = batch["cond_ids"], batch["cond_pad"]
        tgt_ids = batch["tgt_ids"]
        B, Tt = tgt_ids.shape
        Sc = cond_ids.size(1)
        dev = tgt_ids.device
        t = torch.rand(B, device=dev).clamp(self.t_eps, 1.0)              # masking prob per example
        mask = torch.rand(B, Tt, device=dev) < t[:, None]                # over the full target block
        x_t = torch.where(mask, torch.full_like(tgt_ids, cfg.mask_id), tgt_ids)
        seq = torch.cat([cond_ids, x_t], dim=1)
        kpm = torch.cat([cond_pad, torch.zeros(B, Tt, dtype=torch.bool, device=dev)], dim=1)
        h = self.trunk(self.trunk.embed_tokens(seq), causal=False, key_padding_mask=kpm)
        logits = self.trunk.readout_logits(h[:, Sc:, :])                 # (B,Tt,V)
        ce = F.cross_entropy(logits.reshape(-1, logits.size(-1)), tgt_ids.reshape(-1), reduction="none").reshape(B, Tt)
        w = (1.0 / t)[:, None]                                           # MDLM linear-schedule weight
        masked = mask.float()
        return (ce * masked * w).sum() / masked.sum().clamp(min=1.0)

    @torch.no_grad()
    def generate(self, cond_ids: torch.Tensor, *, n_samples: int, steps: int = 16,
                 temperature: float = 1.0, prompt: str = "", seed: int = 0,
                 device: str = "cpu", **_) -> torch.Tensor:
        """MaskGIT-style confidence unmasking → ids (K, Tt)."""
        cfg = self.cfg
        self.eval()
        K = max(n_samples, 1)
        Sc, Tt = cfg.max_cond_len, cfg.max_tgt_len
        cond = cond_ids.expand(K, -1).to(device)
        cond_pad = cond == cfg.pad_id
        kpm = torch.cat([cond_pad, torch.zeros(K, Tt, dtype=torch.bool, device=device)], dim=1)
        g = torch.Generator(device=device)
        g.manual_seed((seed ^ zlib.crc32(prompt.encode())) & 0x7FFFFFFF)
        x = torch.full((K, Tt), cfg.mask_id, dtype=torch.long, device=device)
        for s in range(max(steps, 1)):
            seq = torch.cat([cond, x], dim=1)
            h = self.trunk(self.trunk.embed_tokens(seq), causal=False, key_padding_mask=kpm)
            logits = self.trunk.readout_logits(h[:, Sc:, :]) / max(temperature, 1e-6)
            probs = logits.softmax(dim=-1)                                # (K,Tt,V)
            flat = probs.reshape(K * Tt, -1)
            sampled = torch.multinomial(flat, 1, generator=g).reshape(K, Tt)
            conf = probs.gather(-1, sampled.unsqueeze(-1)).squeeze(-1)    # (K,Tt)
            is_mask = x == cfg.mask_id
            conf = torch.where(is_mask, conf, torch.full_like(conf, float("inf")))  # keep committed
            cand = torch.where(is_mask, sampled, x)
            k = max(1, round(Tt * (s + 1) / max(steps, 1)))
            keep_idx = conf.topk(k, dim=1).indices                       # commit these positions
            new_x = torch.full_like(x, cfg.mask_id)
            new_x.scatter_(1, keep_idx, cand.gather(1, keep_idx))
            x = new_x
        # any residual MASK (shouldn't remain at last step) → pad
        x = torch.where(x == cfg.mask_id, torch.full_like(x, cfg.pad_id), x)
        return x


__all__ = ["MDLMModel"]
