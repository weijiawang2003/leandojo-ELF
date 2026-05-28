"""Training loop for the character-level AR seq2seq tactic model.

Reads a processed ``next_tactic.jsonl`` (via the same
:class:`~mini_elf_lean.baselines.Example` loader the other baselines use, so it
is structurally impossible to read ``state_after``), trains with teacher forcing
and cross-entropy, selects the checkpoint by **val** greedy exact-match, and
writes the artifact set:

    config.json  vocab.json  model.pt  train_log.jsonl
    val_predictions.jsonl  val_metrics.json

Everything is deterministic given ``--seed``: torch's global seed, a seeded RNG
for epoch shuffling, dropout disabled during evaluation, and CPU-only ops.

Offline metrics only here (greedy exact-match, beam top-k contains-gold, average
generated length, empty-generation rate). Real lean-cli ``pass@k`` lives in
``scripts/evaluate_ar_model.py`` so training never depends on a Lean toolchain.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .ar_decode import beam_search, greedy_decode
from .ar_model import (
    Seq2Seq,
    Seq2SeqConfig,
    Vocab,
    build_input_text,
    count_parameters,
)
from .baselines import Example

import torch
import torch.nn as nn


# ---------------- config ----------------


@dataclass
class TrainConfig:
    epochs: int = 40
    batch_size: int = 32
    lr: float = 3e-3
    embedding_dim: int = 64
    hidden_dim: int = 128
    num_layers: int = 1
    bidirectional_encoder: bool = True
    attention_dim: int = 64
    dropout: float = 0.1
    max_input_len: int = 160
    max_output_len: int = 80
    seed: int = 0
    grad_clip: float = 1.0
    weight_decay: float = 0.0
    # decoding params used for the offline val report + saved into config
    beam_width: int = 5
    length_penalty: float = 0.7


# ---------------- batching ----------------


def build_vocab(train: Sequence[Example]) -> Vocab:
    """Vocab from the **train split only** (source text + target tactics)."""
    texts: List[str] = []
    for e in train:
        texts.append(build_input_text(e.theorem_statement, e.state_before))
        texts.append(e.tactic)
    return Vocab.build(texts)


def _encode_pair(
    e: Example, vocab: Vocab, max_in: int, max_out: int
) -> Tuple[List[int], List[int]]:
    src = vocab.encode_source(build_input_text(e.theorem_statement, e.state_before))[:max_in]
    tgt = vocab.encode_target(e.tactic)[:max_out]
    if tgt[-1] != vocab.eos_id:
        tgt[-1] = vocab.eos_id  # truncation must still terminate the sequence
    return src, tgt


def _make_batch(
    batch: Sequence[Example], vocab: Vocab, max_in: int, max_out: int, device: str
):
    pad = vocab.pad_id
    srcs, tgts = [], []
    for e in batch:
        s, t = _encode_pair(e, vocab, max_in, max_out)
        srcs.append(s)
        tgts.append(t)
    max_s = max(len(s) for s in srcs)
    max_t = max(len(t) for t in tgts)
    src_pad = [s + [pad] * (max_s - len(s)) for s in srcs]
    tgt_pad = [t + [pad] * (max_t - len(t)) for t in tgts]
    src = torch.tensor(src_pad, dtype=torch.long, device=device)
    src_len = torch.tensor([len(s) for s in srcs], dtype=torch.long)
    tgt = torch.tensor(tgt_pad, dtype=torch.long, device=device)
    return src, src_len, tgt[:, :-1], tgt[:, 1:]


def _truncation_report(
    examples: Sequence[Example], vocab: Vocab, max_in: int, max_out: int
) -> Dict[str, int]:
    src_trunc = tgt_trunc = 0
    for e in examples:
        if len(vocab.encode_source(build_input_text(e.theorem_statement, e.state_before))) > max_in:
            src_trunc += 1
        if len(vocab.encode_target(e.tactic)) > max_out:
            tgt_trunc += 1
    return {"source_truncated": src_trunc, "target_truncated": tgt_trunc}


# ---------------- evaluation (offline) ----------------


def _greedy_exact(model: Seq2Seq, examples: Sequence[Example], vocab: Vocab, cfg: TrainConfig) -> float:
    if not examples:
        return 0.0
    correct = 0
    for e in examples:
        src = vocab.encode_source(build_input_text(e.theorem_statement, e.state_before))[: cfg.max_input_len]
        pred = greedy_decode(model, src, vocab, max_len=cfg.max_output_len)
        if pred == e.tactic:
            correct += 1
    return correct / len(examples)


def _val_loss(model: Seq2Seq, examples: Sequence[Example], vocab: Vocab, cfg: TrainConfig, device: str) -> float:
    if not examples:
        return 0.0
    model.eval()
    crit = nn.CrossEntropyLoss(ignore_index=vocab.pad_id, reduction="sum")
    total = 0.0
    n_tokens = 0
    with torch.no_grad():
        for i in range(0, len(examples), cfg.batch_size):
            batch = examples[i : i + cfg.batch_size]
            src, src_len, tgt_in, tgt_out = _make_batch(batch, vocab, cfg.max_input_len, cfg.max_output_len, device)
            logits = model(src, src_len, tgt_in)
            total += float(crit(logits.reshape(-1, logits.size(-1)), tgt_out.reshape(-1)).item())
            n_tokens += int((tgt_out != vocab.pad_id).sum().item())
    return total / max(n_tokens, 1)


def offline_val_report(
    model: Seq2Seq,
    examples: Sequence[Example],
    vocab: Vocab,
    cfg: TrainConfig,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Greedy exact-match, beam top-k contains-gold, avg generated length, empty
    rate, and per-row predictions (greedy + beam). No Lean here."""
    rows: List[Dict[str, Any]] = []
    greedy_correct = 0
    beam_contains_gold = 0
    empty = 0
    gen_lengths: List[int] = []
    novel = 0  # beam top-1 not equal to greedy/gold — informational
    train_tactics: set = set()  # filled by caller if desired; left empty here
    for e in examples:
        src = vocab.encode_source(build_input_text(e.theorem_statement, e.state_before))[: cfg.max_input_len]
        g = greedy_decode(model, src, vocab, max_len=cfg.max_output_len)
        beam = beam_search(
            model, src, vocab, beam_width=cfg.beam_width,
            max_len=cfg.max_output_len, num_return=cfg.beam_width, length_penalty=cfg.length_penalty,
        )
        beam_strs = [s for s, _ in beam]
        if g == e.tactic:
            greedy_correct += 1
        if e.tactic in beam_strs:
            beam_contains_gold += 1
        if not g.strip():
            empty += 1
        gen_lengths.append(len(g))
        rows.append(
            {
                "theorem_name": e.theorem_name,
                "theorem_statement": e.theorem_statement,
                "state_before": e.state_before,
                "ground_truth_tactic": e.tactic,
                "greedy": g,
                "beam": beam_strs,
                "beam_scores": [round(sc, 4) for _, sc in beam],
                "greedy_exact": g == e.tactic,
                "beam_contains_gold": e.tactic in beam_strs,
            }
        )
    n = len(examples)
    metrics = {
        "n_examples": n,
        "greedy_exact_top1": greedy_correct / n if n else 0.0,
        f"beam_top{cfg.beam_width}_contains_gold": beam_contains_gold / n if n else 0.0,
        "avg_generated_length": (sum(gen_lengths) / n) if n else 0.0,
        "empty_generation_rate": empty / n if n else 0.0,
        "uses_state_after": False,
    }
    return metrics, rows


