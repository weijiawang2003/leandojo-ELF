"""Mini-ELF v0 — tactic autoencoder + condition encoder + data hygiene.

Torch-gated. Vocab/data invariants and the "never reads state_after" check are
included; the autoencoder is trained only very briefly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from mini_elf_lean.baselines import Example  # noqa: E402
from mini_elf_lean.elf_embed import (  # noqa: E402
    ConditionEncoder,
    ElfEmbedConfig,
    TacticAutoencoder,
    build_vocab_for_elf,
    encode_condition_batch,
    encode_tactic_batch,
)
from mini_elf_lean.elf_train import ElfTrainConfig, train_autoencoder, _ae_recon_exact  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src" / "mini_elf_lean"


def _ex(name, statement, state, tactic, split="train"):
    return Example(theorem_name=name, theorem_statement=statement,
                   state_before=state, tactic=tactic, split=split)


def _cfg(vocab, latent=8):
    return ElfEmbedConfig(
        vocab_size=len(vocab), latent_dim=latent, cond_dim=16, ae_emb=16, ae_hidden=16,
        cond_emb=16, cond_hidden=16, dropout=0.0, max_tactic_len=32, max_cond_len=48,
        pad_id=vocab.pad_id, bos_id=vocab.bos_id, eos_id=vocab.eos_id,
    )


def test_autoencoder_encode_decode_shapes():
    from mini_elf_lean.ar_model import Vocab
    vocab = Vocab.build(["exact h", "rfl"])
    cfg = _cfg(vocab, latent=8)
    ae = TacticAutoencoder(cfg)
    src, src_len = encode_tactic_batch(["exact h", "rfl"], vocab, cfg.max_tactic_len, "cpu")
    z = ae.encode(src, src_len)
    assert z.shape == (2, 8)
    decoded = ae.decode_greedy(z, vocab, max_len=cfg.max_tactic_len)
    assert isinstance(decoded, list) and len(decoded) == 2
    assert all(isinstance(s, str) for s in decoded)


def test_condition_encoder_output_shape():
    from mini_elf_lean.ar_model import Vocab
    vocab = Vocab.build(["(p:Prop):p", "p\n|- p"])
    cfg = _cfg(vocab)
    enc = ConditionEncoder(cfg)
    src, src_len = encode_condition_batch(["(p:Prop):p\np\n|- p", "p\n|- p"], vocab, cfg.max_cond_len, "cpu")
    c = enc(src, src_len)
    assert c.shape == (2, cfg.cond_dim)


def test_build_vocab_uses_train_only():
    train = [_ex("t1", "(p:Prop):p", "p\n|- p", "exact h")]
    v = build_vocab_for_elf(train)
    assert "@" not in v.stoi  # a char only a val tactic would contain
    assert v.unk_id not in v.encode_source("exact h")


def test_autoencoder_can_reconstruct_after_training():
    from mini_elf_lean.ar_model import Vocab
    tactics = ["rfl", "exact h"]
    vocab = Vocab.build(tactics)
    embed_cfg = _cfg(vocab, latent=16)
    cfg = ElfTrainConfig(ae_epochs=60, ae_lr=5e-3, ae_batch=2, max_tactic_len=32, seed=0)
    log = []
    ae = train_autoencoder(tactics, tactics, vocab, embed_cfg, cfg, "cpu", log)
    # loss should drop, and it should reconstruct at least one of two short strings
    ae_losses = [r["ae_loss"] for r in log if r["stage"] == "ae"]
    assert ae_losses[-1] < ae_losses[0]
    assert _ae_recon_exact(ae, tactics, vocab, cfg, "cpu") >= 0.5


def test_frozen_after_training():
    from mini_elf_lean.ar_model import Vocab
    tactics = ["rfl"]
    vocab = Vocab.build(tactics)
    embed_cfg = _cfg(vocab)
    cfg = ElfTrainConfig(ae_epochs=2, ae_batch=1, max_tactic_len=32, seed=0)
    ae = train_autoencoder(tactics, tactics, vocab, embed_cfg, cfg, "cpu", [])
    assert all(not p.requires_grad for p in ae.parameters())


def test_elf_source_never_accesses_state_after():
    forbidden = [".state_after", '["state_after"]', "['state_after']",
                 'get("state_after"', "get('state_after'"]
    for fname in ("elf_embed.py", "elf_flow.py", "elf_train.py", "elf_sample.py"):
        text = (SRC / fname).read_text(encoding="utf-8")
        for pat in forbidden:
            assert pat not in text, f"{fname} accesses state_after via {pat!r}"
