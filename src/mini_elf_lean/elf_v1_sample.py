"""Mini-ELF v1 — sampling, candidate fusion, and reranked decoding.

Pipeline per prompt:

  1. Draw ``n_samples`` Gaussian noises, integrate the conditional flow (Euler),
     un-standardize, and decode each latent with the AE decoder (generative) or
     the nearest-neighbour ablation. → ``flow_decoder`` / ``nn_decode`` candidates.
  2. Optionally add **witness-copy** candidates (:mod:`mini_elf_lean.elf_witness`)
     for existential goals. → ``witness_copy`` candidates.
  3. Merge + deduplicate (first source wins).
  4. Rank: by the learned **reranker** score when enabled, else by flow sampling
     frequency. The verifier then checks the top-k.

Every candidate carries a ``candidate_source`` and (when reranked) a score, so
``predictions.jsonl`` is fully auditable. Conditioning uses the v1
:class:`~mini_elf_lean.elf_structure.StructuredConditionEncoder`. Theorem-level,
``state_after`` never read.
"""

from __future__ import annotations

import json
import zlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import torch

from .ar_model import Vocab, build_input_text
from .baselines import Baseline, Example
from .elf_embed import ElfEmbedConfig, TacticAutoencoder
from .elf_flow import FlowConfig, FlowMLP
from .elf_sample import (
    LatentStats,
    decode_with_decoder,
    euler_integrate,
    nn_decode,
    unstandardize,
)
from .elf_structure import (
    NUMERIC_FEATURE_DIM,
    StructuredConditionEncoder,
    structured_inputs_from_prompts,
)
from .elf_witness import WITNESS_SOURCE, witness_candidates_for

FLOW_SOURCE = "flow_decoder"
NN_SOURCE = "nn_decode"


@dataclass
class StructuredCondConfig:
    vocab_size: int
    cond_dim: int = 128
    emb: int = 48
    raw_hidden: int = 128
    goal_hidden: int = 48
    shape_dim: int = 8
    num_feat_dim: int = NUMERIC_FEATURE_DIM
    dropout: float = 0.1
    pad_id: int = 0
    max_goal_len: int = 80

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StructuredCondConfig":
        fields = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in fields})

    def build_encoder(self) -> StructuredConditionEncoder:
        return StructuredConditionEncoder(
            vocab_size=self.vocab_size, cond_dim=self.cond_dim, emb=self.emb,
            raw_hidden=self.raw_hidden, goal_hidden=self.goal_hidden,
            shape_dim=self.shape_dim, num_feat_dim=self.num_feat_dim,
            dropout=self.dropout, pad_id=self.pad_id,
        )


