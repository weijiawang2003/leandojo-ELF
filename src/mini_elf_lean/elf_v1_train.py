"""Mini-ELF v1 training: a *denoising* tactic autoencoder + a conditional
rectified-flow model conditioned on the **structured** prompt encoder.

Two deltas from v0 (:mod:`mini_elf_lean.elf_train`), both aimed at the observed
weaknesses (too many invalid generations; weak top-1):

  * **Denoising / latent-noise AE.** Encoder input characters are randomly
    corrupted (``ae_denoise_prob``) and Gaussian noise is added to the latent
    before decoding (``ae_latent_noise_std``); the target stays the clean tactic.
    This widens the basin of latents that decode to *valid* strings, so off-
    distribution flow samples garble less. Optional scheduled sampling is
    available (``scheduled_sampling`` + ``ae_teacher_forcing_ratio`` floor).
  * **Structured condition encoder**
    (:class:`~mini_elf_lean.elf_structure.StructuredConditionEncoder`): raw-prompt
    bi-GRU **plus** a goal bi-GRU, a goal-shape embedding, and structural numeric
    features.

v0 is untouched (this is a separate module). Splits are honored: AE + flow train
on the train split only; val selects the flow checkpoint offline (no Lean); test
is never touched. ``state_after`` is never read. CPU-only, deterministic given
``seed``.
"""

from __future__ import annotations

import copy
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import torch
import torch.nn as nn

from .ar_model import build_input_text
from .baselines import Example, oracle_verified_lookup
from .elf_embed import (
    ElfEmbedConfig,
    TacticAutoencoder,
    build_vocab_for_elf,
    encode_tactic_batch,
    encode_tactic_targets,
)
from .elf_flow import FlowConfig, FlowMLP, interpolate, velocity_target
from .elf_sample import LatentStats, standardize
from .elf_rerank import RerankExample
from .elf_structure import StructuredConditionEncoder, structured_inputs_from_prompts
from .elf_train import _ae_recon_exact, build_library, compute_latent_stats
from .elf_v1_sample import MiniElfV1Baseline, StructuredCondConfig


# ---------------- config ----------------


@dataclass
class ElfV1TrainConfig:
    # autoencoder (stage 1) + v1 denoising options
    ae_epochs: int = 80
    ae_lr: float = 3e-3
    ae_batch: int = 32
    ae_denoise_prob: float = 0.1       # P(corrupt an input char); target stays clean
    ae_latent_noise_std: float = 0.1   # Gaussian noise added to latent before decode
    scheduled_sampling: bool = False
    ae_teacher_forcing_ratio: float = 1.0  # floor (annealed to) when scheduled_sampling
    # flow (stage 2)
    flow_epochs: int = 400
    flow_lr: float = 2e-3
    flow_batch: int = 64
    # architecture
    latent_dim: int = 64
    cond_dim: int = 128
    ae_emb: int = 48
    ae_hidden: int = 96
    cond_emb: int = 48
    cond_raw_hidden: int = 128
    cond_goal_hidden: int = 48
    cond_shape_dim: int = 8
    flow_hidden: int = 128
    flow_layers: int = 3
    time_dim: int = 32
    dropout: float = 0.1
    max_tactic_len: int = 80
    max_cond_len: int = 160
    max_goal_len: int = 80
    # sampling (val selection + reporting)
    n_samples: int = 64
    flow_steps: int = 10
    val_every: int = 30
    grad_clip: float = 1.0
    seed: int = 0


# ---------------- stage 1: denoising autoencoder ----------------


def _corrupt(src: torch.Tensor, vocab, prob: float, gen: torch.Generator) -> torch.Tensor:
    """Substitute non-pad input characters with a random non-special id with
    probability ``prob`` (denoising-AE input corruption). Targets are untouched."""
    if prob <= 0.0:
        return src
    n_special = max(vocab.eos_id, vocab.bos_id, vocab.pad_id, vocab.unk_id) + 1
    if len(vocab) <= n_special:
        return src
    mask = (torch.rand(src.shape, generator=gen, device=src.device) < prob) & (src != vocab.pad_id)
    rand_ids = torch.randint(n_special, len(vocab), src.shape, generator=gen, device=src.device)
    return torch.where(mask, rand_ids, src)


