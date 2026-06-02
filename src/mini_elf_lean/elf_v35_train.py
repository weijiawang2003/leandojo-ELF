"""Mini-ELF v35 — training the ELF-style embedded-flow model (CPU, deterministic).

Objective (faithful to ELF, arXiv 2605.10938):

* **Flow matching** — standardize ``Z1 = E[ids]`` with per-dim train stats, draw
  ``Z0 ~ N(0,I)``, ``z_t = (1−t)Z0 + tZ1``, target ``v = Z1 − Z0``;
  ``L_fm = masked-MSE(v_θ(z_t,t,C), v)`` over non-pad target positions.
* **CE anchor** (prob ``p_ce≈0.2``) — reconstruct ``Ẑ1 = z_t + (1−t)·v_θ``,
  *un-standardize* (the tied readout lives in raw embedding space), and add a
  cross-entropy on the nearest-embedding logits, ignoring pad.
* **Self-conditioning** (prob ``p_selfcond≈0.5``) — a no-grad pass produces a
  detached ``Ẑ1`` that is fed back as the field's self-cond input.
* **Classifier-free guidance** (prob ``p_uncond≈0.1``) — the condition is
  dropped to the learned null token for a fraction of examples.
* **Time schedule** — logit-normal ``t = sigmoid(N(p_mean=−1.5, p_std=0.8))``.

Per-dim latent stats are recomputed from the (learned) embedding table after
every epoch and the stats matching the selected checkpoint are saved, so
sampling standardizes with exactly the stats the chosen weights were trained
against. Checkpoint selection is by an **offline** validation flow-MSE (no Lean).
``state_after`` is never read; training uses the train split only.
"""

from __future__ import annotations

import copy
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import torch
import torch.nn.functional as F

from .elf_flow import interpolate, velocity_target
from .elf_v35_embed import (
    ElfV35Config,
    LatentStats,
    compute_latent_stats,
    padding_mask,
    standardize,
    unstandardize,
)
from .elf_v35_flow import ElfV35Model


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


@dataclass
class ElfV35TrainConfig:
    epochs: int = 60
    batch_size: int = 64
    lr: float = 1e-3
    weight_decay: float = 1e-4
    grad_clip: float = 1.0
    seed: int = 0
    # objective probabilities / weights
    p_selfcond: float = 0.5
    p_ce: float = 0.2
    p_uncond: float = 0.1
    ce_weight: float = 0.2
    # logit-normal time schedule
    time_p_mean: float = -1.5
    time_p_std: float = 0.8
    # ablation switches (A1–A3): default = full ELF objective
    use_selfcond: bool = True
    use_ce: bool = True
    use_cfg: bool = True

    def to_jsonable(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


def load_rows(path: Path) -> List[Dict[str, Any]]:
    if not Path(path).exists():
        return []
    out = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(json.loads(s))
    return out


def _make_batch(rows: Sequence[Dict[str, Any]], *, pad_id: int, T: int, device: str
                ) -> Tuple[torch.Tensor, torch.Tensor]:
    """Pad cond_ids to the batch max, tgt_ids to exactly ``T`` (the fixed flow
    length). Targets shorter than ``T`` are pad-tailed (those positions are
    unsupervised in the loss)."""
    B = len(rows)
    Sc = max((len(r["cond_ids"]) for r in rows), default=1)
    Sc = max(Sc, 1)
    cond = torch.full((B, Sc), pad_id, dtype=torch.long)
    tgt = torch.full((B, T), pad_id, dtype=torch.long)
    for i, r in enumerate(rows):
        c = r["cond_ids"][:Sc]
        cond[i, : len(c)] = torch.tensor(c, dtype=torch.long)
        t = r["tgt_ids"][:T]
        tgt[i, : len(t)] = torch.tensor(t, dtype=torch.long)
    return cond.to(device), tgt.to(device)


# --------------------------------------------------------------------------- #
# Loss
# --------------------------------------------------------------------------- #


def sample_logit_normal_time(B: int, cfg: ElfV35TrainConfig, *, generator, device: str) -> torch.Tensor:
    """``t = sigmoid(p_mean + p_std · N(0,1))`` → shape ``(B,)`` in (0,1)."""
    z = torch.randn(B, generator=generator, device=device)
    return torch.sigmoid(cfg.time_p_mean + cfg.time_p_std * z)


def compute_losses(
    model: ElfV35Model,
    cond_ids: torch.Tensor,
    tgt_ids: torch.Tensor,
    mean: torch.Tensor,
    std: torch.Tensor,
    cfg: ElfV35TrainConfig,
    *,
    generator,
) -> Dict[str, torch.Tensor]:
    """Full ELF objective on one batch. Returns dict of scalar tensors:
    ``total``, ``fm``, ``ce`` (ce==0 when not applied this step)."""
    device = tgt_ids.device
    B, T = tgt_ids.shape
    D = model.cfg.d_model
    pad_id = model.cfg.pad_id

    Z1 = model.embed_targets(tgt_ids)                       # (B,T,D) raw
    Z1s = standardize(Z1, mean, std)
    Z0 = torch.randn(B, T, D, generator=generator, device=device)
    t = sample_logit_normal_time(B, cfg, generator=generator, device=device)  # (B,)
    t3 = t.view(B, 1, 1)
    z_t = interpolate(Z0, Z1s, t3)
    v_tgt = velocity_target(Z0, Z1s)                        # Z1s - Z0

    # CFG: drop condition to null for a fraction of examples.
    if cfg.use_cfg and cfg.p_uncond > 0:
        drop = torch.rand(B, generator=generator, device=device) < cfg.p_uncond
    else:
        drop = None
    memory, mem_pad = model.build_memory(cond_ids, drop)

    # Self-conditioning: no-grad estimate of ẑ1, fed back for a fraction.
    self_cond = None
    if cfg.use_selfcond and cfg.p_selfcond > 0:
        with torch.no_grad():
            v0 = model.field(z_t, t, memory, mem_pad, None)
            z1_hat = (z_t + (1.0 - t3) * v0).detach()
        use_sc = (torch.rand(B, generator=generator, device=device) < cfg.p_selfcond)
        self_cond = z1_hat * use_sc.view(B, 1, 1).float()

    v_pred = model.field(z_t, t, memory, mem_pad, self_cond)

    # Masked flow-matching MSE over non-pad target positions.
    valid = (~padding_mask(tgt_ids, pad_id)).float()        # (B,T)
    se = (v_pred - v_tgt).pow(2).mean(dim=-1)               # (B,T)
    fm = (se * valid).sum() / valid.sum().clamp(min=1.0)

    # CE anchor (probabilistic): reconstruct clean signal → un-standardize →
    # tied nearest-embedding logits → CE ignoring pad.
    ce = torch.zeros((), device=device)
    if cfg.use_ce and cfg.p_ce > 0:
        if torch.rand((), generator=generator, device=device).item() < cfg.p_ce:
            z1_hat_pred = z_t + (1.0 - t3) * v_pred         # standardized clean est
            raw = unstandardize(z1_hat_pred, mean, std)
            logits = model.readout_logits(raw)              # (B,T,V)
            ce = F.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                tgt_ids.reshape(-1),
                ignore_index=pad_id,
            )

    total = fm + cfg.ce_weight * ce
    return {"total": total, "fm": fm.detach(), "ce": ce.detach()}


