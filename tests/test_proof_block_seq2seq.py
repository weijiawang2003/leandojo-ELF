"""Tests for :mod:`mini_elf_lean.proof_block_seq2seq`.

Torch is required for the model load/predict path; the regime-loader and the
``available()`` gate are torch-free and exercised separately.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_load_proof_block_regime_torch_free(tmp_path):
    """``load_proof_block_regime`` itself does not need torch."""
    from mini_elf_lean.proof_block_seq2seq import load_proof_block_regime
    d = tmp_path / "regime"
    d.mkdir()
    (d / "train.jsonl").write_text(json.dumps({
        "theorem_name": "t1",
        "theorem_statement": "stmt",
        "state_before": "⊢ goal",
        "tactic": "exact h",
        "split": "train",
    }) + "\n", encoding="utf-8")
    (d / "val.jsonl").write_text(json.dumps({
        "theorem_name": "t2",
        "theorem_statement": "stmt2",
        "state_before": "⊢ goal2",
        "tactic": "rfl",
        "split": "val",
    }) + "\n", encoding="utf-8")
    train, val, test = load_proof_block_regime(d)
    assert [e.theorem_name for e in train] == ["t1"]
    assert [e.theorem_name for e in val]   == ["t2"]
    assert test == []


def test_proof_blocks_to_examples_no_state_after():
    """The shim drops any state_after field — never plumbs it to torch."""
    from mini_elf_lean.proof_block_seq2seq import proof_blocks_to_examples
    rows = [{
        "theorem_name": "t",
        "theorem_statement": "stmt",
        "state_before": "⊢ goal",
        "tactic": "exact h",
        "state_after": "<<should be ignored>>",
        "split": "train",
    }]
    exs = proof_blocks_to_examples(rows)
    assert len(exs) == 1
    # The dataclass has no state_after field; assert that:
    for fname in exs[0].__dataclass_fields__:
        assert not fname.startswith("state_after"), fname


def test_proposer_unavailable_when_no_model(tmp_path):
    """No saved model => ``available()`` is False, ``propose`` returns []."""
    from mini_elf_lean.proof_block_seq2seq import ProofBlockSeq2SeqProposer
    prop = ProofBlockSeq2SeqProposer(tmp_path / "nope")
    assert prop.available() is False
    out = prop.propose("stmt", "⊢ goal", top_k=5)
    assert out == []


def test_proposer_loads_and_predicts(tmp_path):
    """If torch + a tiny trained model are present, the wrapper round-trips."""
    pytest.importorskip("torch")
    from mini_elf_lean.ar_model import build_input_text, Seq2Seq, Seq2SeqConfig, Vocab
    from mini_elf_lean.proof_block_seq2seq import ProofBlockSeq2SeqProposer
    import torch

    # Smallest possible vocab/model that round-trips
    texts = ["stmt\n⊢ goal", "exact h"]
    vocab = Vocab.build(texts)
    cfg = Seq2SeqConfig(vocab_size=len(vocab), embedding_dim=8, hidden_dim=8,
                        num_layers=1, bidirectional_encoder=True, attention_dim=8,
                        dropout=0.0, max_input_len=80, max_output_len=20,
                        pad_id=vocab.pad_id, bos_id=vocab.bos_id, eos_id=vocab.eos_id)
    model = Seq2Seq(cfg)
    model_dir = tmp_path / "m"
    model_dir.mkdir()
    torch.save(model.state_dict(), model_dir / "model.pt")
    vocab.save(model_dir / "vocab.json")
    # Match what ar_train.save_artifacts would write (a flat dict)
    (model_dir / "config.json").write_text(
        json.dumps({
            "vocab_size": len(vocab),
            "embedding_dim": 8, "hidden_dim": 8, "num_layers": 1,
            "bidirectional_encoder": True, "attention_dim": 8, "dropout": 0.0,
            "max_input_len": 80, "max_output_len": 20,
            "pad_id": vocab.pad_id, "bos_id": vocab.bos_id, "eos_id": vocab.eos_id,
        }), encoding="utf-8")
    prop = ProofBlockSeq2SeqProposer(model_dir, beam_width=3, max_output_len=10)
    assert prop.available()
    out = prop.propose("stmt", "⊢ goal", top_k=3)
    # Model is untrained — content not predictable, but the wrapper must
    # return a list of ProposedCandidate with the correct source.
    assert isinstance(out, list)
    for c in out:
        assert c.source == "proof_block_seq2seq"
        assert isinstance(c.tactic, str)
        assert "beam_rank" in c.metadata
