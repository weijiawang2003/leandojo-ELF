"""Mini-ELF v36 — iterative-refinement / discrete-diffusion sampler.

The v35 continuous sampler self-conditions on the *continuous* clean estimate
``ẑ1`` and decodes only once, at ``t=1``. Because the field is non-autoregressive,
nothing couples the per-position predictions, so it produces "token salad" (v35
report: ~32% per-token recovery, 0% verify). This module is the canonical fix —
**self-condition on the DISCRETE estimate** (analog-bits / discrete-diffusion
style) so the model re-conditions each step on a committed *token* sequence, with
an optional **low-confidence remasking** schedule (re-noise the positions whose
nearest-embedding confidence is smallest, MaskGIT-style) so uncertain positions
are re-decided given the confident ones.

It does **not** edit ``elf_v35_sample`` — it is a drop-in alternative
``integrate_discrete`` plus a :class:`Baseline` adapter, so the §2 coherence probe
can compare the two samplers on the identical trained model.

Per step ``i`` (of ``N``), at time ``t = i/N``:

1. ``v = v_θ(z, t, C, sc)`` (with CFG);
2. continuous clean estimate ``ẑ1 = z + (1−t)·v``;
3. **snap**: un-standardize → tied nearest-embedding readout → ``ids`` (+ softmax
   confidence per position) → re-embed → re-standardize = ``ẑ1_disc`` (the
   committed discrete hypothesis);
4. ``sc ← ẑ1_disc`` (discrete self-conditioning for the next step);
5. **re-noise to ``t_next``**: ``z = (1−t_eff)·ε + t_eff·ẑ1_disc``. With
   ``remask``, ``t_eff = t_next`` for the top-confidence (committed) positions and
   ``0`` (pure noise) for the rest, with the committed fraction growing as
   ``t_next``; without it, ``t_eff = t_next`` uniformly.

The final ``ids`` is the snap of the last step. CPU, deterministic
(``seed ^ crc32(prompt)``); ``state_after`` never read.
"""

from __future__ import annotations

import zlib
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import torch

from .baselines import Baseline, Example
from .elf_v35_embed import LatentStats, standardize, unstandardize
from .elf_v35_flow import ElfV35Model
from .elf_v35_sample import decode_and_rank
from .elf_v35_train import load_model
from .token_seq2seq_dataset import TokenVocab, build_input_text


def _seed_for(prompt: str, seed: int) -> int:
    return (seed ^ zlib.crc32(prompt.encode("utf-8"))) & 0x7FFFFFFF


