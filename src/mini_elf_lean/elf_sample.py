"""Mini-ELF v0 — sampling + the :class:`Baseline` adapter for evaluation.

Sampling: draw K Gaussian noise vectors, integrate the flow (Euler) to K latent
candidates, un-standardize, and decode each latent to a tactic string — either
with the AE **decoder** (the true generative path, Option A) or by **nearest
neighbour** snap to a train tactic library (Option C, a robustness ablation).
Candidates are deduplicated and ranked by sampling frequency (a proxy for
probability mass), which gives the top-k for ``pass@k``.

Determinism: the per-example noise generator is seeded from
``seed ^ crc32(prompt)`` — reproducible across runs, yet different prompts get
different noise. :class:`MiniElfBaseline` plugs into
:func:`mini_elf_lean.baseline_eval.evaluate` exactly like the AR baseline, so the
numbers are directly comparable.
"""

from __future__ import annotations

import json
import zlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import torch

from .ar_model import Vocab, build_input_text
from .baselines import Baseline, Example
from .elf_embed import (
    ConditionEncoder,
    ElfEmbedConfig,
    TacticAutoencoder,
    encode_condition_batch,
)
from .elf_flow import FlowConfig, FlowMLP


# ---------------- latent standardization ----------------


@dataclass
class LatentStats:
    """Per-dim mean/std of the train tactic latents (so the flow target and the
    N(0,I) noise live on the same scale)."""

    mean: List[float]
    std: List[float]

    def tensors(self, device: str = "cpu") -> Tuple[torch.Tensor, torch.Tensor]:
        m = torch.tensor(self.mean, dtype=torch.float32, device=device)
        s = torch.tensor(self.std, dtype=torch.float32, device=device)
        return m, s


def standardize(z: torch.Tensor, mean: torch.Tensor, std: torch.Tensor) -> torch.Tensor:
    return (z - mean) / std


def unstandardize(x: torch.Tensor, mean: torch.Tensor, std: torch.Tensor) -> torch.Tensor:
    return x * std + mean


# ---------------- flow integration ----------------


@torch.no_grad()
def euler_integrate(flow: FlowMLP, eps: torch.Tensor, c: torch.Tensor, *, steps: int) -> torch.Tensor:
    """Integrate dz/dt = v(z,t,c) from z(0)=eps to z(1) with ``steps`` Euler
    steps. ``eps`` (B,L), ``c`` (B,cond) → standardized latent (B,L)."""
    flow.eval()
    z = eps
    dt = 1.0 / max(steps, 1)
    b = eps.size(0)
    for i in range(max(steps, 1)):
        t_val = i * dt
        t = torch.full((b, 1), t_val, dtype=torch.float32, device=eps.device)
        v = flow(z, t, c)
        z = z + dt * v
    return z


# ---------------- latent → string decoders ----------------


def decode_with_decoder(
    ae: TacticAutoencoder, latents: torch.Tensor, vocab: Vocab, *, max_len: int
) -> List[str]:
    """Generative decode: run the AE decoder on each (un-standardized) latent."""
    return ae.decode_greedy(latents, vocab, max_len=max_len)


def nn_decode(
    latents: torch.Tensor, library_latents: torch.Tensor, library_tactics: Sequence[str]
) -> List[str]:
    """Snap each latent to its nearest library latent (Euclidean) and return the
    corresponding train tactic. A robustness ablation — not open-vocabulary."""
    if library_latents.numel() == 0:
        return [""] * latents.size(0)
    # (B, Nlib) pairwise squared distances
    d = torch.cdist(latents, library_latents)  # (B, Nlib)
    idx = d.argmin(dim=-1).tolist()
    return [library_tactics[i] for i in idx]


# ---------------- baseline adapter ----------------


