"""Mini-ELF v35 — sampling + the :class:`Baseline` adapter for evaluation.

Generation is **continuous until ``t=1``**: per prompt we draw ``K`` Gaussian
seeds, integrate the conditional flow over the *whole* token-embedding sequence
(ODE Euler, optionally SDE), apply classifier-free guidance and
self-conditioning, then discretize at ``t=1`` by the **tied nearest-embedding
readout** — never a separate decoder. Decoded ids are detokenized with the
shared vocab, sanitized, ranked by sampling frequency, and the top-k are
returned for ``pass@k``.

Determinism + prompt-diversity: the per-prompt noise generator is seeded from
``seed ^ crc32(prompt)`` (matches Mini-ELF v0), so runs are reproducible yet
different prompts get different noise. :class:`MiniElfV35Baseline` plugs into
:func:`mini_elf_lean.baseline_eval.evaluate` exactly like the AR baselines, and
records per-prompt diagnostics (invalid-decode rate, distinct count) for the §6
generation-profile metrics. ``state_after`` is never read.
"""

from __future__ import annotations

import json
import math
import zlib
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import torch

from .baselines import Baseline, Example
from .elf_v35_embed import LatentStats, unstandardize
from .elf_v35_flow import ElfV35Model
from .elf_v35_train import load_model
from .tactic_sanitizer import contains_forbidden, sanitize_candidate_list
from .token_seq2seq_dataset import TokenVocab, build_input_text


def _seed_for(prompt: str, seed: int) -> int:
    return (seed ^ zlib.crc32(prompt.encode("utf-8"))) & 0x7FFFFFFF


@torch.no_grad()
def integrate(
    model: ElfV35Model,
    cond_ids: torch.Tensor,            # (1, S) one prompt
    mean: torch.Tensor,
    std: torch.Tensor,
    *,
    n_seeds: int,
    steps: int,
    cfg_weight: Optional[float] = 2.0,
    self_cond: bool = True,
    sde: bool = False,
    sde_noise: float = 0.15,
    seed: int = 0,
    prompt: str = "",
    device: str = "cpu",
) -> torch.Tensor:
    """Integrate ``dz/dt = v_θ(z,t,C)`` from ``z(0)~N(0,I)`` to ``z(1)`` for
    ``n_seeds`` draws of one prompt, returning decoded ids ``(n_seeds, T)``.

    * **CFG**: when ``cfg_weight`` is set and ``!= 1``, ``v = v_u + w·(v_c − v_u)``
      using cond / uncond memories built once.
    * **self-cond**: the previous step's clean estimate ``ẑ1`` is fed back.
    * **SDE**: optional Euler–Maruyama-style churn (adds noise each step) for a
      higher-diversity sampler; ODE is the default for the step-sensitivity sweep.
    """
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
    dt = 1.0 / max(steps, 1)

    for i in range(max(steps, 1)):
        tv = i * dt
        t = torch.full((B,), tv, dtype=torch.float32, device=device)
        v = model.field(z, t, mem_c, mp_c, sc)
        if use_cfg:
            v_u = model.field(z, t, mem_u, mp_u, sc)
            v = v_u + cfg_weight * (v - v_u)
        if self_cond:
            sc = (z + (1.0 - tv) * v).detach()
        z = z + dt * v
        if sde and i < steps - 1:
            z = z + sde_noise * math.sqrt(dt) * torch.randn(B, T, D, generator=g, device=device)

    raw = unstandardize(z, mean, std)
    return model.readout_ids(raw)      # (B, T)


def decode_and_rank(
    ids: torch.Tensor, vocab: TokenVocab
) -> Tuple[List[Tuple[str, int]], Dict[str, Any]]:
    """ids ``(B, T)`` → frequency-ranked ``(tactic, count)`` survivors + decode
    diagnostics. ``count`` is over the raw decodes (probability-mass proxy)."""
    B = ids.size(0)
    raw_strings = [vocab.decode_target(ids[b].tolist()) for b in range(B)]
    counts: Counter = Counter()
    n_invalid = 0
    for s in raw_strings:
        cleaned, _ = sanitize_candidate_list([s])
        cand = cleaned[0] if cleaned else ""
        if not cand or contains_forbidden(cand):
            n_invalid += 1
            continue
        counts[cand] += 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    diagnostics = {
        "n_seeds": B,
        "n_invalid_decode": n_invalid,
        "invalid_decode_rate": n_invalid / B if B else 0.0,
        "n_distinct_raw": len(set(raw_strings)),
        "n_distinct_valid": len(ranked),
    }
    return ranked, diagnostics