def train_autoencoder_v1(
    train_tactics: List[str], val_tactics: List[str], vocab, embed_cfg: ElfEmbedConfig,
    cfg: ElfV1TrainConfig, device: str, log: List[Dict[str, Any]],
) -> TacticAutoencoder:
    ae = TacticAutoencoder(embed_cfg).to(device)
    opt = torch.optim.Adam(ae.parameters(), lr=cfg.ae_lr)
    crit = nn.CrossEntropyLoss(ignore_index=vocab.pad_id)
    rng = random.Random(cfg.seed)
    gen = torch.Generator(device=device)
    gen.manual_seed(cfg.seed + 7)
    idx = list(range(len(train_tactics)))
    best_recon = -1.0
    best_state = copy.deepcopy(ae.state_dict())

    for epoch in range(cfg.ae_epochs):
        ae.train()
        if cfg.scheduled_sampling and cfg.ae_epochs > 1:
            frac = epoch / (cfg.ae_epochs - 1)
            tf_ratio = 1.0 - frac * (1.0 - cfg.ae_teacher_forcing_ratio)
        else:
            tf_ratio = 1.0
        rng.shuffle(idx)
        total, ntok = 0.0, 0
        for s in range(0, len(idx), cfg.ae_batch):
            batch = [train_tactics[i] for i in idx[s : s + cfg.ae_batch]]
            src, src_len = encode_tactic_batch(batch, vocab, cfg.max_tactic_len, device)
            tgt_in, tgt_out = encode_tactic_targets(batch, vocab, cfg.max_tactic_len, device)
            src = _corrupt(src, vocab, cfg.ae_denoise_prob, gen)

            z = ae.encode(src, src_len)
            if cfg.ae_latent_noise_std > 0.0:
                z = z + torch.randn(z.shape, generator=gen, device=device) * cfg.ae_latent_noise_std
            hidden = ae.init_hidden(z)
            T = tgt_in.size(1)
            step_logits: List[torch.Tensor] = []
            prev = tgt_in[:, 0]
            for t in range(T):
                logits_t, hidden = ae.decode_step(prev, hidden, z)
                step_logits.append(logits_t)
                if t < T - 1:
                    teacher = tgt_in[:, t + 1]
                    if cfg.scheduled_sampling and tf_ratio < 1.0:
                        use_pred = torch.rand(prev.shape, generator=gen, device=device) > tf_ratio
                        prev = torch.where(use_pred, logits_t.argmax(dim=-1), teacher)
                    else:
                        prev = teacher
            logits = torch.stack(step_logits, dim=1)
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
                    "tf_ratio": round(tf_ratio, 3), "val_recon_exact": round(recon, 5)})
        if recon >= best_recon:
            best_recon = recon
            best_state = copy.deepcopy(ae.state_dict())
    ae.load_state_dict(best_state)
    ae.eval()
    for p in ae.parameters():  # freeze: the latent space is now fixed
        p.requires_grad_(False)
    return ae


# ---------------- stage 2: conditional flow w/ structured encoder ----------------


def _val_select_metric(baseline: MiniElfV1Baseline, val: Sequence[Example], oracle, k: int = 5) -> float:
    if not val:
        return 0.0
    hit = 0
    for e in val:
        preds = baseline.predict(e, k=k)
        verified = oracle.get((e.theorem_name, e.state_before), frozenset())
        if any(p in verified for p in preds):
            hit += 1
    return hit / len(val)