class MiniElfV1Baseline(Baseline):
    """Mini-ELF v1 generator behind the :class:`Baseline` interface.

    Modes are controlled by ``decode`` (``"decoder"``/``"nn"``), ``use_witness``,
    and ``use_reranker``. A ``reranker`` (optional
    :class:`~mini_elf_lean.elf_rerank.Reranker`) must be supplied to enable
    reranking. ``fit`` is a no-op — models are trained offline.
    """

    name = "mini_elf_v1"

    def __init__(
        self,
        ae: TacticAutoencoder,
        cond_encoder: StructuredConditionEncoder,
        flow: FlowMLP,
        vocab: Vocab,
        stats: LatentStats,
        *,
        cond_cfg: StructuredCondConfig,
        n_samples: int = 64,
        steps: int = 10,
        seed: int = 0,
        decode: str = "decoder",
        use_witness: bool = False,
        use_reranker: bool = False,
        reranker=None,
        rerank_pool: int = 16,
        rerank_blend: float = 0.15,
        library_latents: Optional[torch.Tensor] = None,
        library_tactics: Optional[Sequence[str]] = None,
        max_tactic_len: int = 80,
        max_cond_len: int = 160,
        device: str = "cpu",
    ) -> None:
        if decode not in ("decoder", "nn"):
            raise ValueError(f"decode must be 'decoder' or 'nn', got {decode!r}")
        if use_reranker and reranker is None:
            raise ValueError("use_reranker=True requires a reranker instance")
        self.ae = ae.eval()
        self.cond_encoder = cond_encoder.eval()
        self.flow = flow.eval()
        self.vocab = vocab
        self.stats = stats
        self.cond_cfg = cond_cfg
        self.n_samples = n_samples
        self.steps = steps
        self.seed = seed
        self.decode = decode
        self.use_witness = use_witness
        self.use_reranker = use_reranker
        self.reranker = reranker
        self.rerank_pool = rerank_pool
        self.rerank_blend = rerank_blend
        self.library_latents = library_latents
        self.library_tactics = list(library_tactics) if library_tactics is not None else []
        self.max_tactic_len = max_tactic_len
        self.max_cond_len = max_cond_len
        self.device = device
        self._mean, self._std = stats.tensors(device)

    @property
    def mode(self) -> str:
        bits = [f"samples={self.n_samples}", f"steps={self.steps}", f"decode={self.decode}"]
        if self.use_witness:
            bits.append("witness")
        bits.append("rerank" if self.use_reranker else "freq")
        return "flow_v1(" + ",".join(bits) + ")"

    def fit(self, train) -> "MiniElfV1Baseline":  # noqa: ARG002 - pre-trained
        return self

    @property
    def _stats_dim(self) -> int:
        return len(self.stats.mean)

    def _condition(self, theorem_statement: str, state_before: str) -> torch.Tensor:
        inputs = structured_inputs_from_prompts(
            [(theorem_statement, state_before)], self.vocab,
            self.max_cond_len, self.cond_cfg.max_goal_len, self.device,
        )
        with torch.no_grad():
            return self.cond_encoder(*inputs)  # (1, cond_dim)

    def _flow_candidates(self, theorem_statement: str, state_before: str) -> List[Tuple[str, int]]:
        """``(tactic, count)`` from the conditional flow, sorted by count desc."""
        text = build_input_text(theorem_statement, state_before)
        c = self._condition(theorem_statement, state_before).expand(self.n_samples, -1).contiguous()
        g = torch.Generator(device=self.device)
        g.manual_seed((self.seed ^ zlib.crc32(text.encode("utf-8"))) & 0x7FFFFFFF)
        eps = torch.randn(self.n_samples, self._stats_dim, generator=g, device=self.device)
        x_std = euler_integrate(self.flow, eps, c, steps=self.steps)
        latents = unstandardize(x_std, self._mean, self._std)
        if self.decode == "decoder":
            strings = decode_with_decoder(self.ae, latents, self.vocab, max_len=self.max_tactic_len)
        else:
            lib = self.library_latents if self.library_latents is not None else torch.empty(0)
            strings = nn_decode(latents, lib.to(self.device), self.library_tactics)
        counts = Counter(s for s in strings if s.strip())
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def ranked_candidates(self, example: Example) -> List[Dict[str, Any]]:
        """Full ranked candidate list with provenance. Each item:
        ``{"tactic", "source", "sample_count", "reranker_score"}``.

        Without a reranker: pure flow sample-frequency order (witnesses appended).
        With a reranker: only a *shortlist* — the top ``rerank_pool`` flow
        candidates by frequency plus all witness candidates — is reordered by a
        frequency-**blended** reranker score; the remaining flow candidates keep
        their frequency order after it. This bounds the reordering so reranking
        can lift the right candidate to rank 1 without pushing recall out of the
        top-5 (the failure mode of reranking the whole list)."""
        flow = self._flow_candidates(example.theorem_statement, example.state_before)
        src = NN_SOURCE if self.decode == "nn" else FLOW_SOURCE
        seen: set = set()
        flow_items: List[Dict[str, Any]] = []
        for tac, cnt in flow:
            if tac in seen:
                continue
            seen.add(tac)
            flow_items.append({"tactic": tac, "source": src, "sample_count": cnt,
                               "reranker_score": None})

        witness_items: List[Dict[str, Any]] = []
        if self.use_witness:
            family = getattr(example, "pattern_family", None)
            for tac in witness_candidates_for(example.theorem_statement, example.state_before, family):
                if tac in seen:
                    continue
                seen.add(tac)
                witness_items.append({"tactic": tac, "source": WITNESS_SOURCE,
                                      "sample_count": 0, "reranker_score": None})

        if not (self.use_reranker and self.reranker is not None):
            # frequency ranking; witnesses (count 0) trail in stable string order.
            return sorted(flow_items + witness_items,
                          key=lambda it: (-it["sample_count"], it["tactic"]))

        pool = flow_items[: self.rerank_pool] + witness_items
        tail = flow_items[self.rerank_pool :]
        family = getattr(example, "pattern_family", None)
        scores = self.reranker.score_batch(
            example.theorem_statement, example.state_before,
            [it["tactic"] for it in pool], family=family,
        )
        max_cnt = max((it["sample_count"] for it in pool), default=0) or 1
        for it, sc in zip(pool, scores):
            it["reranker_score"] = float(sc)
            # blended score: reranker dominates, flow frequency breaks near-ties
            # toward the model's confident pick (witnesses have count 0 and rely
            # purely on the reranker's structural features, e.g. numeric_match).
            it["_blend"] = sc + self.rerank_blend * (it["sample_count"] / max_cnt)
        pool.sort(key=lambda it: (-it["_blend"], it["tactic"]))
        for it in pool:
            it.pop("_blend", None)
        return pool + tail

    def predict(self, example: Example, *, k: int) -> List[str]:
        return [it["tactic"] for it in self.ranked_candidates(example)[:k]]

    def predict_with_neighbors(
        self, example: Example, *, k: int
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """``(predictions, provenance)`` so the eval harness can record the
        candidate source + reranker score for each top-k tactic."""
        ranked = self.ranked_candidates(example)[:k]
        preds = [it["tactic"] for it in ranked]
        prov = [{"source": it["source"], "reranker_score": it["reranker_score"],
                 "sample_count": it["sample_count"]} for it in ranked]
        return preds, prov

    def distinct_flow_candidates(self, example: Example) -> int:
        return len(self._flow_candidates(example.theorem_statement, example.state_before))

    # ---- persistence ----

    @classmethod
    def load(
        cls,
        model_dir: Path,
        *,
        n_samples: int = 64,
        steps: int = 10,
        seed: int = 0,
        decode: str = "decoder",
        use_witness: bool = False,
        use_reranker: bool = False,
        device: str = "cpu",
    ) -> "MiniElfV1Baseline":
        model_dir = Path(model_dir)
        cfg = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        embed_cfg = ElfEmbedConfig.from_dict(cfg["embed"])
        flow_cfg = FlowConfig.from_dict(cfg["flow"])
        cond_cfg = StructuredCondConfig.from_dict(cfg["structured_cond"])
        vocab = Vocab.load(model_dir / "vocab.json")
        stats = LatentStats(mean=cfg["latent_mean"], std=cfg["latent_std"])

        ae = TacticAutoencoder(embed_cfg)
        cond_encoder = cond_cfg.build_encoder()
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

        reranker = None
        if use_reranker:
            from .elf_rerank import Reranker

            reranker = Reranker.load(model_dir, device=device)

        return cls(
            ae, cond_encoder, flow, vocab, stats, cond_cfg=cond_cfg,
            n_samples=n_samples, steps=steps, seed=seed, decode=decode,
            use_witness=use_witness, use_reranker=use_reranker, reranker=reranker,
            library_latents=lib_lat, library_tactics=lib_tac,
            max_tactic_len=embed_cfg.max_tactic_len, max_cond_len=embed_cfg.max_cond_len,
            device=device,
        )
