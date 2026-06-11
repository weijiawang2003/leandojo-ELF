"""Mini-ELF v38 — Family A: continuous embedded flow, **x-prediction**.

The v35 bug per ELF (arXiv:2605.10938): v-prediction (predict the velocity) fails
with a shared discretization head. v38-A predicts the **clean target embedding x̂≈Z1**
(x-pred) and derives the sampling velocity ``v=(x̂−z_t)/(1−t)``. Flow runs over the
per-token embedding sequence in standardized space (both cond and target inputs
standardized for a consistent trunk space); shared tied nearest-embedding readout;
CE-anchor (prob 0.2); logit-normal time; self-conditioning (prob 0.5,
train/infer-consistent); training-time CFG (cond fully masked for ~10%); frozen
pretrained embeddings by default; ``noise_scale`` on Z0.

``--block`` (semi-AR, BD3-LM arXiv:2503.09573) and learned-vs-frozen embeddings are
exposed for the ablations. Verdict on x-pred vs v-pred is the D1 ablation.
"""

from __future__ import annotations

import zlib
from typing import Dict, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

from .v38_backbone import V38Config, V38Trunk


class FlowModel(nn.Module):
    family = "flow"

    def __init__(self, cfg: V38Config, *, freeze_emb: bool = True, noise_scale: float = 2.0,
                 cfg_drop: float = 0.1, p_ce: float = 0.2, ce_weight: float = 0.2,
                 p_selfcond: float = 0.5, time_p_mean: float = -1.5, time_p_std: float = 0.8,
                 predict: str = "x", unit_norm_emb: bool = False) -> None:
        super().__init__()
        self.cfg = cfg
        self.trunk = V38Trunk(cfg)
        if unit_norm_emb:  # v40 H9: max-separation geometry — rows on the unit sphere so the
            with torch.no_grad():  # tied readout becomes a pure cosine (||E||² constant), cleaner 1-step snap
                w = self.trunk.tok_emb.weight
                w.copy_(torch.nn.functional.normalize(torch.randn_like(w), dim=-1))
        self.in_proj = nn.Linear(2 * cfg.d_model, cfg.d_model)   # [z_t ; self_cond] → D
        self.x_head = nn.Linear(cfg.d_model, cfg.d_model)
        self.noise_scale = noise_scale
        self.cfg_drop = cfg_drop
        self.p_ce = p_ce
        self.ce_weight = ce_weight
        self.p_selfcond = p_selfcond
        self.time_p_mean = time_p_mean
        self.time_p_std = time_p_std
        self.predict = predict                                   # "x" (default) or "v" (D1 ablation)
        self.freeze_emb = freeze_emb
        self.register_buffer("emb_mean", torch.zeros(cfg.d_model))
        self.register_buffer("emb_std", torch.ones(cfg.d_model))
        if freeze_emb:
            self.trunk.tok_emb.weight.requires_grad_(False)
        self.recompute_emb_stats()

    @torch.no_grad()
    def recompute_emb_stats(self, eps: float = 1e-3) -> None:
        E = self.trunk.tok_emb.weight[: self.cfg.vocab_size]
        self.emb_mean.copy_(E.mean(0))
        self.emb_std.copy_(E.std(0).clamp(min=eps))

    def _std(self, raw):
        return (raw - self.emb_mean) / self.emb_std

    def _unstd(self, z):
        return z * self.emb_std + self.emb_mean

    def _core(self, cond_in, z_t, sc, t, kpm):
        """cond_in (B,Sc,D) standardized clean cond; z_t,sc (B,Tt,D) → x̂ (B,Tt,D)."""
        Sc = cond_in.size(1)
        tgt_in = self.in_proj(torch.cat([z_t, sc], dim=-1))
        seq = torch.cat([cond_in, tgt_in], dim=1)
        h = self.trunk(seq, causal=False, key_padding_mask=kpm, time=t)
        return self.x_head(h[:, Sc:, :])

    def loss(self, batch: Dict[str, torch.Tensor]) -> torch.Tensor:
        cfg = self.cfg
        cond_ids, cond_pad = batch["cond_ids"], batch["cond_pad"]
        tgt_ids, tgt_pad = batch["tgt_ids"], batch["tgt_pad"]
        B, Tt = tgt_ids.shape
        Sc = cond_ids.size(1)
        dev = tgt_ids.device
        with torch.no_grad():
            Z1 = self._std(self.trunk.embed_tokens(tgt_ids))     # frozen-emb target
            cond_in = self._std(self.trunk.embed_tokens(cond_ids))
        Z0 = torch.randn(B, Tt, cfg.d_model, device=dev) * self.noise_scale
        t = torch.sigmoid(self.time_p_mean + self.time_p_std * torch.randn(B, device=dev))
        t3 = t[:, None, None]
        z_t = (1 - t3) * Z0 + t3 * Z1
        drop = (torch.rand(B, device=dev) < self.cfg_drop)
        kpm = torch.cat([cond_pad | drop[:, None], torch.zeros(B, Tt, dtype=torch.bool, device=dev)], dim=1)

        sc = torch.zeros_like(z_t)
        if self.p_selfcond > 0:
            with torch.no_grad():
                x0 = self._core(cond_in, z_t, torch.zeros_like(z_t), t, kpm)
                v0 = x0 if self.predict == "x" else (z_t + (1 - t3) * x0)  # v-pred: x0 holds v
                use = (torch.rand(B, device=dev) < self.p_selfcond)[:, None, None].float()
                sc = (v0.detach() if self.predict == "x" else x0.detach()) * use
        out = self._core(cond_in, z_t, sc, t, kpm)
        if self.predict == "x":
            x_hat = out
            target = Z1
        else:  # v-prediction (D1 ablation): out is the velocity; x̂ is implied
            x_hat = z_t + (1 - t3) * out
        valid = (~tgt_pad).float()
        if self.predict == "x":
            mse = (x_hat - Z1).pow(2).mean(-1)              # x-prediction MSE
        else:
            mse = (out - (Z1 - Z0)).pow(2).mean(-1)         # velocity MSE
        L = (mse * valid).sum() / valid.sum().clamp(min=1)
        if self.p_ce > 0 and torch.rand((), device=dev).item() < self.p_ce:
            logits = self.trunk.readout_logits(self._unstd(x_hat))
            L = L + self.ce_weight * F.cross_entropy(
                logits.reshape(-1, logits.size(-1)), tgt_ids.reshape(-1), ignore_index=cfg.pad_id)
        return L

    @torch.no_grad()
    def generate(self, cond_ids: torch.Tensor, *, n_samples: int, steps: int = 16,
                 cfg_weight: float = 2.0, self_cond: bool = True, prompt: str = "",
                 seed: int = 0, device: str = "cpu", **_) -> torch.Tensor:
        cfg = self.cfg
        self.eval()
        K = max(n_samples, 1)
        Sc, Tt = cfg.max_cond_len, cfg.max_tgt_len
        cond = cond_ids.expand(K, -1).to(device)
        cond_pad = cond == cfg.pad_id
        cond_in = self._std(self.trunk.embed_tokens(cond))
        kpm_c = torch.cat([cond_pad, torch.zeros(K, Tt, dtype=torch.bool, device=device)], dim=1)
        kpm_u = torch.cat([torch.ones(K, Sc, dtype=torch.bool, device=device),
                           torch.zeros(K, Tt, dtype=torch.bool, device=device)], dim=1)
        g = torch.Generator(device=device)
        g.manual_seed((seed ^ zlib.crc32(prompt.encode())) & 0x7FFFFFFF)
        z = torch.randn(K, Tt, cfg.d_model, generator=g, device=device) * self.noise_scale
        sc = torch.zeros_like(z)
        use_cfg = abs(cfg_weight - 1.0) > 1e-9
        x_hat = z
        for i in range(max(steps, 1)):
            t_val = i / max(steps, 1)
            t = torch.full((K,), t_val, device=device)
            out_c = self._core(cond_in, z, sc, t, kpm_c)
            x_c = out_c if self.predict == "x" else (z + (1 - t_val) * out_c)
            if use_cfg:
                out_u = self._core(cond_in, z, sc, t, kpm_u)
                x_u = out_u if self.predict == "x" else (z + (1 - t_val) * out_u)
                x_hat = x_u + cfg_weight * (x_c - x_u)
            else:
                x_hat = x_c
            v = (x_hat - z) / max(1 - t_val, 1e-3)
            if self_cond:
                sc = (x_hat if self.predict == "x" else v).detach()
            z = z + (1.0 / max(steps, 1)) * v
        return self.trunk.readout_ids(self._unstd(x_hat))


__all__ = ["FlowModel"]
