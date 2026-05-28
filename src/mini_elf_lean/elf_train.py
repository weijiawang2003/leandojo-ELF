"""Mini-ELF v0 training: (1) a tactic autoencoder defines the latent space,
(2) a conditional rectified-flow model learns to transport noise → tactic latent
given the prompt. The AE is **frozen** after stage 1, so the flow trains against
a fixed latent space (and a fixed standardization).

Splits are honored strictly: AE + flow train on the **train** split only; the
**val** split is used solely to select the flow checkpoint (offline, no Lean);
**test** is never touched here. ``state_after`` is never read.

Deterministic given ``seed`` (global torch seed + a seeded shuffler). CPU-only;
targets well under ~2 minutes on this corpus.
"""

from __future__ import annotations

import copy
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import torch
import torch.nn as nn

from .baselines import Example, oracle_verified_lookup
from .ar_model import build_input_text
from .elf_embed import (
    ConditionEncoder,
    ElfEmbedConfig,
    TacticAutoencoder,
    build_vocab_for_elf,
    encode_condition_batch,
    encode_tactic_batch,
    encode_tactic_targets,
)
from .elf_flow import FlowConfig, FlowMLP, interpolate, velocity_target
from .elf_sample import LatentStats, MiniElfBaseline, standardize


# ---------------- config ----------------


@dataclass
class ElfTrainConfig:
    # autoencoder (stage 1)
    ae_epochs: int = 60
    ae_lr: float = 3e-3
    ae_batch: int = 32
    # flow (stage 2)
    flow_epochs: int = 300
    flow_lr: float = 2e-3
    flow_batch: int = 64
    # architecture
    latent_dim: int = 48
    cond_dim: int = 128
    ae_emb: int = 48
    ae_hidden: int = 96
    cond_emb: int = 48
    cond_hidden: int = 128
    flow_hidden: int = 128
    flow_layers: int = 3
    time_dim: int = 32
    dropout: float = 0.1
    max_tactic_len: int = 80
    max_cond_len: int = 160
    # sampling (val selection + reporting)
    n_samples: int = 32
    flow_steps: int = 10
    val_every: int = 30
    grad_clip: float = 1.0
    seed: int = 0


# ---------------- stage 1: autoencoder ----------------


def _ae_recon_exact(ae: TacticAutoencoder, tactics: Sequence[str], vocab, cfg: ElfTrainConfig, device: str) -> float:
    if not tactics:
        return 0.0
    src, src_len = encode_tactic_batch(tactics, vocab, cfg.max_tactic_len, device)
    with torch.no_grad():
        z = ae.encode(src, src_len)
        decoded = ae.decode_greedy(z, vocab, max_len=cfg.max_tactic_len)
    return sum(1 for d, t in zip(decoded, tactics) if d == t) / len(tactics)


def train_autoencoder(
    train_tactics: List[str], val_tactics: List[str], vocab, embed_cfg: ElfEmbedConfig,
    cfg: ElfTrainConfig, device: str, log: List[Dict[str, Any]],
) -> TacticAutoencoder:
    ae = TacticAutoencoder(embed_cfg).to(device)
    opt = torch.optim.Adam(ae.parameters(), lr=cfg.ae_lr)
    crit = nn.CrossEntropyLoss(ignore_index=vocab.pad_id)
    rng = random.Random(cfg.seed)
    idx = list(range(len(train_tactics)))
    best_recon = -1.0
    best_state = copy.deepcopy(ae.state_dict())
    for epoch in range(cfg.ae_epochs):
        ae.train()
        rng.shuffle(idx)
        total, ntok = 0.0, 0
        for s in range(0, len(idx), cfg.ae_batch):
            batch = [train_tactics[i] for i in idx[s : s + cfg.ae_batch]]
            src, src_len = encode_tactic_batch(batch, vocab, cfg.max_tactic_len, device)
            tgt_in, tgt_out = encode_tactic_targets(batch, vocab, cfg.max_tactic_len, device)
            logits, _ = ae(src, src_len, tgt_in)
            loss = crit(logits.reshape(-1, logits.size(-1)), tgt_out.reshape(-1))
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(ae.parameters(), cfg.grad_clip)
            opt.step()
            mask = tgt_out != vocab.pad_id
            n = int(mask.sum().item())
            total += float(loss.item()) * n
            ntok += n
        recon = _ae_recon_exact(ae, val_tactics, vocab, cfg, device)
        log.append({"stage": "ae", "epoch": epoch, "ae_loss": round(total / max(ntok, 1), 5),
                    "val_recon_exact": round(recon, 5)})
        if recon > best_recon:
            best_recon = recon
            best_state = copy.deepcopy(ae.state_dict())
    ae.load_state_dict(best_state)
    ae.eval()
    for p in ae.parameters():  # freeze: the latent space is now fixed
        p.requires_grad_(False)
    return ae