class MiniElfBaseline(Baseline):
    """Trained Mini-ELF v0 behind the :class:`Baseline` interface.

    ``predict`` samples K latents from the conditional flow and decodes them to
    tactic strings, ranked by sampling frequency. ``fit`` is a no-op (models are
    trained offline by :mod:`mini_elf_lean.elf_train`); use :meth:`load`.
    """

    name = "mini_elf"

    def __init__(
        self,
        ae: TacticAutoencoder,
        cond_encoder: ConditionEncoder,
        flow: FlowMLP,
        vocab: Vocab,
        stats: LatentStats,
        *,
        n_samples: int = 32,
        steps: int = 10,
        seed: int = 0,
        decode: str = "decoder",
        library_latents: Optional[torch.Tensor] = None,
        library_tactics: Optional[Sequence[str]] = None,
        max_tactic_len: int = 80,
        max_cond_len: int = 160,
        device: str = "cpu",
    ) -> None:
        if decode not in ("decoder", "nn"):
            raise ValueError(f"decode must be 'decoder' or 'nn', got {decode!r}")
        self.ae = ae.eval()
        self.cond_encoder = cond_encoder.eval()
        self.flow = flow.eval()
        self.vocab = vocab
        self.stats = stats
        self.n_samples = n_samples
        self.steps = steps
        self.seed = seed
        self.decode = decode
        self.library_latents = library_latents
        self.library_tactics = list(library_tactics) if library_tactics is not None else []
        self.max_tactic_len = max_tactic_len
        self.max_cond_len = max_cond_len
        self.device = device
        self._mean, self._std = stats.tensors(device)

    @property
    def mode(self) -> str:
        return f"flow(samples={self.n_samples},steps={self.steps},decode={self.decode})"

    def fit(self, train) -> "MiniElfBaseline":  # noqa: ARG002 - pre-trained
        return self

    def _condition(self, text: str) -> torch.Tensor:
        src, src_len = encode_condition_batch([text], self.vocab, self.max_cond_len, self.device)
        with torch.no_grad():
            return self.cond_encoder(src, src_len)  # (1, cond_dim)

    def sample_candidates(self, text: str, n_samples: Optional[int] = None) -> List[Tuple[str, int]]:
        """Return ``(tactic, count)`` pairs sorted by count desc, ties alpha.
        Count = how many of the noise draws decoded to that string."""
        n = n_samples or self.n_samples
        c = self._condition(text).expand(n, -1).contiguous()
        g = torch.Generator(device=self.device)
        g.manual_seed((self.seed ^ zlib.crc32(text.encode("utf-8"))) & 0x7FFFFFFF)
        eps = torch.randn(n, self.stats_dim, generator=g, device=self.device)
        x_std = euler_integrate(self.flow, eps, c, steps=self.steps)
        latents = unstandardize(x_std, self._mean, self._std)
        if self.decode == "decoder":
            strings = decode_with_decoder(self.ae, latents, self.vocab, max_len=self.max_tactic_len)
        else:
            lib = self.library_latents if self.library_latents is not None else torch.empty(0)
            strings = nn_decode(latents, lib.to(self.device), self.library_tactics)
        counts = Counter(strings)
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    @property
    def stats_dim(self) -> int:
        return len(self.stats.mean)

    def predict(self, example: Example, *, k: int) -> List[str]:
        text = build_input_text(example.theorem_statement, example.state_before)
        ranked = self.sample_candidates(text)
        return [t for t, _ in ranked[:k]]

    def predict_with_counts(self, example: Example) -> List[Tuple[str, int]]:
        text = build_input_text(example.theorem_statement, example.state_before)
        return self.sample_candidates(text)

    # ---- persistence ----

    @classmethod
    def load(
        cls,
        model_dir: Path,
        *,
        n_samples: int = 32,
        steps: int = 10,
        seed: int = 0,
        decode: str = "decoder",
        device: str = "cpu",
    ) -> "MiniElfBaseline":
        model_dir = Path(model_dir)
        cfg = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        embed_cfg = ElfEmbedConfig.from_dict(cfg["embed"])
        flow_cfg = FlowConfig.from_dict(cfg["flow"])
        vocab = Vocab.load(model_dir / "vocab.json")
        stats = LatentStats(mean=cfg["latent_mean"], std=cfg["latent_std"])

        ae = TacticAutoencoder(embed_cfg)
        cond_encoder = ConditionEncoder(embed_cfg)
        flow = FlowMLP(flow_cfg)
        embed_ckpt = torch.load(model_dir / "embed.pt", map_location=device)
        ae.load_state_dict(embed_ckpt["ae"])
        cond_encoder.load_state_dict(embed_ckpt["cond_encoder"])
        flow.load_state_dict(torch.load(model_dir / "flow_model.pt", map_location=device))

        lib_lat = None
        lib_tac: List[str] = []
        lib_path = model_dir / "tactic_library.json"
        if lib_path.exists():
            lib = json.loads(lib_path.read_text(encoding="utf-8"))
            lib_tac = lib.get("tactics", [])
            if lib.get("latents"):
                lib_lat = torch.tensor(lib["latents"], dtype=torch.float32)

        return cls(
            ae, cond_encoder, flow, vocab, stats,
            n_samples=n_samples, steps=steps, seed=seed, decode=decode,
            library_latents=lib_lat, library_tactics=lib_tac,
            max_tactic_len=embed_cfg.max_tactic_len, max_cond_len=embed_cfg.max_cond_len,
            device=device,
        )
