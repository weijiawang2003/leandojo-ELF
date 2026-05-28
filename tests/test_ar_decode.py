"""Decoding + tiny-training tests for the AR seq2seq model.

Torch-gated: skipped cleanly when PyTorch is not installed. The beam-search
dedup test uses a *stub* model (no training, no real network) so it is fast and
exercises only the search logic; one tiny real model is built for a greedy/beam
smoke test, and one very short (5-epoch, 8-dim) training run checks the loop
end-to-end without "training a real model for long".
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from mini_elf_lean.ar_decode import (  # noqa: E402
    ARGenerativeBaseline,
    beam_search,
    greedy_decode,
)
from mini_elf_lean.ar_model import Seq2Seq, Seq2SeqConfig, Vocab  # noqa: E402
from mini_elf_lean.ar_train import TrainConfig, save_artifacts, train  # noqa: E402
from mini_elf_lean.baselines import Example  # noqa: E402


def _ex(name, statement, state, tactic, split="train"):
    return Example(
        theorem_name=name, theorem_statement=statement,
        state_before=state, tactic=tactic, split=split,
    )


def _tiny_model(vocab):
    cfg = Seq2SeqConfig(
        vocab_size=len(vocab), embedding_dim=8, hidden_dim=8, num_layers=1,
        attention_dim=8, dropout=0.0, max_input_len=40, max_output_len=12,
        pad_id=vocab.pad_id, bos_id=vocab.bos_id, eos_id=vocab.eos_id,
    )
    torch.manual_seed(0)
    return Seq2Seq(cfg), cfg


# ---------------- real tiny model: smoke ----------------


def test_greedy_decode_returns_string_and_terminates():
    vocab = Vocab.build(["exact h", "rfl"])
    model, cfg = _tiny_model(vocab)
    src = vocab.encode_source("(p:Prop):p\n|- p")
    out = greedy_decode(model, src, vocab, max_len=cfg.max_output_len)
    assert isinstance(out, str)
    assert len(out) <= cfg.max_output_len  # bounded by max_len


def test_beam_search_returns_unique_ranked_results():
    vocab = Vocab.build(["exact h", "rfl", "intro x"])
    model, cfg = _tiny_model(vocab)
    src = vocab.encode_source("(p:Prop):p\n|- p")
    results = beam_search(model, src, vocab, beam_width=5, max_len=cfg.max_output_len, num_return=5)
    assert len(results) <= 5
    strings = [s for s, _ in results]
    assert len(set(strings)) == len(strings)  # deduplicated
    scores = [sc for _, sc in results]
    assert scores == sorted(scores, reverse=True)  # ranked best-first


# ---------------- stub model: beam dedup logic in isolation ----------------


class _StubModel:
    """Minimal stand-in implementing the interface ``beam_search`` calls.

    Every step puts the top probability mass on EOS and the second on PAD, with
    everything else far lower. Several distinct token *paths* therefore complete
    (``[bos,eos]``, ``[bos,pad,eos]``, …) but all decode to the empty string, so
    a correct dedup collapses them to a single returned result.
    """

    def __init__(self, vocab: Vocab):
        self.vocab = vocab
        self._p = torch.zeros(1)

    def eval(self):
        return self

    def parameters(self):
        return iter([self._p])

    def encode(self, src, src_len):
        b, s = src.size(0), src.size(1)
        enc = torch.zeros(b, s, 4)
        hidden = torch.zeros(1, b, 2)
        mask = src == self.vocab.pad_id
        return enc, hidden, mask

    def decode_step(self, prev, hidden, enc_outputs, src_mask):
        a = prev.size(0)
        v = len(self.vocab)
        logits = torch.full((a, v), -10.0)
        logits[:, self.vocab.eos_id] = 0.0   # most likely -> finishes the beam
        logits[:, self.vocab.pad_id] = -1.0  # second -> a different path, same string
        return logits, hidden, torch.zeros(a, enc_outputs.size(1))


def test_beam_search_dedups_paths_that_render_to_same_string():
    vocab = Vocab.build(["rfl"])
    stub = _StubModel(vocab)
    src = vocab.encode_source("x")
    # beam_width=2 so only EOS and PAD are explored; every completed path then
    # renders to "" and a correct dedup collapses them to a single result.
    results = beam_search(stub, src, vocab, beam_width=2, max_len=8, num_return=5)
    strings = [s for s, _ in results]
    assert len(set(strings)) == len(strings)
    assert strings == [""]  # all paths collapse to the empty tactic


def test_greedy_decode_with_stub_stops_immediately_at_eos():
    vocab = Vocab.build(["rfl"])
    stub = _StubModel(vocab)
    out = greedy_decode(stub, vocab.encode_source("x"), vocab, max_len=8)
    assert out == ""  # argmax is EOS at the first step


# ---------------- short training smoke + adapter round-trip ----------------


def test_short_training_runs_and_loss_decreases(tmp_path):
    # A trivially learnable mapping: each theorem has a distinct one-word tactic.
    train_ex = [
        _ex("a", "(p:Prop):p", "p:Prop\n|- p", "exact h"),
        _ex("b", "(q:Prop):q", "q:Prop\n|- q", "rfl"),
        _ex("c", "(r:Prop):r", "r:Prop\n|- r", "intro x"),
        _ex("d", "(s:Prop):s", "s:Prop\n|- s", "decide"),
    ]
    val_ex = [_ex("e", "(t:Prop):t", "t:Prop\n|- t", "exact h", split="val")]
    cfg = TrainConfig(
        epochs=5, batch_size=4, lr=0.01, embedding_dim=8, hidden_dim=8,
        max_input_len=40, max_output_len=16, beam_width=3, seed=0,
    )
    art = train(train_ex, val_ex, cfg, device="cpu")
    assert len(art.train_log) == 5
    # loss should not increase from first to last epoch on a learnable task
    assert art.train_log[-1]["train_loss"] <= art.train_log[0]["train_loss"]
    assert "greedy_exact_top1" in art.val_metrics
    assert art.val_metrics["uses_state_after"] is False

    # artifacts round-trip through disk + ARGenerativeBaseline.load
    save_artifacts(tmp_path, art, cfg)
    for fname in ("config.json", "vocab.json", "model.pt", "train_log.jsonl",
                  "val_predictions.jsonl", "val_metrics.json"):
        assert (tmp_path / fname).exists()

    baseline = ARGenerativeBaseline.load(tmp_path, beam_width=3)
    preds = baseline.predict(val_ex[0], k=3)
    assert isinstance(preds, list) and len(preds) <= 3
    assert all(isinstance(s, str) for s in preds)


def test_ar_baseline_predict_is_deterministic(tmp_path):
    train_ex = [
        _ex("a", "(p:Prop):p", "p:Prop\n|- p", "exact h"),
        _ex("b", "(q:Prop):q", "q:Prop\n|- q", "rfl"),
    ]
    cfg = TrainConfig(epochs=3, batch_size=2, embedding_dim=8, hidden_dim=8,
                      max_input_len=40, max_output_len=12, beam_width=3, seed=0)
    art = train(train_ex, [], cfg, device="cpu")
    save_artifacts(tmp_path, art, cfg)
    b1 = ARGenerativeBaseline.load(tmp_path, beam_width=3)
    b2 = ARGenerativeBaseline.load(tmp_path, beam_width=3)
    ex = _ex("z", "(p:Prop):p", "p:Prop\n|- p", "exact h", split="test")
    assert b1.predict(ex, k=3) == b2.predict(ex, k=3)