@torch.no_grad()
def offline_val_loss(
    model: ElfV35Model,
    rows: Sequence[Dict[str, Any]],
    mean: torch.Tensor,
    std: torch.Tensor,
    cfg: ElfV35TrainConfig,
    *,
    device: str,
    batch_size: int = 128,
) -> float:
    """Deterministic offline flow-MSE on a split (no Lean, no self-cond, full
    condition). A fixed-seed generator makes it comparable across epochs so the
    checkpoint selector is stable."""
    if not rows:
        return 0.0
    model.eval()
    T = model.cfg.max_tgt_len
    pad_id = model.cfg.pad_id
    D = model.cfg.d_model
    g = torch.Generator(device=device)
    g.manual_seed(12345)
    total = 0.0
    n = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        cond_ids, tgt_ids = _make_batch(batch, pad_id=pad_id, T=T, device=device)
        B = tgt_ids.size(0)
        Z1s = standardize(model.embed_targets(tgt_ids), mean, std)
        Z0 = torch.randn(B, T, D, generator=g, device=device)
        t = sample_logit_normal_time(B, cfg, generator=g, device=device)
        t3 = t.view(B, 1, 1)
        z_t = interpolate(Z0, Z1s, t3)
        v_tgt = velocity_target(Z0, Z1s)
        memory, mem_pad = model.build_memory(cond_ids, None)
        v_pred = model.field(z_t, t, memory, mem_pad, None)
        valid = (~padding_mask(tgt_ids, pad_id)).float()
        se = (v_pred - v_tgt).pow(2).mean(dim=-1)
        total += float((se * valid).sum().item())
        n += float(valid.sum().item())
    return total / max(n, 1.0)


# --------------------------------------------------------------------------- #
# Train loop
# --------------------------------------------------------------------------- #


@dataclass
class ElfV35Artifacts:
    model: ElfV35Model
    config: ElfV35Config
    stats: LatentStats
    train_log: List[Dict[str, Any]]
    summary: Dict[str, Any]
    best_state: Dict[str, Any] = field(default_factory=dict)


def _train_target_token_ids(rows: Sequence[Dict[str, Any]]) -> List[int]:
    out: List[int] = []
    for r in rows:
        out.extend(r["tgt_ids"])
    return out