class MiniElfV35Baseline(Baseline):
    """Trained Mini-ELF v35 flow model behind the :class:`Baseline` interface.

    ``predict`` encodes the condition, draws ``n_samples`` seeds, integrates the
    flow, nearest-embedding-decodes at ``t=1``, sanitizes, ranks by sampling
    frequency, and returns the top-k. Per-prompt diagnostics are stored on the
    instance (``last_diagnostics`` / appended to ``diagnostics_log``)."""

    name = "mini_elf_v35"

    def __init__(
        self,
        model: ElfV35Model,
        vocab: TokenVocab,
        stats: LatentStats,
        *,
        n_samples: int = 32,
        steps: int = 8,
        cfg_weight: Optional[float] = 2.0,
        self_cond: bool = True,
        sde: bool = False,
        seed: int = 0,
        max_cond_len: int = 96,
        device: str = "cpu",
    ) -> None:
        self.model = model.eval()
        self.vocab = vocab
        self.stats = stats
        self.n_samples = n_samples
        self.steps = steps
        self.cfg_weight = cfg_weight
        self.self_cond = self_cond
        self.sde = sde
        self.seed = seed
        self.max_cond_len = max_cond_len
        self.device = device
        self._mean, self._std = stats.tensors(device)
        self.last_diagnostics: Dict[str, Any] = {}
        self.diagnostics_log: List[Dict[str, Any]] = []

    @property
    def mode(self) -> str:
        return (f"flow_v35(samples={self.n_samples},steps={self.steps},"
                f"cfg={self.cfg_weight},self_cond={self.self_cond},sde={self.sde})")

    def fit(self, train) -> "MiniElfV35Baseline":  # noqa: ARG002 - pre-trained
        return self

    def _cond_ids(self, text: str) -> torch.Tensor:
        ids = self.vocab.encode_source(text)[: self.max_cond_len] or [self.vocab.pad_id]
        return torch.tensor([ids], dtype=torch.long, device=self.device)

    def sample_candidates(self, text: str, n_samples: Optional[int] = None,
                          steps: Optional[int] = None) -> Tuple[List[Tuple[str, int]], Dict[str, Any]]:
        cond_ids = self._cond_ids(text)
        ids = integrate(
            self.model, cond_ids, self._mean, self._std,
            n_seeds=n_samples or self.n_samples,
            steps=steps or self.steps,
            cfg_weight=self.cfg_weight, self_cond=self.self_cond, sde=self.sde,
            seed=self.seed, prompt=text, device=self.device,
        )
        return decode_and_rank(ids, self.vocab)

    def predict(self, example: Example, *, k: int) -> List[str]:
        text = build_input_text(example.theorem_statement, example.state_before)
        ranked, diag = self.sample_candidates(text)
        diag = {**diag, "theorem_name": example.theorem_name, "n_returned": min(k, len(ranked))}
        self.last_diagnostics = diag
        self.diagnostics_log.append(diag)
        return [t for t, _ in ranked[:k]]

    def predict_with_counts(self, example: Example) -> List[Tuple[str, int]]:
        text = build_input_text(example.theorem_statement, example.state_before)
        ranked, _ = self.sample_candidates(text)
        return ranked

    # ---- persistence ----

    @classmethod
    def load(
        cls,
        model_dir: Path,
        *,
        vocab_path: Optional[Path] = None,
        n_samples: int = 32,
        steps: int = 8,
        cfg_weight: Optional[float] = 2.0,
        self_cond: bool = True,
        sde: bool = False,
        seed: int = 0,
        device: str = "cpu",
    ) -> "MiniElfV35Baseline":
        model, cfg, stats = load_model(model_dir, device=device)
        if vocab_path is None:
            vocab_path = Path(model_dir) / "vocab.json"
        vocab = TokenVocab.load(vocab_path)
        return cls(
            model, vocab, stats,
            n_samples=n_samples, steps=steps, cfg_weight=cfg_weight,
            self_cond=self_cond, sde=sde, seed=seed,
            max_cond_len=cfg.max_cond_len, device=device,
        )


__all__ = ["integrate", "decode_and_rank", "MiniElfV35Baseline"]
