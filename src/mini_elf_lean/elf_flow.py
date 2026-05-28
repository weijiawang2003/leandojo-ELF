"""Mini-ELF v0 — conditional rectified-flow (flow-matching) model.

Transports Gaussian noise to the tactic-latent distribution, conditioned on the
prompt embedding. Rectified-flow / flow-matching formulation:

    eps ~ N(0, I)                          # noise
    x   = standardized tactic latent       # data point (from the AE, frozen)
    t   ~ U(0, 1)
    z_t = (1 - t) * eps + t * x            # straight-line interpolation
    v*  = x - eps                          # constant target velocity
    loss = || v_theta(z_t, t, c) - v* ||^2

Sampling integrates dz/dt = v_theta(z, t, c) from z(0)=eps to z(1) (Euler), so a
trained model maps noise → a latent that decodes to a plausible tactic. The
network is a small MLP — `latent_dim + time_embed + cond_dim` in, `latent_dim`
out. CPU-friendly; deterministic given a seeded generator at sample time.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Dict

import torch
import torch.nn as nn


# ---------------- flow-matching math (pure tensor ops; unit-tested) ----------------


def interpolate(eps: torch.Tensor, x: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
    """Straight-line interpolation ``z_t = (1 - t) * eps + t * x``.

    ``t`` broadcasts against ``eps``/``x`` (pass shape ``(B, 1)`` for a per-row
    time). At ``t=0`` returns ``eps``; at ``t=1`` returns ``x``.
    """
    return (1.0 - t) * eps + t * x


def velocity_target(eps: torch.Tensor, x: torch.Tensor) -> torch.Tensor:
    """Constant target velocity of the straight path: ``x - eps`` (shape of x)."""
    return x - eps


def time_embedding(t: torch.Tensor, dim: int) -> torch.Tensor:
    """Sinusoidal embedding of a time scalar in ``[0, 1]`` → ``(B, dim)``."""
    t = t.reshape(-1).float()
    half = dim // 2
    freqs = torch.exp(
        -math.log(10000.0) * torch.arange(half, device=t.device, dtype=torch.float32) / max(half, 1)
    )
    args = t.unsqueeze(1) * freqs.unsqueeze(0) * 1000.0  # scale so [0,1] spreads
    emb = torch.cat([torch.sin(args), torch.cos(args)], dim=-1)
    if emb.size(1) < dim:  # odd dim: pad one zero column
        emb = torch.cat([emb, torch.zeros(emb.size(0), dim - emb.size(1), device=t.device)], dim=-1)
    return emb


# ---------------- config + network ----------------


@dataclass
class FlowConfig:
    latent_dim: int = 48
    cond_dim: int = 128
    hidden: int = 128
    n_layers: int = 3
    time_dim: int = 32

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, d: Dict) -> "FlowConfig":
        fields = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in fields})


class FlowMLP(nn.Module):
    """Velocity field ``v_theta(z_t, t, c)``. Small SiLU MLP."""

    def __init__(self, cfg: FlowConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.time_dim = cfg.time_dim
        in_dim = cfg.latent_dim + cfg.time_dim + cfg.cond_dim
        layers = []
        d = in_dim
        for _ in range(max(cfg.n_layers - 1, 1)):
            layers += [nn.Linear(d, cfg.hidden), nn.SiLU()]
            d = cfg.hidden
        layers += [nn.Linear(d, cfg.latent_dim)]
        self.net = nn.Sequential(*layers)

    def forward(self, z_t: torch.Tensor, t: torch.Tensor, c: torch.Tensor) -> torch.Tensor:
        te = time_embedding(t, self.time_dim)  # (B, time_dim)
        if te.size(0) == 1 and z_t.size(0) > 1:  # scalar t broadcast to batch
            te = te.expand(z_t.size(0), -1)
        h = torch.cat([z_t, te, c], dim=-1)
        return self.net(h)
