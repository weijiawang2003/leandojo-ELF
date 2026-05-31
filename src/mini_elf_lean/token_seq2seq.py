"""Mini-ELF v14 — token-level seq2seq training + decode.

This module is the **token-level twin** of :mod:`mini_elf_lean.ar_train`.
It reuses the existing :class:`mini_elf_lean.ar_model.Seq2Seq`
architecture and the per-batch / per-step helpers from
:mod:`mini_elf_lean.ar_train` (which are vocab-duck-typed), but
instantiates the model over a :class:`TokenVocab` built with the
:mod:`tactic_tokenizer` rather than the char-level
:class:`mini_elf_lean.ar_model.Vocab`. The training loop, beam decode,
val-report and artefact-saving paths are *line-for-line equivalent*
to the v8 char path so we can run a fair char-vs-token comparison.

What the token-level model gives us that the char-level model cannot:

  * **Truncation-class failures are impossible by construction.** A
    token-level decoder cannot emit ``refintro`` (which would require
    `refine` and `intro` to fuse into one IDENT token at train time —
    they never do), and it cannot emit ``rcases h wi`` (where ``wi``
    is an OOV identifier — train tactics use ``with``, a closed
    keyword).
  * **Numeric literals are one-per-token.** ``exact h 13`` requires
    three tokens (``exact``, `` ``, ``h``, `` ``, ``13``); the model
    either emits ``13`` whole or substitutes an UNK / different number
    — never ``1`` mid-decode.

Honest scope:

  * Pure model-side change. No new data, no ``state_after``, no
    manual oracle, no v10 leakage.
  * v13 corrected metrics remain the apples-to-apples baseline.
  * Whether token-level decoding actually moves pass@k is an
    empirical question — the docs report the answer either way.
"""

from __future__ import annotations

import copy
import json
import logging
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Lazy torch import so this module is importable without torch.
try:  # pragma: no cover - exercised by import
    import torch
    import torch.nn as nn

    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch = None  # type: ignore
    nn = None  # type: ignore
    _TORCH_AVAILABLE = False

from .baselines import Example
from .token_seq2seq_dataset import TokenVocab, build_input_text

# Reuse the duck-typed helpers from ar_train (they only call the vocab
# through .encode_source / .encode_target / .pad_id / etc, all of which
# TokenVocab provides identically).
if _TORCH_AVAILABLE:
    from .ar_decode import beam_search, greedy_decode
    from .ar_model import Seq2Seq, Seq2SeqConfig, count_parameters
    from .ar_train import (
        _make_batch as _ar_make_batch,
        _val_loss as _ar_val_loss,
        _greedy_exact as _ar_greedy_exact,
        offline_val_report as _ar_offline_val_report,
        _truncation_report as _ar_truncation_report,
    )


TOKEN_SEQ2SEQ_SOURCE = "token_seq2seq"


# --------------------------------------------------------------------------- #
# Config / artefact dataclasses
# --------------------------------------------------------------------------- #