# ---------------- latent stats + library ----------------


def compute_latent_stats(
    ae: TacticAutoencoder, tactics: Sequence[str], vocab, cfg: ElfTrainConfig, device: str
) -> Tuple[LatentStats, torch.Tensor]:
    src, src_len = encode_tactic_batch(list(tactics), vocab, cfg.max_tactic_len, device)
    with torch.no_grad():
        z = ae.encode(src, src_len)  # (N, L) unstandardized
    mean = z.mean(dim=0)
    std = z.std(dim=0).clamp_min(1e-3)
    stats = LatentStats(mean=mean.tolist(), std=std.tolist())
    return stats, z


def build_library(
    ae: TacticAutoencoder, train: Sequence[Example], vocab, cfg: ElfTrainConfig, device: str
) -> Tuple[List[str], torch.Tensor]:
    """Unique train tactics → mean (unstandardized) latent. Used for NN decode
    and novelty/diversity references."""
    uniq = sorted({e.tactic for e in train})
    src, src_len = encode_tactic_batch(uniq, vocab, cfg.max_tactic_len, device)
    with torch.no_grad():
        z = ae.encode(src, src_len)
    return uniq, z


# ---------------- stage 2: conditional flow ----------------


def _val_select_metric(baseline: MiniElfBaseline, val: Sequence[Example], oracle, k: int = 5) -> float:
    """Offline (no-Lean) selection signal: fraction of val rows where some top-k
    sampled candidate is in the corpus-verified set for that (theorem, state)."""
    if not val:
        return 0.0
    hit = 0
    for e in val:
        preds = baseline.predict(e, k=k)
        verified = oracle.get((e.theorem_name, e.state_before), frozenset())
        if any(p in verified for p in preds):
            hit += 1
    return hit / len(val)


def train_flow(
    ae: TacticAutoencoder, vocab, embed_cfg: ElfEmbedConfig, flow_cfg: FlowConfig,
    train: Sequence[Example], val: Sequence[Example], full_dataset: Sequence[Example],
    stats: LatentStats, x_unstd: torch.Tensor, library: Tuple[List[str], torch.Tensor],
    cfg: ElfTrainConfig, device: str, log: List[Dict[str, Any]], log_fn=None,
) -> Tuple[ConditionEncoder, FlowMLP, int]:
    cond_encoder = ConditionEncoder(embed_cfg).to(device)
    flow = FlowMLP(flow_cfg).to(device)
    opt = torch.optim.Adam(list(cond_encoder.parameters()) + list(flow.parameters()), lr=cfg.flow_lr)

    mean, std = stats.tensors(device)
    x_std = standardize(x_unstd, mean, std)  # (N, L) fixed targets

    # Precompute per-row condition tensors (AE/flow inputs that never change).
    texts = [build_input_text(e.theorem_statement, e.state_before) for e in train]
    oracle = oracle_verified_lookup(full_dataset)

    rng = random.Random(cfg.seed + 1)
    idx = list(range(len(train)))
    best_metric = -1.0
    best_state = (copy.deepcopy(cond_encoder.state_dict()), copy.deepcopy(flow.state_dict()))
    best_epoch = -1

    for epoch in range(cfg.flow_epochs):
        cond_encoder.train()
        flow.train()
        rng.shuffle(idx)
        total = 0.0
        for s in range(0, len(idx), cfg.flow_batch):
            bidx = idx[s : s + cfg.flow_batch]
            batch_texts = [texts[i] for i in bidx]
            src, src_len = encode_condition_batch(batch_texts, vocab, cfg.max_cond_len, device)
            c = cond_encoder(src, src_len)  # (B, cond)
            x = x_std[bidx]  # (B, L)
            eps = torch.randn_like(x)
            t = torch.rand(x.size(0), 1, device=device)
            z_t = interpolate(eps, x, t)
            v_target = velocity_target(eps, x)
            v = flow(z_t, t, c)
            loss = nn.functional.mse_loss(v, v_target)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(list(cond_encoder.parameters()) + list(flow.parameters()), cfg.grad_clip)
            opt.step()
            total += float(loss.item()) * len(bidx)
        flow_loss = total / max(len(idx), 1)

        rec: Dict[str, Any] = {"stage": "flow", "epoch": epoch, "flow_loss": round(flow_loss, 6)}
        is_last = epoch == cfg.flow_epochs - 1
        if val and (epoch % cfg.val_every == 0 or is_last):
            sampler = MiniElfBaseline(
                ae, cond_encoder, flow, vocab, stats,
                n_samples=cfg.n_samples, steps=cfg.flow_steps, seed=cfg.seed, decode="decoder",
                library_latents=library[1], library_tactics=library[0],
                max_tactic_len=cfg.max_tactic_len, max_cond_len=cfg.max_cond_len, device=device,
            )
            metric = _val_select_metric(sampler, val, oracle)
            rec["val_any_verified_top5"] = round(metric, 5)
            if metric > best_metric:
                best_metric = metric
                best_state = (copy.deepcopy(cond_encoder.state_dict()), copy.deepcopy(flow.state_dict()))
                best_epoch = epoch
        log.append(rec)
        if log_fn is not None:
            log_fn(rec)

    cond_encoder.load_state_dict(best_state[0])
    flow.load_state_dict(best_state[1])
    cond_encoder.eval()
    flow.eval()
    return cond_encoder, flow, best_epoch


