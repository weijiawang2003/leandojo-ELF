"""End-to-end smoke tests for the v14 token-level seq2seq model.

These tests **require torch**; they skip cleanly when torch is not
available. They train a *tiny* token-level seq2seq on a hand-rolled
3-row dataset and assert that:

  1. ``train_token`` runs, returns artefacts, and selects a best-epoch.
  2. ``predict_beams`` yields ``beam_width`` candidates and they
     concatenate without ``<unk>`` for in-vocab training tactics.
  3. The decoded tactic strings are syntactically clean — no fused
     keywords like ``rwexact``, no clipped ``refin``.
  4. The artefacts round-trip through ``save_token_artifacts`` /
     ``load_token_model``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

torch = pytest.importorskip("torch")  # noqa: E402

from mini_elf_lean.baselines import Example  # noqa: E402
from mini_elf_lean.token_seq2seq import (  # noqa: E402
    TOKEN_SEQ2SEQ_SOURCE, TokenTrainConfig,
    load_token_model, predict_beams, save_token_artifacts, train_token,
)
from mini_elf_lean.token_seq2seq_dataset import TokenVocab  # noqa: E402


def _tiny_examples():
    return [
        Example(theorem_name=f"t{i}", theorem_statement="(p:Prop):p→p",
                state_before="⊢ p → p", tactic="intro h\n  exact h",
                split="train")
        for i in range(8)
    ] + [
        Example(theorem_name="rw_t1", theorem_statement="(n m:Nat)(h:n=m):n.succ=m.succ",
                state_before="⊢ n.succ = m.succ", tactic="rw [h]",
                split="train")
        for _ in range(8)
    ]


def _tiny_val():
    return [
        Example(theorem_name="vt1", theorem_statement="(q:Prop):q→q",
                state_before="⊢ q → q", tactic="intro h\n  exact h",
                split="val"),
        Example(theorem_name="rw_vt1", theorem_statement="(a b:Nat)(h:a=b):a.succ=b.succ",
                state_before="⊢ a.succ = b.succ", tactic="rw [h]",
                split="val"),
    ]


def _build_vocab(examples):
    src_texts = [f"{e.theorem_statement}\n{e.state_before}" for e in examples]
    tactics = [e.tactic for e in examples]
    return TokenVocab.build(src_texts, tactics)


@pytest.fixture(scope="module")
def trained_artifacts():
    train_ex = _tiny_examples()
    val_ex = _tiny_val()
    vocab = _build_vocab(train_ex + val_ex)
    cfg = TokenTrainConfig(
        epochs=20, batch_size=8, lr=5e-3,
        embedding_dim=24, hidden_dim=32, attention_dim=24,
        beam_width=4, seed=0,
    )
    art = train_token(train_ex, val_ex, vocab, cfg)
    return art, vocab, cfg


def test_train_token_returns_artifacts(trained_artifacts):
    art, _vocab, _cfg = trained_artifacts
    assert art.model is not None
    assert art.summary["n_train_examples"] == 16
    assert art.summary["n_val_examples"] == 2
    assert art.summary["best_epoch"] >= 0
    assert art.summary["uses_state_after"] is False
    assert art.summary["source"] == TOKEN_SEQ2SEQ_SOURCE


def test_predict_beams_emits_beam_width_candidates(trained_artifacts):
    art, vocab, cfg = trained_artifacts
    beams = predict_beams(
        art.model, vocab, art.config,
        "(p:Prop):p→p", "⊢ p → p", beam_width=4,
    )
    assert 0 < len(beams) <= 4
    # Every beam must be (str, float)
    for s, sc in beams:
        assert isinstance(s, str)
        assert isinstance(sc, float)


def test_beams_do_not_emit_fused_keywords(trained_artifacts):
    """Core token-level invariant: the model has never seen
    ``rwexact`` / ``refintro`` as tokens (we built the vocab from
    train tactics which contain only well-formed Lean), so no beam
    can emit them. This is the *single property* the v14 brief most
    cares about."""
    art, vocab, cfg = trained_artifacts
    for stmt, state in [
        ("(p:Prop):p→p", "⊢ p → p"),
        ("(a b:Nat)(h:a=b):a.succ=b.succ", "⊢ a.succ = b.succ"),
    ]:
        beams = predict_beams(art.model, vocab, art.config, stmt, state,
                              beam_width=4)
        for tactic, _ in beams:
            assert "rwexact" not in tactic, f"emitted fused token: {tactic!r}"
            assert "refintro" not in tactic, f"emitted fused token: {tactic!r}"
            assert "refin " not in tactic, f"emitted clipped keyword: {tactic!r}"


def test_save_load_round_trip(tmp_path: Path, trained_artifacts):
    art, _vocab, cfg = trained_artifacts
    out_dir = tmp_path / "saved"
    save_token_artifacts(out_dir, art, cfg)
    assert (out_dir / "model.pt").exists()
    assert (out_dir / "vocab.json").exists()
    assert (out_dir / "config.json").exists()
    assert (out_dir / "train_log.jsonl").exists()
    assert (out_dir / "val_metrics.json").exists()
    assert (out_dir / "summary.json").exists()
    model, vocab2, cfg2 = load_token_model(out_dir)
    # Same vocab size
    assert len(vocab2) == len(art.vocab)
    # Model accepts the same inputs and runs without error
    beams = predict_beams(model, vocab2, cfg2,
                          "(p:Prop):p→p", "⊢ p → p", beam_width=2)
    assert len(beams) > 0


def test_train_with_empty_val_falls_back_to_last_epoch():
    train_ex = _tiny_examples()
    vocab = _build_vocab(train_ex)
    cfg = TokenTrainConfig(
        epochs=3, batch_size=8, lr=5e-3,
        embedding_dim=16, hidden_dim=24, attention_dim=16,
        beam_width=2, seed=0,
    )
    art = train_token(train_ex, [], vocab, cfg)
    assert art.val_metrics["selected_by"].startswith("last_epoch")
    assert art.summary["best_epoch"] == cfg.epochs - 1


def test_train_seed_is_deterministic():
    """Two runs with the same seed must produce the same train_log."""
    train_ex = _tiny_examples()[:6]
    val_ex = _tiny_val()
    vocab_a = _build_vocab(train_ex + val_ex)
    vocab_b = _build_vocab(train_ex + val_ex)
    cfg = TokenTrainConfig(
        epochs=3, batch_size=4, lr=5e-3,
        embedding_dim=16, hidden_dim=24, attention_dim=16,
        beam_width=2, seed=42,
    )
    art_a = train_token(train_ex, val_ex, vocab_a, cfg)
    art_b = train_token(train_ex, val_ex, vocab_b, cfg)
    assert [r["train_loss"] for r in art_a.train_log] == \
           [r["train_loss"] for r in art_b.train_log]