@dataclass
class TokenTrainConfig:
    """Hyperparameters for v14 token-level training. Mirrors
    :class:`mini_elf_lean.ar_train.TrainConfig` so char vs token uses
    identical capacity (modulo vocab size)."""

    epochs: int = 40
    batch_size: int = 32
    lr: float = 3e-3
    embedding_dim: int = 96  # bumped slightly from char (64) — vocab is ~3x
    hidden_dim: int = 128
    num_layers: int = 1
    bidirectional_encoder: bool = True
    attention_dim: int = 64
    dropout: float = 0.1
    max_input_len: int = 160  # in tokens, not chars
    max_output_len: int = 80
    seed: int = 0
    grad_clip: float = 1.0
    weight_decay: float = 0.0
    beam_width: int = 10
    length_penalty: float = 0.7

    def to_jsonable(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TokenTrainArtifacts:
    model: "Seq2Seq"
    vocab: TokenVocab
    config: "Seq2SeqConfig"
    train_log: List[Dict[str, Any]]
    val_metrics: Dict[str, Any]
    val_predictions: List[Dict[str, Any]]
    summary: Dict[str, Any]
    best_state: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Train loop (mirrors ar_train.train but accepts a pre-built vocab)
# --------------------------------------------------------------------------- #


def train_token(
    train_examples: Sequence[Example],
    val_examples: Sequence[Example],
    vocab: TokenVocab,
    cfg: TokenTrainConfig,
    *,
    device: str = "cpu",
    log_fn=None,
) -> TokenTrainArtifacts:
    """Train the token-level seq2seq. Selects the best checkpoint on
    ``val_greedy_exact_top1`` (ties broken by lower val loss). When
    ``val_examples`` is empty (per-family LOFO sometimes is), checkpoint
    selection falls back to last-epoch."""
    if not _TORCH_AVAILABLE:  # pragma: no cover
        raise RuntimeError("PyTorch required for token-level training")

    torch.manual_seed(cfg.seed)
    rng = random.Random(cfg.seed)

    model_config = Seq2SeqConfig(
        vocab_size=len(vocab),
        embedding_dim=cfg.embedding_dim,
        hidden_dim=cfg.hidden_dim,
        num_layers=cfg.num_layers,
        bidirectional_encoder=cfg.bidirectional_encoder,
        attention_dim=cfg.attention_dim,
        dropout=cfg.dropout,
        max_input_len=cfg.max_input_len,
        max_output_len=cfg.max_output_len,
        pad_id=vocab.pad_id,
        bos_id=vocab.bos_id,
        eos_id=vocab.eos_id,
    )
    model = Seq2Seq(model_config).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=cfg.lr,
                                 weight_decay=cfg.weight_decay)
    criterion = nn.CrossEntropyLoss(ignore_index=vocab.pad_id)

    indices = list(range(len(train_examples)))
    train_log: List[Dict[str, Any]] = []
    best_key: Tuple[float, float] = (-1.0, float("inf"))
    best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    best_epoch = -1

    # Mirror the same TrainConfig-style attribute pack that the
    # duck-typed helpers expect (they read max_input_len / max_output_len
    # / batch_size / beam_width / length_penalty).
    helper_cfg = _HelperCfg(
        batch_size=cfg.batch_size,
        max_input_len=cfg.max_input_len,
        max_output_len=cfg.max_output_len,
        beam_width=cfg.beam_width,
        length_penalty=cfg.length_penalty,
    )

    for epoch in range(cfg.epochs):
        model.train()
        rng.shuffle(indices)
        total_loss = 0.0
        n_tokens = 0
        correct_tokens = 0
        for start in range(0, len(indices), cfg.batch_size):
            batch_idx = indices[start : start + cfg.batch_size]
            batch = [train_examples[i] for i in batch_idx]
            src, src_len, tgt_in, tgt_out = _ar_make_batch(
                batch, vocab, cfg.max_input_len, cfg.max_output_len, device,
            )
            logits = model(src, src_len, tgt_in)
            loss = criterion(logits.reshape(-1, logits.size(-1)),
                             tgt_out.reshape(-1))
            optimizer.zero_grad()
            loss.backward()
            if cfg.grad_clip:
                nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
            optimizer.step()

            mask = tgt_out != vocab.pad_id
            n_tok = int(mask.sum().item())
            total_loss += float(loss.item()) * n_tok
            n_tokens += n_tok
            preds = logits.argmax(dim=-1)
            correct_tokens += int(((preds == tgt_out) & mask).sum().item())

        train_loss = total_loss / max(n_tokens, 1)
        train_tok_acc = correct_tokens / max(n_tokens, 1)
        val_loss = (_ar_val_loss(model, val_examples, vocab, helper_cfg, device)
                    if val_examples else 0.0)
        val_exact = (_ar_greedy_exact(model, val_examples, vocab, helper_cfg)
                     if val_examples else 0.0)

        rec = {
            "epoch": epoch,
            "train_loss": round(train_loss, 5),
            "train_token_acc": round(train_tok_acc, 5),
            "val_loss": round(val_loss, 5),
            "val_greedy_exact_top1": round(val_exact, 5),
        }
        train_log.append(rec)
        if log_fn is not None:
            log_fn(rec)

        if val_examples:
            key = (val_exact, -val_loss)
            if key > best_key:
                best_key = key
                best_state = copy.deepcopy({k: v.detach().clone()
                                            for k, v in model.state_dict().items()})
                best_epoch = epoch
        else:
            # No val set → keep latest. Documented in val_metrics.selected_by.
            best_state = copy.deepcopy({k: v.detach().clone()
                                        for k, v in model.state_dict().items()})
            best_epoch = epoch

    model.load_state_dict(best_state)
    model.eval()

    if val_examples:
        val_metrics, val_preds = _ar_offline_val_report(model, val_examples,
                                                        vocab, helper_cfg)
        val_metrics["selected_by"] = ("val_greedy_exact_top1 "
                                      "(tie: lower val_loss)")
    else:
        val_metrics = {"n_examples": 0, "selected_by": "last_epoch (no val set)",
                       "uses_state_after": False}
        val_preds = []
    val_metrics["best_epoch"] = best_epoch

    summary = {
        "n_train_examples": len(train_examples),
        "n_val_examples": len(val_examples),
        "n_train_theorems": len({e.theorem_name for e in train_examples}),
        "n_val_theorems": len({e.theorem_name for e in val_examples}),
        "vocab_size": len(vocab),
        "n_parameters": count_parameters(model),
        "best_epoch": best_epoch,
        "truncation": _ar_truncation_report(
            list(train_examples) + list(val_examples), vocab,
            cfg.max_input_len, cfg.max_output_len,
        ),
        "uses_state_after": False,
        "source": TOKEN_SEQ2SEQ_SOURCE,
    }

    return TokenTrainArtifacts(
        model=model, vocab=vocab, config=model_config,
        train_log=train_log, val_metrics=val_metrics,
        val_predictions=val_preds, summary=summary, best_state=best_state,
    )


