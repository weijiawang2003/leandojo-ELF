"""Mini-ELF v39 — matched-token-budget trainer (library + single-cell CLI).

One *cell* = (family, scale, corpus U) trained to a fixed TOKEN budget with a
cosine LR schedule. Because every cell shares batch_size and seq_len, the budget
fixes the number of optimizer steps -> all cells run the SAME #steps; the only
thing that varies is how many epochs that is over U unique rows (data-constrained
crossover, brief H2). Checkpoints at token-budget fractions; at each, cheap dev
metrics (free-running exact-seq / per-token gold recovery / distinct@K) — these
gate who earns Lean verification later. No verifier here (that's Phase 4).

Reproducibility: writes config.json (all hyperparams, seed, git SHA, data
fingerprint = sha256 of the cell's train rows, measured tokens/sec) next to a
final state_dict snapshot. Resumable at the orchestrator level (skip a cell whose
snapshot + config already exist). bf16 autocast on CUDA. NaN guard raises so the
orchestrator can retry once at half-LR then mark FAILED.

Guardrails honored: train-only vocab (passed in), no state_after (v38_data), the
24-theorem tier is NEVER in train/dev (orchestrator's job).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT / "src"), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import torch

from mini_elf_lean.v38_backbone import V38Config, SCALE_PRESETS, count_params
from mini_elf_lean.v38_data import make_batch, cond_ids_for
from mini_elf_lean.elf_v38_ar import ARModel
from mini_elf_lean.elf_v38_flow import FlowModel
from mini_elf_lean.elf_v38_mdlm import MDLMModel
from mini_elf_lean.tactic_sanitizer import sanitize_candidate_list, tactic_head

FAMILIES = {"ar": ARModel, "mdlm": MDLMModel, "flow": FlowModel}


class NanError(RuntimeError):
    pass


# ----------------------------- helpers ----------------------------- #

def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT)).decode().strip()
    except Exception:
        return "unknown"


def data_fingerprint(rows: Sequence[Dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for r in rows:
        h.update((str(r.get("theorem_name", "")) + "\x1f" + str(r.get("state_before", "")) +
                  "\x1f" + str(r.get("tactic", "")) + "\n").encode("utf-8"))
    return h.hexdigest()


def make_cfg(scale: str, vocab, manifest) -> V38Config:
    return V38Config(vocab_size=len(vocab), max_cond_len=manifest["max_cond_len"],
                     max_tgt_len=manifest["max_tgt_len"], pad_id=vocab.pad_id,
                     bos_id=vocab.bos_id, eos_id=vocab.eos_id, **SCALE_PRESETS[scale])


def build_model(family: str, cfg: V38Config, **kw):
    if family == "flow":
        return FlowModel(cfg, **kw)
    if family == "mdlm":
        return MDLMModel(cfg)
    if family == "ar":
        return ARModel(cfg)
    raise ValueError(family)


def cosine_lr(step: int, total: int, warmup: int, base_lr: float, floor_frac: float = 0.1) -> float:
    if step < warmup:
        return base_lr * (step + 1) / max(warmup, 1)
    prog = (step - warmup) / max(total - warmup, 1)
    prog = min(max(prog, 0.0), 1.0)
    return base_lr * (floor_frac + (1 - floor_frac) * 0.5 * (1 + math.cos(math.pi * prog)))


def gen_kw_for(family: str, *, cfg_weight: float = 2.0) -> Dict[str, Any]:
    if family == "flow":
        return {"cfg_weight": cfg_weight, "self_cond": True}
    return {}


# ------------------------- cheap dev metrics ------------------------- #

@torch.no_grad()
def val_loss(model, val_rows, vocab, cfg, device, bs=256, n_rep=1) -> float:
    model.eval()
    tot, n = 0.0, 0
    for _ in range(n_rep):
        for s in range(0, len(val_rows), bs):
            b = make_batch(val_rows[s:s + bs], vocab, max_cond_len=cfg.max_cond_len,
                           max_tgt_len=cfg.max_tgt_len, device=device)
            tot += float(model.loss(b).item()); n += 1
    return tot / max(n, 1)


@torch.no_grad()
def dev_metrics(model, dev_rows, vocab, cfg, golds, device, *, n_dev=160, K=4, steps=16,
                gen_kw=None, distinct_prompts=8, distinct_K=32) -> Dict[str, Any]:
    """Free-running exact-seq / per-token gold recovery on a dev subset, and
    distinct@distinct_K on the first `distinct_prompts` dev prompts. Cheap gate."""
    model.eval()
    gen_kw = gen_kw or {}
    Tt = cfg.max_tgt_len
    sub = dev_rows[:n_dev]
    exact, n_samp, per_tok = 0, 0, []
    for r in sub:
        cond = cond_ids_for(r, vocab, max_cond_len=cfg.max_cond_len, device=device)
        ids = model.generate(cond, n_samples=K, steps=steps, prompt=r["theorem_name"], device=device, **gen_kw)
        gold_ids = (list(r["tgt_ids"])[:Tt] + [cfg.pad_id] * Tt)[:Tt]
        gpos = [i for i in range(Tt) if gold_ids[i] != cfg.pad_id]
        gset = golds.get((r["theorem_name"], r["state_before"]), frozenset({r["tactic"]}))
        if gpos:
            per_tok.append(sum(sum(1 for i in gpos if int(ids[k][i]) == gold_ids[i]) / len(gpos)
                               for k in range(ids.size(0))) / ids.size(0))
        for k in range(ids.size(0)):
            cl, _ = sanitize_candidate_list([vocab.decode_target(ids[k].tolist())])
            cand = cl[0] if cl else ""
            n_samp += 1
            if cand and cand in gset:
                exact += 1
    # distinct@K on fixed prompts
    distinct = []
    for r in dev_rows[:distinct_prompts]:
        cond = cond_ids_for(r, vocab, max_cond_len=cfg.max_cond_len, device=device)
        ids = model.generate(cond, n_samples=distinct_K, steps=steps, prompt=r["theorem_name"], device=device, **gen_kw)
        seen = set()
        for k in range(ids.size(0)):
            cl, _ = sanitize_candidate_list([vocab.decode_target(ids[k].tolist())])
            c = cl[0] if cl else ""
            if c:
                seen.add(c)
        distinct.append(len(seen))
    return {
        "dev_exact_seq": round(exact / max(n_samp, 1), 4),
        "dev_per_token": round(sum(per_tok) / len(per_tok), 4) if per_tok else 0.0,
        "dev_distinct_mean": round(sum(distinct) / len(distinct), 3) if distinct else 0.0,
        "dev_n_samples": n_samp,
    }


# ------------------------------- train ------------------------------- #

def cpu_state(model) -> Dict[str, torch.Tensor]:
    return {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}


def train_cell(*, family: str, scale: str, train_rows, val_rows, dev_rows, vocab, manifest,
               golds, token_budget: float, ckpt_fracs: Sequence[float], batch_size: int,
               base_lr: float, seed: int, device: str, cell_id: str, out_dir: Path,
               dev_n: int, K_dev: int, gen_steps: int, family_kw: Optional[Dict] = None,
               time_cap_s: float = 2400.0, bf16: bool = True, save_snapshot: bool = True,
               extra_meta: Optional[Dict] = None) -> Dict[str, Any]:
    family_kw = family_kw or {}
    torch.manual_seed(seed)
    cfg = make_cfg(scale, vocab, manifest)
    model = build_model(family, cfg, **family_kw).to(device)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=base_lr, weight_decay=0.01, betas=(0.9, 0.95))
    seq_len = cfg.max_cond_len + cfg.max_tgt_len
    total_steps = max(1, round(token_budget / (batch_size * seq_len)))
    warmup = max(1, round(0.02 * total_steps))
    ckpt_steps = sorted({max(1, round(f * total_steps)) for f in ckpt_fracs} | {total_steps})
    npar = count_params(model)
    gkw = gen_kw_for(family)
    g = torch.Generator(device="cpu"); g.manual_seed(seed)

    metrics: List[Dict[str, Any]] = []
    step, tokens = 0, 0
    t0 = time.perf_counter()
    done = False
    while step < total_steps and not done:
        perm = torch.randperm(len(train_rows), generator=g).tolist()
        for s in range(0, len(perm), batch_size):
            if step >= total_steps:
                break
            rows = [train_rows[i] for i in perm[s:s + batch_size]]
            b = make_batch(rows, vocab, max_cond_len=cfg.max_cond_len, max_tgt_len=cfg.max_tgt_len, device=device)
            lr = cosine_lr(step, total_steps, warmup, base_lr)
            for pg in opt.param_groups:
                pg["lr"] = lr
            model.train()
            if bf16 and device == "cuda":
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    L = model.loss(b)
            else:
                L = model.loss(b)
            if not torch.isfinite(L):
                raise NanError(f"{cell_id}: non-finite loss at step {step}")
            opt.zero_grad(); L.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0); opt.step()
            step += 1
            tokens += len(rows) * seq_len
            if step in ckpt_steps:
                vl = val_loss(model, val_rows, vocab, cfg, device)
                dm = dev_metrics(model, dev_rows, vocab, cfg, golds, device,
                                 n_dev=dev_n, K=K_dev, steps=gen_steps, gen_kw=gkw)
                tps = tokens / max(time.perf_counter() - t0, 1e-6)
                rec = {"cell": cell_id, "family": family, "scale": scale,
                       "U": len(train_rows), "params": npar, "step": step, "total_steps": total_steps,
                       "frac": round(step / total_steps, 3), "tokens": tokens,
                       "epochs": round(tokens / max(len(train_rows) * seq_len, 1), 2),
                       "val_loss": round(vl, 4), "lr": round(lr, 6), "tok_per_s": round(tps, 1), **dm}
                metrics.append(rec)
            if time.perf_counter() - t0 > time_cap_s:
                done = True
                break
    elapsed = time.perf_counter() - t0
    tps = tokens / max(elapsed, 1e-6)

    out_dir.mkdir(parents=True, exist_ok=True)
    snap_dir = out_dir / "snapshots"; snap_dir.mkdir(parents=True, exist_ok=True)
    cfg_dir = out_dir / "configs"; cfg_dir.mkdir(parents=True, exist_ok=True)
    snap_path = snap_dir / f"{cell_id}.pt"
    if save_snapshot:
        torch.save({"state_dict": cpu_state(model), "cfg": cfg.__dict__, "family": family,
                    "family_kw": family_kw}, snap_path)
    config = {
        "cell": cell_id, "family": family, "scale": scale, "U": len(train_rows),
        "params": npar, "token_budget": token_budget, "total_steps": total_steps,
        "warmup": warmup, "batch_size": batch_size, "base_lr": base_lr, "seq_len": seq_len,
        "seed": seed, "git_sha": git_sha(), "data_fingerprint": data_fingerprint(train_rows),
        "vocab_size": len(vocab), "ckpt_fracs": list(ckpt_fracs), "gen_steps": gen_steps,
        "K_dev": K_dev, "dev_n": dev_n, "family_kw": family_kw, "device": device,
        "measured_tok_per_s": round(tps, 1), "elapsed_s": round(elapsed, 1),
        "n_val": len(val_rows), "n_dev": len(dev_rows), "snapshot": str(snap_path),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), **(extra_meta or {}),
    }
    (cfg_dir / f"{cell_id}.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    final = metrics[-1] if metrics else {}
    return {"cell": cell_id, "metrics": metrics, "final": final, "config": config,
            "snapshot": str(snap_path), "npar": npar, "elapsed_s": round(elapsed, 1)}


__all__ = ["train_cell", "dev_metrics", "val_loss", "make_cfg", "build_model", "cosine_lr",
           "gen_kw_for", "data_fingerprint", "git_sha", "NanError", "FAMILIES"]