@torch.no_grad()
def _snap(model: ElfV35Model, z1_std: torch.Tensor, mean: torch.Tensor, std: torch.Tensor
          ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Standardized continuous estimate → (ids, per-position confidence,
    standardized snapped embeddings)."""
    raw = unstandardize(z1_std, mean, std)
    logits = model.readout_logits(raw)            # (K,T,V)
    probs = logits.softmax(dim=-1)
    conf, ids = probs.max(dim=-1)                 # (K,T)
    z1_disc = standardize(model.embed.embed(ids), mean, std)
    return ids, conf, z1_disc


@torch.no_grad()
def integrate_discrete(
    model: ElfV35Model,
    cond_ids: torch.Tensor,                # (1, S)
    mean: torch.Tensor,
    std: torch.Tensor,
    *,
    n_seeds: int,
    steps: int,
    cfg_weight: Optional[float] = 2.0,
    remask: bool = True,
    seed: int = 0,
    prompt: str = "",
    device: str = "cpu",
) -> torch.Tensor:
    """Iterative discrete-self-conditioning sampler → decoded ids ``(n_seeds, T)``."""
    model.eval()
    B = max(n_seeds, 1)
    T, D = model.cfg.max_tgt_len, model.cfg.d_model
    cond_ids = cond_ids.expand(B, -1).contiguous().to(device)

    use_cfg = cfg_weight is not None and abs(cfg_weight - 1.0) > 1e-9
    mem_c, mp_c = model.build_memory(cond_ids, torch.zeros(B, dtype=torch.bool, device=device))
    if use_cfg:
        mem_u, mp_u = model.build_memory(cond_ids, torch.ones(B, dtype=torch.bool, device=device))

    g = torch.Generator(device=device)
    g.manual_seed(_seed_for(prompt, seed))
    z = torch.randn(B, T, D, generator=g, device=device)
    sc: Optional[torch.Tensor] = None
    ids = torch.zeros(B, T, dtype=torch.long, device=device)

    for i in range(max(steps, 1)):
        t_val = i / max(steps, 1)
        t = torch.full((B,), t_val, dtype=torch.float32, device=device)
        v = model.field(z, t, mem_c, mp_c, sc)
        if use_cfg:
            v_u = model.field(z, t, mem_u, mp_u, sc)
            v = v_u + cfg_weight * (v - v_u)
        z1 = z + (1.0 - t_val) * v                 # continuous clean estimate
        ids, conf, z1_disc = _snap(model, z1, mean, std)
        sc = z1_disc.detach()                      # DISCRETE self-conditioning
        if i == max(steps, 1) - 1:
            break
        t_next = (i + 1) / max(steps, 1)
        eps = torch.randn(B, T, D, generator=g, device=device)
        if remask:
            commit_frac = t_next                   # commit more positions as t grows
            q = max(0.0, min(1.0, 1.0 - commit_frac))
            thresh = torch.quantile(conf, q, dim=1, keepdim=True)   # (B,1)
            committed = conf >= thresh                              # (B,T)
            t_eff = torch.where(committed, torch.full_like(conf, t_next),
                                torch.zeros_like(conf)).unsqueeze(-1)  # (B,T,1)
        else:
            t_eff = t_next
        z = (1.0 - t_eff) * eps + t_eff * z1_disc
    return ids


class MiniElfV36Baseline(Baseline):
    """v36 iterative/discrete sampler behind the :class:`Baseline` interface
    (for the gated verified run; mirrors MiniElfV35Baseline)."""

    name = "mini_elf_v36"

    def __init__(self, model: ElfV35Model, vocab: TokenVocab, stats: LatentStats, *,
                 n_samples: int = 32, steps: int = 8, cfg_weight: Optional[float] = 2.0,
                 remask: bool = True, seed: int = 0, max_cond_len: int = 96, device: str = "cpu") -> None:
        self.model = model.eval()
        self.vocab = vocab
        self.stats = stats
        self.n_samples = n_samples
        self.steps = steps
        self.cfg_weight = cfg_weight
        self.remask = remask
        self.seed = seed
        self.max_cond_len = max_cond_len
        self.device = device
        self._mean, self._std = stats.tensors(device)
        self.diagnostics_log: List[dict] = []

    @property
    def mode(self) -> str:
        return f"flow_v36_iterative(samples={self.n_samples},steps={self.steps},cfg={self.cfg_weight},remask={self.remask})"

    def fit(self, train):  # noqa: ARG002
        return self

    def _cond_ids(self, text: str) -> torch.Tensor:
        ids = self.vocab.encode_source(text)[: self.max_cond_len] or [self.vocab.pad_id]
        return torch.tensor([ids], dtype=torch.long, device=self.device)

    def sample_candidates(self, text: str, n_samples=None, steps=None):
        ids = integrate_discrete(self.model, self._cond_ids(text), self._mean, self._std,
                                 n_seeds=n_samples or self.n_samples, steps=steps or self.steps,
                                 cfg_weight=self.cfg_weight, remask=self.remask,
                                 seed=self.seed, prompt=text, device=self.device)
        return decode_and_rank(ids, self.vocab)

    def predict(self, example: Example, *, k: int) -> List[str]:
        text = build_input_text(example.theorem_statement, example.state_before)
        ranked, diag = self.sample_candidates(text)
        self.diagnostics_log.append({**diag, "theorem_name": example.theorem_name})
        return [t for t, _ in ranked[:k]]

    def predict_with_counts(self, example: Example):
        text = build_input_text(example.theorem_statement, example.state_before)
        return self.sample_candidates(text)[0]

    @classmethod
    def load(cls, model_dir: Path, *, vocab_path: Optional[Path] = None, n_samples: int = 32,
             steps: int = 8, cfg_weight: Optional[float] = 2.0, remask: bool = True,
             seed: int = 0, device: str = "cpu") -> "MiniElfV36Baseline":
        model, cfg, stats = load_model(model_dir, device=device)
        vocab = TokenVocab.load(vocab_path or (Path(model_dir) / "vocab.json"))
        return cls(model, vocab, stats, n_samples=n_samples, steps=steps, cfg_weight=cfg_weight,
                   remask=remask, seed=seed, max_cond_len=cfg.max_cond_len, device=device)


__all__ = ["integrate_discrete", "MiniElfV36Baseline"]