def train_flow_v1(
    ae: TacticAutoencoder, vocab, cond_cfg: StructuredCondConfig, flow_cfg: FlowConfig,
    train: Sequence[Example], val: Sequence[Example], full_dataset: Sequence[Example],
    stats: LatentStats, x_unstd: torch.Tensor, library: Tuple[List[str], torch.Tensor],
    cfg: ElfV1TrainConfig, device: str, log: List[Dict[str, Any]], log_fn=None,
) -> Tuple[StructuredConditionEncoder, FlowMLP, int]:
    cond_encoder = cond_cfg.build_encoder().to(device)
    flow = FlowMLP(flow_cfg).to(device)
    opt = torch.optim.Adam(list(cond_encoder.parameters()) + list(flow.parameters()), lr=cfg.flow_lr)

    mean, std = stats.tensors(device)
    x_std = standardize(x_unstd, mean, std)
    pairs = [(e.theorem_statement, e.state_before) for e in train]
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
            batch_pairs = [pairs[i] for i in bidx]
            inputs = structured_inputs_from_prompts(
                batch_pairs, vocab, cfg.max_cond_len, cfg.max_goal_len, device
            )
            c = cond_encoder(*inputs)
            x = x_std[bidx]
            eps = torch.randn_like(x)
            t = torch.rand(x.size(0), 1, device=device)
            z_t = interpolate(eps, x, t)
            v_target = velocity_target(eps, x)
            v = flow(z_t, t, c)
            loss = nn.functional.mse_loss(v, v_target)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(
                list(cond_encoder.parameters()) + list(flow.parameters()), cfg.grad_clip
            )
            opt.step()
            total += float(loss.item()) * len(bidx)
        flow_loss = total / max(len(idx), 1)

        rec: Dict[str, Any] = {"stage": "flow", "epoch": epoch, "flow_loss": round(flow_loss, 6)}
        is_last = epoch == cfg.flow_epochs - 1
        if val and (epoch % cfg.val_every == 0 or is_last):
            sampler = MiniElfV1Baseline(
                ae, cond_encoder, flow, vocab, stats, cond_cfg=cond_cfg,
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


def offline_val_report_v1(
    baseline: MiniElfV1Baseline, val: Sequence[Example], full_dataset: Sequence[Example], k: int = 5
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    oracle = oracle_verified_lookup(full_dataset)
    rows: List[Dict[str, Any]] = []
    top1_exact = top5_any = empty = 0
    gen_lengths: List[int] = []
    uniq_counts: List[int] = []
    for e in val:
        ranked = baseline.ranked_candidates(e)
        preds = [it["tactic"] for it in ranked]
        uniq_counts.append(baseline.distinct_flow_candidates(e))
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
            "theorem_name": e.theorem_name, "ground_truth_tactic": e.tactic,
            "predictions": preds[:k],
            "sources": [it["source"] for it in ranked[:k]],
            "top1_exact": top1 == e.tactic,
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


# ---------------- reranker self-training data (flow candidates, Lean-labelled) ----------------


def flow_rerank_examples(
    baseline: MiniElfV1Baseline, train_examples: Sequence[Example],
    verify_fn, *, max_per_row: int = 12, family_map: Optional[Dict[str, str]] = None,
) -> List[RerankExample]:
    """Generate flow candidates for each *train* theorem and label them by Lean
    (``verify_fn(theorem_name, theorem_statement, tactic) -> bool``).

    These are the **hard** reranker examples: positives and negatives share the
    flow decoder's token distribution, so token/GRU features alone cannot
    separate them — the model is forced to use the structural features
    (binding, conjunct/disjunct consistency, numeric match). ``baseline`` must be
    a decode-only (no reranker, no witness) generator. No ``state_after``."""
    family_map = family_map or {}
    out: List[RerankExample] = []
    for e in train_examples:
        ranked = baseline.ranked_candidates(e)
        for it in ranked[:max_per_row]:
            tac = it["tactic"]
            ok = bool(verify_fn(e.theorem_name, e.theorem_statement, tac))
            out.append(RerankExample(
                theorem_statement=e.theorem_statement, state_before=e.state_before,
                candidate=tac, label=int(ok), theorem_name=e.theorem_name,
                family=family_map.get(e.theorem_name),
            ))
    return out


# ---------------- top-level train + save ----------------


@dataclass
class ElfV1Artifacts:
    ae: TacticAutoencoder
    cond_encoder: StructuredConditionEncoder
    flow: FlowMLP
    vocab: Any
    stats: LatentStats
    embed_cfg: ElfEmbedConfig
    flow_cfg: FlowConfig
    cond_cfg: StructuredCondConfig
    library: Tuple[List[str], torch.Tensor]
    train_log: List[Dict[str, Any]]
    val_metrics: Dict[str, Any]
    val_predictions: List[Dict[str, Any]]
    summary: Dict[str, Any]


def train_v1(
    train_examples: Sequence[Example], val_examples: Sequence[Example],
    full_dataset: Sequence[Example], cfg: ElfV1TrainConfig, *, device: str = "cpu", log_fn=None,
) -> ElfV1Artifacts:
    torch.manual_seed(cfg.seed)
    vocab = build_vocab_for_elf(train_examples)
    embed_cfg = ElfEmbedConfig(
        vocab_size=len(vocab), latent_dim=cfg.latent_dim, cond_dim=cfg.cond_dim,
        ae_emb=cfg.ae_emb, ae_hidden=cfg.ae_hidden, cond_emb=cfg.cond_emb,
        cond_hidden=cfg.cond_raw_hidden, dropout=cfg.dropout,
        max_tactic_len=cfg.max_tactic_len, max_cond_len=cfg.max_cond_len,
        pad_id=vocab.pad_id, bos_id=vocab.bos_id, eos_id=vocab.eos_id,
    )
    flow_cfg = FlowConfig(
        latent_dim=cfg.latent_dim, cond_dim=cfg.cond_dim, hidden=cfg.flow_hidden,
        n_layers=cfg.flow_layers, time_dim=cfg.time_dim,
    )
    cond_cfg = StructuredCondConfig(
        vocab_size=len(vocab), cond_dim=cfg.cond_dim, emb=cfg.cond_emb,
        raw_hidden=cfg.cond_raw_hidden, goal_hidden=cfg.cond_goal_hidden,
        shape_dim=cfg.cond_shape_dim, dropout=cfg.dropout, pad_id=vocab.pad_id,
        max_goal_len=cfg.max_goal_len,
    )
    log: List[Dict[str, Any]] = []

    train_tactics = [e.tactic for e in train_examples]
    val_tactics = [e.tactic for e in val_examples]
    ae = train_autoencoder_v1(train_tactics, val_tactics, vocab, embed_cfg, cfg, device, log)
    ae_recon = _ae_recon_exact(ae, val_tactics, vocab, cfg, device)

    stats, _ = compute_latent_stats(ae, train_tactics, vocab, cfg, device)
    src, src_len = encode_tactic_batch(train_tactics, vocab, cfg.max_tactic_len, device)
    with torch.no_grad():
        x_unstd = ae.encode(src, src_len)
    library = build_library(ae, train_examples, vocab, cfg, device)

    cond_encoder, flow, best_epoch = train_flow_v1(
        ae, vocab, cond_cfg, flow_cfg, train_examples, val_examples, full_dataset,
        stats, x_unstd, library, cfg, device, log, log_fn=log_fn,
    )

    final = MiniElfV1Baseline(
        ae, cond_encoder, flow, vocab, stats, cond_cfg=cond_cfg,
        n_samples=cfg.n_samples, steps=cfg.flow_steps, seed=cfg.seed, decode="decoder",
        library_latents=library[1], library_tactics=library[0],
        max_tactic_len=cfg.max_tactic_len, max_cond_len=cfg.max_cond_len, device=device,
    )
    val_metrics, val_preds = offline_val_report_v1(final, val_examples, full_dataset)
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
        "ae_denoise_prob": cfg.ae_denoise_prob,
        "ae_latent_noise_std": cfg.ae_latent_noise_std,
        "scheduled_sampling": cfg.scheduled_sampling,
        "uses_state_after": False,
    }

    return ElfV1Artifacts(
        ae=ae, cond_encoder=cond_encoder, flow=flow, vocab=vocab, stats=stats,
        embed_cfg=embed_cfg, flow_cfg=flow_cfg, cond_cfg=cond_cfg, library=library,
        train_log=log, val_metrics=val_metrics, val_predictions=val_preds, summary=summary,
    )


def save_artifacts_v1(out_dir: Path, art: ElfV1Artifacts, cfg: ElfV1TrainConfig,
                      extra: Optional[Dict[str, Any]] = None) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    config: Dict[str, Any] = {
        "model": "mini_elf_v1",
        "approach": "denoising tactic-AE latent + conditional rectified-flow + structured condition encoder",
        "embed": json.loads(art.embed_cfg.to_json()),
        "flow": json.loads(art.flow_cfg.to_json()),
        "structured_cond": art.cond_cfg.to_dict(),
        "latent_mean": art.stats.mean,
        "latent_std": art.stats.std,
        "training": {
            "ae_epochs": cfg.ae_epochs, "ae_lr": cfg.ae_lr, "ae_batch": cfg.ae_batch,
            "ae_denoise_prob": cfg.ae_denoise_prob, "ae_latent_noise_std": cfg.ae_latent_noise_std,
            "scheduled_sampling": cfg.scheduled_sampling,
            "ae_teacher_forcing_ratio": cfg.ae_teacher_forcing_ratio,
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
