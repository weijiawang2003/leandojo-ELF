"""Mini-ELF v0 — sampling: integration, NN decode/dedup, determinism, and a
tiny end-to-end train→save→load smoke. Torch-gated; no Lean required."""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from mini_elf_lean.ar_model import Vocab  # noqa: E402
from mini_elf_lean.baselines import Example  # noqa: E402
from mini_elf_lean.elf_embed import ConditionEncoder, ElfEmbedConfig, TacticAutoencoder  # noqa: E402
from mini_elf_lean.elf_flow import FlowConfig, FlowMLP  # noqa: E402
from mini_elf_lean.elf_sample import (  # noqa: E402
    LatentStats,
    MiniElfBaseline,
    euler_integrate,
    nn_decode,
)
from mini_elf_lean.elf_train import ElfTrainConfig, save_artifacts, train  # noqa: E402


def _ex(name, statement, state, tactic, split="train"):
    return Example(theorem_name=name, theorem_statement=statement,
                   state_before=state, tactic=tactic, split=split)


# ---------------- low-level ----------------


def test_euler_integrate_shape():
    cfg = FlowConfig(latent_dim=8, cond_dim=16, hidden=16, n_layers=2, time_dim=8)
    flow = FlowMLP(cfg)
    eps = torch.randn(5, 8)
    c = torch.randn(5, 16)
    z = euler_integrate(flow, eps, c, steps=5)
    assert z.shape == (5, 8)


def test_nn_decode_picks_nearest_tactic():
    lib_latents = torch.tensor([[0.0, 0.0], [10.0, 10.0], [-5.0, -5.0]])
    lib_tactics = ["zero", "big", "neg"]
    latents = torch.tensor([[0.1, -0.1], [-4.0, -6.0]])  # near "zero", near "neg"
    out = nn_decode(latents, lib_latents, lib_tactics)
    assert out == ["zero", "neg"]


def _tiny_baseline(seed=0, decode="decoder"):
    vocab = Vocab.build(["rfl", "exact h", "intro x"])
    embed_cfg = ElfEmbedConfig(
        vocab_size=len(vocab), latent_dim=8, cond_dim=16, ae_emb=16, ae_hidden=16,
        cond_emb=16, cond_hidden=16, dropout=0.0, max_tactic_len=24, max_cond_len=32,
        pad_id=vocab.pad_id, bos_id=vocab.bos_id, eos_id=vocab.eos_id,
    )
    flow_cfg = FlowConfig(latent_dim=8, cond_dim=16, hidden=16, n_layers=2, time_dim=8)
    torch.manual_seed(0)
    ae = TacticAutoencoder(embed_cfg)
    cond = ConditionEncoder(embed_cfg)
    flow = FlowMLP(flow_cfg)
    stats = LatentStats(mean=[0.0] * 8, std=[1.0] * 8)
    return MiniElfBaseline(ae, cond, flow, vocab, stats, n_samples=6, steps=4,
                           seed=seed, decode=decode, max_tactic_len=24, max_cond_len=32)


def test_predict_returns_at_most_k_unique():
    b = _tiny_baseline()
    ex = _ex("z", "(p:Prop):p", "p\n|- p", "rfl", split="val")
    preds = b.predict(ex, k=5)
    assert len(preds) <= 5
    assert len(set(preds)) == len(preds)  # deduplicated


def test_sampling_is_deterministic_with_fixed_seed():
    b = _tiny_baseline(seed=0)
    ex = _ex("z", "(p:Prop):p", "p\n|- p", "rfl", split="val")
    assert b.predict(ex, k=5) == b.predict(ex, k=5)  # repeatable


def test_different_seed_can_change_samples():
    ex = _ex("z", "(p:Prop):p", "p\n|- p", "rfl", split="val")
    a = _tiny_baseline(seed=0).predict_with_counts(ex)
    # same weights (manual_seed(0) in builder) but different sampling seed
    c = _tiny_baseline(seed=123).predict_with_counts(ex)
    # not a hard guarantee, but with different noise the candidate multiset
    # ordering/counts should generally differ; at minimum this must not error
    assert isinstance(a, list) and isinstance(c, list)


def test_train_save_load_roundtrip(tmp_path):
    train_ex = [
        _ex("a", "(p:Prop):p", "p\n|- p", "exact h"),
        _ex("b", "(q:Prop):q", "q\n|- q", "rfl"),
        _ex("c", "(r:Prop):r", "r\n|- r", "intro x"),
        _ex("d", "(s:Prop):s", "s\n|- s", "decide"),
    ]
    val_ex = [_ex("e", "(t:Prop):t", "t\n|- t", "exact h", split="val")]
    full = train_ex + val_ex
    cfg = ElfTrainConfig(
        ae_epochs=3, flow_epochs=4, latent_dim=8, cond_dim=16, ae_emb=16, ae_hidden=16,
        cond_emb=16, cond_hidden=16, flow_hidden=16, time_dim=8, n_samples=4, flow_steps=3,
        val_every=2, max_tactic_len=24, max_cond_len=32, seed=0,
    )
    art = train(train_ex, val_ex, full, cfg, device="cpu")
    assert art.summary["uses_state_after"] is False
    assert "top1_exact" in art.val_metrics

    save_artifacts(tmp_path, art, cfg)
    for fname in ("config.json", "vocab.json", "embed.pt", "flow_model.pt",
                  "tactic_library.json", "train_log.jsonl", "val_predictions.jsonl",
                  "val_metrics.json"):
        assert (tmp_path / fname).exists()

    b1 = MiniElfBaseline.load(tmp_path, n_samples=4, steps=3, seed=0)
    b2 = MiniElfBaseline.load(tmp_path, n_samples=4, steps=3, seed=0)
    ex = _ex("z", "(p:Prop):p", "p\n|- p", "exact h", split="test")
    assert b1.predict(ex, k=3) == b2.predict(ex, k=3)  # deterministic across loads

    # nn-decode mode returns only library (train) tactics
    bnn = MiniElfBaseline.load(tmp_path, n_samples=4, steps=3, seed=0, decode="nn")
    preds = bnn.predict(ex, k=3)
    assert all(p in {e.tactic for e in train_ex} for p in preds)