def train(
    model_cfg: ElfV35Config,
    train_rows: Sequence[Dict[str, Any]],
    val_rows: Sequence[Dict[str, Any]],
    cfg: ElfV35TrainConfig,
    *,
    device: str = "cpu",
    log_fn=None,
) -> ElfV35Artifacts:
    torch.manual_seed(cfg.seed)
    model = ElfV35Model(model_cfg).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)

    g = torch.Generator(device=device)
    g.manual_seed(cfg.seed)

    train_rows = list(train_rows)
    tok_ids = _train_target_token_ids(train_rows)
    T = model_cfg.max_tgt_len
    pad_id = model_cfg.pad_id

    # Initial stats from the (untrained) embedding.
    stats = compute_latent_stats(model.embed, tok_ids)
    mean, std = stats.tensors(device)

    best_val = float("inf")
    best_state = copy.deepcopy({k: v.detach().clone() for k, v in model.state_dict().items()})
    best_stats = stats
    best_epoch = -1
    train_log: List[Dict[str, Any]] = []
    perm = torch.randperm(len(train_rows), generator=g).tolist()
    t0 = time.perf_counter()

    for epoch in range(cfg.epochs):
        model.train()
        perm = torch.randperm(len(train_rows), generator=g).tolist()
        ep_total = ep_fm = ep_ce = 0.0
        n_batches = 0
        for start in range(0, len(perm), cfg.batch_size):
            idx = perm[start : start + cfg.batch_size]
            batch = [train_rows[i] for i in idx]
            cond_ids, tgt_ids = _make_batch(batch, pad_id=pad_id, T=T, device=device)
            losses = compute_losses(model, cond_ids, tgt_ids, mean, std, cfg, generator=g)
            opt.zero_grad()
            losses["total"].backward()
            if cfg.grad_clip:
                torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
            opt.step()
            ep_total += float(losses["total"].item())
            ep_fm += float(losses["fm"].item())
            ep_ce += float(losses["ce"].item())
            n_batches += 1

        # Refresh stats from the updated embedding; the saved stats match the
        # saved weights (both post-epoch).
        stats = compute_latent_stats(model.embed, tok_ids)
        mean, std = stats.tensors(device)
        val_fm = offline_val_loss(model, val_rows, mean, std, cfg, device=device)

        rec = {
            "epoch": epoch,
            "train_total": round(ep_total / max(n_batches, 1), 6),
            "train_fm": round(ep_fm / max(n_batches, 1), 6),
            "train_ce": round(ep_ce / max(n_batches, 1), 6),
            "val_fm": round(val_fm, 6),
        }
        train_log.append(rec)
        if log_fn is not None:
            log_fn(rec)

        select = val_fm if val_rows else (ep_fm / max(n_batches, 1))
        if select < best_val:
            best_val = select
            best_state = copy.deepcopy({k: v.detach().clone() for k, v in model.state_dict().items()})
            best_stats = stats
            best_epoch = epoch

    model.load_state_dict(best_state)
    model.eval()

    summary = {
        "n_train_rows": len(train_rows),
        "n_val_rows": len(val_rows),
        "n_parameters": int(sum(p.numel() for p in model.parameters() if p.requires_grad)),
        "best_epoch": best_epoch,
        "best_val_fm": round(best_val, 6),
        "selected_by": "offline val flow-MSE (no Lean)" if val_rows else "last/train-fm (no val)",
        "runtime_seconds": round(time.perf_counter() - t0, 1),
        "uses_state_after": False,
        "uses_manual_oracle": False,
        "train_config": cfg.to_jsonable(),
    }
    return ElfV35Artifacts(
        model=model, config=model_cfg, stats=best_stats,
        train_log=train_log, summary=summary, best_state=best_state,
    )


def save_artifacts(out_dir: Path, art: ElfV35Artifacts, *, vocab_src: Optional[Path] = None) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    art.config.save(out_dir / "config.json")
    (out_dir / "latent_stats.json").write_text(json.dumps(art.stats.to_dict()), encoding="utf-8")
    torch.save(art.best_state, out_dir / "model.pt")
    with (out_dir / "train_log.jsonl").open("w", encoding="utf-8") as f:
        for r in art.train_log:
            f.write(json.dumps(r) + "\n")
    (out_dir / "summary.json").write_text(json.dumps(art.summary, indent=2, ensure_ascii=False), encoding="utf-8")
    if vocab_src is not None and Path(vocab_src).exists():
        (out_dir / "vocab.json").write_text(Path(vocab_src).read_text(encoding="utf-8"), encoding="utf-8")


def load_model(model_dir: Path, *, device: str = "cpu") -> Tuple[ElfV35Model, ElfV35Config, LatentStats]:
    md = Path(model_dir)
    cfg = ElfV35Config.load(md / "config.json")
    model = ElfV35Model(cfg).to(device)
    model.load_state_dict(torch.load(md / "model.pt", map_location=device))
    model.eval()
    stats = LatentStats.from_dict(json.loads((md / "latent_stats.json").read_text(encoding="utf-8")))
    return model, cfg, stats


__all__ = [
    "ElfV35TrainConfig", "ElfV35Artifacts",
    "load_rows", "compute_losses", "offline_val_loss", "sample_logit_normal_time",
    "train", "save_artifacts", "load_model",
]