# ---------------- offline val report ----------------


def offline_val_report(
    baseline: MiniElfBaseline, val: Sequence[Example], full_dataset: Sequence[Example], k: int = 5
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    oracle = oracle_verified_lookup(full_dataset)
    rows: List[Dict[str, Any]] = []
    top1_exact = top5_any = empty = 0
    gen_lengths: List[int] = []
    uniq_counts: List[int] = []
    for e in val:
        ranked = baseline.predict_with_counts(e)
        preds = [t for t, _ in ranked]
        uniq_counts.append(len(set(preds)))
        top1 = preds[0] if preds else ""
        gen_lengths.append(len(top1))
        if not top1.strip():
            empty += 1
        if top1 == e.tactic:
            top1_exact += 1
        verified = oracle.get((e.theorem_name, e.state_before), frozenset())
        if any(p in verified for p in preds[:k]):
            top5_any += 1
        rows.append({
            "theorem_name": e.theorem_name, "theorem_statement": e.theorem_statement,
            "state_before": e.state_before, "ground_truth_tactic": e.tactic,
            "predictions": preds[:k], "sample_counts": [c for _, c in ranked[:k]],
            "n_unique_candidates": len(set(preds)), "top1_exact": top1 == e.tactic,
        })
    n = len(val)
    metrics = {
        "n_examples": n,
        "top1_exact": top1_exact / n if n else 0.0,
        f"top{k}_any_verified": top5_any / n if n else 0.0,
        "avg_generated_length": (sum(gen_lengths) / n) if n else 0.0,
        "empty_generation_rate": empty / n if n else 0.0,
        "avg_unique_candidates": (sum(uniq_counts) / n) if n else 0.0,
        "uses_state_after": False,
    }
    return metrics, rows


# ---------------- top-level train + save ----------------


@dataclass
class ElfArtifacts:
    ae: TacticAutoencoder
    cond_encoder: ConditionEncoder
    flow: FlowMLP
    vocab: Any
    stats: LatentStats
    embed_cfg: ElfEmbedConfig
    flow_cfg: FlowConfig
    library: Tuple[List[str], torch.Tensor]
    train_log: List[Dict[str, Any]]
    val_metrics: Dict[str, Any]
    val_predictions: List[Dict[str, Any]]
    summary: Dict[str, Any]


def train(
    train_examples: Sequence[Example], val_examples: Sequence[Example],
    full_dataset: Sequence[Example], cfg: ElfTrainConfig, *, device: str = "cpu", log_fn=None,
) -> ElfArtifacts:
    torch.manual_seed(cfg.seed)
    vocab = build_vocab_for_elf(train_examples)
    embed_cfg = ElfEmbedConfig(
        vocab_size=len(vocab), latent_dim=cfg.latent_dim, cond_dim=cfg.cond_dim,
        ae_emb=cfg.ae_emb, ae_hidden=cfg.ae_hidden, cond_emb=cfg.cond_emb,
        cond_hidden=cfg.cond_hidden, dropout=cfg.dropout,
        max_tactic_len=cfg.max_tactic_len, max_cond_len=cfg.max_cond_len,
        pad_id=vocab.pad_id, bos_id=vocab.bos_id, eos_id=vocab.eos_id,
    )
    flow_cfg = FlowConfig(
        latent_dim=cfg.latent_dim, cond_dim=cfg.cond_dim, hidden=cfg.flow_hidden,
        n_layers=cfg.flow_layers, time_dim=cfg.time_dim,
    )
    log: List[Dict[str, Any]] = []

    train_tactics = [e.tactic for e in train_examples]
    val_tactics = [e.tactic for e in val_examples]
    ae = train_autoencoder(train_tactics, val_tactics, vocab, embed_cfg, cfg, device, log)
    ae_recon = _ae_recon_exact(ae, val_tactics, vocab, cfg, device)

    stats, _ = compute_latent_stats(ae, train_tactics, vocab, cfg, device)
    # per-row tactic latents (unstandardized) line up with train_examples order
    src, src_len = encode_tactic_batch(train_tactics, vocab, cfg.max_tactic_len, device)
    with torch.no_grad():
        x_unstd = ae.encode(src, src_len)
    library = build_library(ae, train_examples, vocab, cfg, device)

    cond_encoder, flow, best_epoch = train_flow(
        ae, vocab, embed_cfg, flow_cfg, train_examples, val_examples, full_dataset,
        stats, x_unstd, library, cfg, device, log, log_fn=log_fn,
    )

    final = MiniElfBaseline(
        ae, cond_encoder, flow, vocab, stats,
        n_samples=cfg.n_samples, steps=cfg.flow_steps, seed=cfg.seed, decode="decoder",
        library_latents=library[1], library_tactics=library[0],
        max_tactic_len=cfg.max_tactic_len, max_cond_len=cfg.max_cond_len, device=device,
    )
    val_metrics, val_preds = offline_val_report(final, val_examples, full_dataset)
    val_metrics["ae_val_recon_exact"] = round(ae_recon, 5)
    val_metrics["flow_best_epoch"] = best_epoch

    n_params = sum(p.numel() for m in (ae, cond_encoder, flow) for p in m.parameters())
    summary = {
        "n_train_examples": len(train_examples),
        "n_val_examples": len(val_examples),
        "n_train_theorems": len({e.theorem_name for e in train_examples}),
        "vocab_size": len(vocab),
        "latent_dim": cfg.latent_dim,
        "cond_dim": cfg.cond_dim,
        "n_parameters_total": int(n_params),
        "ae_params": int(sum(p.numel() for p in ae.parameters())),
        "flow_params": int(sum(p.numel() for p in flow.parameters())),
        "cond_params": int(sum(p.numel() for p in cond_encoder.parameters())),
        "ae_val_recon_exact": round(ae_recon, 5),
        "flow_best_epoch": best_epoch,
        "uses_state_after": False,
    }

    return ElfArtifacts(
        ae=ae, cond_encoder=cond_encoder, flow=flow, vocab=vocab, stats=stats,
        embed_cfg=embed_cfg, flow_cfg=flow_cfg, library=library,
        train_log=log, val_metrics=val_metrics, val_predictions=val_preds, summary=summary,
    )


def save_artifacts(out_dir: Path, art: ElfArtifacts, cfg: ElfTrainConfig, extra: Optional[Dict[str, Any]] = None) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    config: Dict[str, Any] = {
        "model": "mini_elf_v0",
        "approach": "tactic-autoencoder latent + conditional rectified-flow (Option A)",
        "embed": json.loads(art.embed_cfg.to_json()),
        "flow": json.loads(art.flow_cfg.to_json()),
        "latent_mean": art.stats.mean,
        "latent_std": art.stats.std,
        "training": {
            "ae_epochs": cfg.ae_epochs, "ae_lr": cfg.ae_lr, "ae_batch": cfg.ae_batch,
            "flow_epochs": cfg.flow_epochs, "flow_lr": cfg.flow_lr, "flow_batch": cfg.flow_batch,
            "flow_steps": cfg.flow_steps, "n_samples": cfg.n_samples, "seed": cfg.seed,
            "optimizer": "adam", "framework": f"torch-{torch.__version__}", "device": "cpu",
        },
        "summary": art.summary,
    }
    if extra:
        config.update(extra)
    (out_dir / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")

    art.vocab.save(out_dir / "vocab.json")
    torch.save({"ae": art.ae.state_dict(), "cond_encoder": art.cond_encoder.state_dict()},
               out_dir / "embed.pt")
    torch.save(art.flow.state_dict(), out_dir / "flow_model.pt")

    tactics, lib_latents = art.library
    (out_dir / "tactic_library.json").write_text(
        json.dumps({"tactics": tactics, "latents": lib_latents.tolist()}, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    with (out_dir / "train_log.jsonl").open("w", encoding="utf-8") as fh:
        for rec in art.train_log:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    with (out_dir / "val_predictions.jsonl").open("w", encoding="utf-8") as fh:
        for row in art.val_predictions:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    (out_dir / "val_metrics.json").write_text(
        json.dumps(art.val_metrics, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