# ---------------- training ----------------


@dataclass
class TrainArtifacts:
    model: Seq2Seq
    vocab: Vocab
    config: Seq2SeqConfig
    train_log: List[Dict[str, Any]]
    val_metrics: Dict[str, Any]
    val_predictions: List[Dict[str, Any]]
    summary: Dict[str, Any]
    best_state: Dict[str, Any] = field(default_factory=dict)


def train(
    train_examples: Sequence[Example],
    val_examples: Sequence[Example],
    cfg: TrainConfig,
    *,
    device: str = "cpu",
    log_fn=None,
) -> TrainArtifacts:
    """Train the seq2seq model. Selects the checkpoint with the best val greedy
    exact-match (ties broken by lower val loss), restores it, and reports."""
    torch.manual_seed(cfg.seed)
    rng = random.Random(cfg.seed)

    vocab = build_vocab(train_examples)
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
    optimizer = torch.optim.Adam(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    criterion = nn.CrossEntropyLoss(ignore_index=vocab.pad_id)

    indices = list(range(len(train_examples)))
    train_log: List[Dict[str, Any]] = []
    best_key: Tuple[float, float] = (-1.0, float("inf"))  # (val_exact, -val_loss-ish)
    best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    best_epoch = -1

    import copy

    for epoch in range(cfg.epochs):
        model.train()
        rng.shuffle(indices)
        total_loss = 0.0
        n_tokens = 0
        correct_tokens = 0
        for start in range(0, len(indices), cfg.batch_size):
            batch_idx = indices[start : start + cfg.batch_size]
            batch = [train_examples[i] for i in batch_idx]
            src, src_len, tgt_in, tgt_out = _make_batch(
                batch, vocab, cfg.max_input_len, cfg.max_output_len, device
            )
            logits = model(src, src_len, tgt_in)  # (B, T, V)
            loss = criterion(logits.reshape(-1, logits.size(-1)), tgt_out.reshape(-1))
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
        val_loss = _val_loss(model, val_examples, vocab, cfg, device)
        val_exact = _greedy_exact(model, val_examples, vocab, cfg)

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

        key = (val_exact, -val_loss)
        if key > best_key:
            best_key = key
            best_state = copy.deepcopy({k: v.detach().clone() for k, v in model.state_dict().items()})
            best_epoch = epoch

    # restore best-on-val checkpoint
    model.load_state_dict(best_state)
    model.eval()

    val_metrics, val_preds = offline_val_report(model, val_examples, vocab, cfg)
    val_metrics["best_epoch"] = best_epoch
    val_metrics["selected_by"] = "val_greedy_exact_top1 (tie: lower val_loss)"

    summary = {
        "n_train_examples": len(train_examples),
        "n_val_examples": len(val_examples),
        "n_train_theorems": len({e.theorem_name for e in train_examples}),
        "n_val_theorems": len({e.theorem_name for e in val_examples}),
        "vocab_size": len(vocab),
        "n_parameters": count_parameters(model),
        "best_epoch": best_epoch,
        "truncation": _truncation_report(
            list(train_examples) + list(val_examples), vocab, cfg.max_input_len, cfg.max_output_len
        ),
        "uses_state_after": False,
    }

    return TrainArtifacts(
        model=model,
        vocab=vocab,
        config=model_config,
        train_log=train_log,
        val_metrics=val_metrics,
        val_predictions=val_preds,
        summary=summary,
        best_state=best_state,
    )


# ---------------- artifact writing ----------------


def save_artifacts(out_dir: Path, art: TrainArtifacts, cfg: TrainConfig, extra_config: Optional[Dict[str, Any]] = None) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # config.json carries both the model architecture and the training recipe.
    full_config: Dict[str, Any] = json.loads(art.config.to_json())
    full_config["training"] = {
        "epochs": cfg.epochs,
        "batch_size": cfg.batch_size,
        "lr": cfg.lr,
        "weight_decay": cfg.weight_decay,
        "grad_clip": cfg.grad_clip,
        "seed": cfg.seed,
        "beam_width": cfg.beam_width,
        "length_penalty": cfg.length_penalty,
        "optimizer": "adam",
        "framework": f"torch-{torch.__version__}",
        "device": "cpu",
    }
    full_config["summary"] = art.summary
    if extra_config:
        full_config.update(extra_config)
    (out_dir / "config.json").write_text(
        json.dumps(full_config, indent=2, sort_keys=True), encoding="utf-8"
    )

    art.vocab.save(out_dir / "vocab.json")
    torch.save(art.model.state_dict(), out_dir / "model.pt")

    with (out_dir / "train_log.jsonl").open("w", encoding="utf-8") as fh:
        for rec in art.train_log:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")

    with (out_dir / "val_predictions.jsonl").open("w", encoding="utf-8") as fh:
        for row in art.val_predictions:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    (out_dir / "val_metrics.json").write_text(
        json.dumps(art.val_metrics, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
