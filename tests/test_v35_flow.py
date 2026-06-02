"""Mini-ELF v35 — pure-tensor unit tests (no Lean, no training).

Pins the load-bearing math of the ELF-style flow model:

* flow-matching interpolation endpoints on ``(B, T, D)`` with ``t`` ``(B, 1, 1)``;
* the constant target velocity ``v = Z1 − Z0``;
* the **clean-estimate identity** ``ẑ1 = z_t + (1−t)·v == Z1`` when ``v`` is the
  true velocity (this is exactly the CE-anchor reconstruction);
* the **tied nearest-embedding readout round-trip** ``embed → readout → argmax``
  recovers the embedded ids (the bug a plain ``z·Eᵀ`` head would have);
* the CFG memory mask (learned null prepended; ``drop`` masks the real
  condition steps but never the null);
* the velocity-field forward shape;
* the :class:`LatentStats` inverse ``unstandardize(standardize(z)) == z``.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from mini_elf_lean.elf_flow import interpolate, velocity_target  # noqa: E402
from mini_elf_lean.elf_v35_embed import (  # noqa: E402
    ConditionEncoder,
    ElfV35Config,
    LatentStats,
    TokenEmbedding,
    compute_latent_stats,
    padding_mask,
    standardize,
    unstandardize,
)
from mini_elf_lean.elf_v35_flow import ElfV35Model, SeqVelocityField  # noqa: E402


def _cfg(**kw):
    base = dict(vocab_size=24, d_model=8, cond_hidden=8, n_layers=2, n_heads=2,
                ff_dim=16, dropout=0.0, time_dim=8, max_tgt_len=6, max_cond_len=10)
    base.update(kw)
    return ElfV35Config(**base)


# --------------------------------------------------------------------------- #
# flow-matching math on (B, T, D)
# --------------------------------------------------------------------------- #


def test_interpolate_endpoints_seq():
    torch.manual_seed(0)
    B, T, D = 3, 5, 8
    z0 = torch.randn(B, T, D)
    z1 = torch.randn(B, T, D)
    t0 = torch.zeros(B, 1, 1)
    t1 = torch.ones(B, 1, 1)
    assert torch.allclose(interpolate(z0, z1, t0), z0, atol=1e-6)
    assert torch.allclose(interpolate(z0, z1, t1), z1, atol=1e-6)


def test_velocity_target_is_difference():
    torch.manual_seed(1)
    z0 = torch.randn(2, 4, 8)
    z1 = torch.randn(2, 4, 8)
    assert torch.allclose(velocity_target(z0, z1), z1 - z0, atol=1e-7)


def test_clean_estimate_recovers_endpoint():
    """With the TRUE velocity, ẑ1 = z_t + (1−t)·v == Z1 for any t. This is the
    identity the CE anchor relies on."""
    torch.manual_seed(2)
    B, T, D = 4, 5, 8
    z0 = torch.randn(B, T, D)
    z1 = torch.randn(B, T, D)
    v = velocity_target(z0, z1)
    for tv in (0.0, 0.25, 0.5, 0.9, 1.0):
        t = torch.full((B, 1, 1), tv)
        z_t = interpolate(z0, z1, t)
        z1_hat = z_t + (1.0 - t) * v
        assert torch.allclose(z1_hat, z1, atol=1e-5), tv


# --------------------------------------------------------------------------- #
# tied nearest-embedding readout
# --------------------------------------------------------------------------- #


def test_tied_readout_roundtrips_embedded_ids():
    torch.manual_seed(3)
    cfg = _cfg()
    emb = TokenEmbedding(cfg)
    # distinct rows are a.s. guaranteed by the random init; assert it to be safe.
    W = emb.weight.detach()
    assert len({tuple(r.tolist()) for r in W}) == cfg.vocab_size
    ids = torch.randint(0, cfg.vocab_size, (3, 5))
    z = emb.embed(ids)                       # (B, T, D), z == E[ids] exactly
    decoded = emb.readout_ids(z)             # nearest-embedding argmax
    assert torch.equal(decoded, ids)


def test_tied_readout_equals_min_euclidean():
    """argmax of the readout logits == argmin Euclidean distance to a vocab row
    — true for an arbitrary z, not just exact embeddings."""
    torch.manual_seed(4)
    cfg = _cfg()
    emb = TokenEmbedding(cfg)
    z = torch.randn(7, cfg.d_model)
    by_logit = emb.readout_ids(z)
    E = emb.weight.detach()
    dists = torch.cdist(z, E)                # (7, V)
    by_dist = dists.argmin(dim=-1)
    assert torch.equal(by_logit, by_dist)


def test_plain_dot_head_would_not_roundtrip():
    """Documents the bug the −0.5‖E_i‖² term fixes: a plain z·Eᵀ argmax does NOT
    recover the embedded id once embedding norms differ. (Sanity guard — if this
    ever starts passing, the readout has silently become a plain dot product.)"""
    torch.manual_seed(5)
    cfg = _cfg()
    emb = TokenEmbedding(cfg)
    # Scale rows so norms differ a lot — the failure case for a dot-product head.
    with torch.no_grad():
        emb.table.weight.mul_(torch.linspace(0.1, 5.0, cfg.vocab_size).unsqueeze(1))
    ids = torch.randint(0, cfg.vocab_size, (4, 5))
    z = emb.embed(ids)
    plain = (z @ emb.weight.t()).argmax(dim=-1)   # no −0.5‖E_i‖² term
    tied = emb.readout_ids(z)
    assert torch.equal(tied, ids)                  # tied readout still exact
    assert not torch.equal(plain, ids)             # plain dot product is not


# --------------------------------------------------------------------------- #
# condition encoder + CFG memory mask
# --------------------------------------------------------------------------- #


def test_padding_mask_helper():
    ids = torch.tensor([[1, 2, 0, 0], [3, 0, 0, 0]])
    m = padding_mask(ids, pad_id=0)
    assert m.tolist() == [[False, False, True, True], [False, True, True, True]]


def test_condition_encoder_shapes_and_mask():
    torch.manual_seed(6)
    cfg = _cfg()
    enc = ConditionEncoder(cfg)
    cond = torch.tensor([[5, 6, 7, 0, 0], [8, 9, 0, 0, 0]])
    states, pad = enc(cond)
    assert states.shape == (2, 5, cfg.d_model)
    assert pad.tolist() == padding_mask(cond, cfg.pad_id).tolist()


def test_cfg_memory_mask_null_and_drop():
    torch.manual_seed(7)
    cfg = _cfg()
    model = ElfV35Model(cfg)
    cond = torch.tensor([[5, 6, 7, 0, 0], [8, 9, 0, 0, 0]])
    drop = torch.tensor([False, True])
    memory, mem_pad = model.build_memory(cond, drop=drop)
    assert memory.shape == (2, 1 + 5, cfg.d_model)
    # null column (index 0) is always attended.
    assert mem_pad[:, 0].tolist() == [False, False]
    # row 0 (not dropped): condition pad mask preserved.
    assert mem_pad[0, 1:].tolist() == padding_mask(cond[0:1], cfg.pad_id)[0].tolist()
    # row 1 (dropped): every condition step masked → only the null token remains.
    assert mem_pad[1, 1:].all().item() is True
    assert mem_pad[1].sum().item() == 5  # all 5 cond steps masked, null free


# --------------------------------------------------------------------------- #
# velocity field forward
# --------------------------------------------------------------------------- #


def test_velocity_field_forward_shape():
    torch.manual_seed(8)
    cfg = _cfg()
    model = ElfV35Model(cfg).eval()
    B, T, D = 2, cfg.max_tgt_len, cfg.d_model
    z_t = torch.randn(B, T, D)
    t = torch.rand(B)
    cond = torch.tensor([[5, 6, 7, 0, 0], [8, 9, 0, 0, 0]])
    v = model(z_t, t, cond_ids=cond)
    assert v.shape == (B, T, D)
    # self-conditioning input path returns the same shape.
    v2 = model(z_t, t, cond_ids=cond, self_cond=torch.randn(B, T, D))
    assert v2.shape == (B, T, D)


def test_precomputed_memory_matches_built_memory():
    torch.manual_seed(9)
    cfg = _cfg()
    model = ElfV35Model(cfg).eval()
    B, T, D = 2, cfg.max_tgt_len, cfg.d_model
    z_t = torch.randn(B, T, D)
    t = torch.rand(B)
    cond = torch.tensor([[5, 6, 7, 0, 0], [8, 9, 0, 0, 0]])
    with torch.no_grad():
        v_a = model(z_t, t, cond_ids=cond)
        mem, mp = model.build_memory(cond, drop=None)
        v_b = model(z_t, t, memory=mem, memory_pad_mask=mp)
    assert torch.allclose(v_a, v_b, atol=1e-6)


# --------------------------------------------------------------------------- #
# latent stats inverse
# --------------------------------------------------------------------------- #


def test_latent_stats_inverse():
    torch.manual_seed(10)
    cfg = _cfg()
    emb = TokenEmbedding(cfg)
    stats = compute_latent_stats(emb)
    assert len(stats.mean) == cfg.d_model and len(stats.std) == cfg.d_model
    m, s = stats.tensors()
    z = torch.randn(5, 4, cfg.d_model)
    assert torch.allclose(unstandardize(standardize(z, m, s), m, s), z, atol=1e-5)


def test_latent_stats_from_token_subset():
    torch.manual_seed(11)
    cfg = _cfg()
    emb = TokenEmbedding(cfg)
    ids = [4, 4, 5, 6, 6, 6, 7]
    stats = compute_latent_stats(emb, token_ids=ids)
    rows = emb.table(torch.tensor(ids))
    assert torch.allclose(torch.tensor(stats.mean), rows.mean(0), atol=1e-5)
    assert all(sd >= 1e-3 for sd in stats.std)  # floored