@dataclass
class _HelperCfg:
    """Tiny shim exposing just the fields the ar_train helpers read."""
    batch_size: int
    max_input_len: int
    max_output_len: int
    beam_width: int
    length_penalty: float


# --------------------------------------------------------------------------- #
# Save / load
# --------------------------------------------------------------------------- #


def save_token_artifacts(out_dir: Path, art: TokenTrainArtifacts,
                         cfg: TokenTrainConfig,
                         extra: Optional[Dict[str, Any]] = None) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    art.config.save(out_dir / "config.json")
    art.vocab.save(out_dir / "vocab.json")
    torch.save(art.best_state, out_dir / "model.pt")
    with (out_dir / "train_log.jsonl").open("w", encoding="utf-8") as f:
        for r in art.train_log:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out_dir / "val_metrics.json").write_text(
        json.dumps(art.val_metrics, indent=2), encoding="utf-8")
    with (out_dir / "val_predictions.jsonl").open("w", encoding="utf-8") as f:
        for r in art.val_predictions:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    full = {"summary": art.summary, "train_config": cfg.to_jsonable()}
    if extra:
        full["extra"] = extra
    (out_dir / "summary.json").write_text(
        json.dumps(full, indent=2, ensure_ascii=False), encoding="utf-8")


def load_token_model(model_dir: Path) -> Tuple["Seq2Seq", TokenVocab,
                                               "Seq2SeqConfig"]:
    """Load a saved token-level seq2seq for inference."""
    if not _TORCH_AVAILABLE:  # pragma: no cover
        raise RuntimeError("PyTorch required to load token-level model")
    md = Path(model_dir)
    vocab = TokenVocab.load(md / "vocab.json")
    cfg = Seq2SeqConfig.load(md / "config.json")
    model = Seq2Seq(cfg)
    state = torch.load(md / "model.pt", map_location="cpu")
    model.load_state_dict(state)
    model.eval()
    return model, vocab, cfg


# --------------------------------------------------------------------------- #
# Inference
# --------------------------------------------------------------------------- #


def predict_beams(
    model: "Seq2Seq", vocab: TokenVocab, cfg: "Seq2SeqConfig",
    theorem_statement: str, state_before: str,
    *, beam_width: int = 10, length_penalty: float = 0.7,
) -> List[Tuple[str, float]]:
    """Return up to ``beam_width`` (tactic_string, score) pairs from
    the token-level beam search. Decoded strings are the literal
    concatenation of the model's emitted tokens — already a tactic
    string thanks to the tokenizer's lossless round-trip property."""
    text = build_input_text(theorem_statement, state_before)
    src_ids = vocab.encode_source(text)[: cfg.max_input_len]
    beams = beam_search(
        model, src_ids, vocab,
        beam_width=beam_width, max_len=cfg.max_output_len,
        num_return=beam_width, length_penalty=length_penalty,
    )
    return beams


__all__ = [
    "TOKEN_SEQ2SEQ_SOURCE",
    "TokenTrainConfig",
    "TokenTrainArtifacts",
    "train_token",
    "save_token_artifacts",
    "load_token_model",
    "predict_beams",
]
