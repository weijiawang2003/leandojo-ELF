"""Mini-ELF v0 — flow-matching math + velocity network. Torch-gated."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from mini_elf_lean.elf_flow import (  # noqa: E402
    FlowConfig,
    FlowMLP,
    interpolate,
    time_embedding,
    velocity_target,
)


def test_interpolate_endpoints():
    torch.manual_seed(0)
    eps = torch.randn(4, 8)
    x = torch.randn(4, 8)
    z0 = interpolate(eps, x, torch.zeros(4, 1))
    z1 = interpolate(eps, x, torch.ones(4, 1))
    assert torch.allclose(z0, eps)
    assert torch.allclose(z1, x)


def test_interpolate_midpoint_shape_and_value():
    eps = torch.zeros(3, 5)
    x = torch.ones(3, 5)
    zt = interpolate(eps, x, torch.full((3, 1), 0.5))
    assert zt.shape == (3, 5)
    assert torch.allclose(zt, torch.full((3, 5), 0.5))


def test_velocity_target_shape_and_value():
    eps = torch.randn(6, 8)
    x = torch.randn(6, 8)
    v = velocity_target(eps, x)
    assert v.shape == x.shape
    assert torch.allclose(v, x - eps)


def test_time_embedding_shape_even_and_odd():
    t = torch.rand(5)
    assert time_embedding(t, 32).shape == (5, 32)
    assert time_embedding(t, 7).shape == (5, 7)  # odd dim padded


def test_flow_mlp_output_shape():
    cfg = FlowConfig(latent_dim=8, cond_dim=16, hidden=16, n_layers=3, time_dim=8)
    flow = FlowMLP(cfg)
    z_t = torch.randn(4, 8)
    t = torch.rand(4, 1)
    c = torch.randn(4, 16)
    out = flow(z_t, t, c)
    assert out.shape == (4, 8)


def test_flow_mlp_scalar_time_broadcasts():
    cfg = FlowConfig(latent_dim=8, cond_dim=16, hidden=16, n_layers=2, time_dim=8)
    flow = FlowMLP(cfg)
    z_t = torch.randn(4, 8)
    c = torch.randn(4, 16)
    out = flow(z_t, torch.zeros(1, 1), c)  # single time value, batch of 4
    assert out.shape == (4, 8)
