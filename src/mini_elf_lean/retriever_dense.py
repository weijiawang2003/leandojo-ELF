"""Mini-ELF v44 — DPR-style dense premise retriever (R1).

Dual encoder over the shared V38 trunk (non-causal, mean-pooled → L2-normalized embedding):
  query encoder  : state_before  → q
  premise encoder: premise signature → p
Trained contrastively (InfoNCE, in-batch + BM25 hard negatives) on (state → gold-used premise)
pairs from the LeanDojo train pool. Index = encoded 241k-premise pool (flat cosine; numpy matmul,
no FAISS needed at this scale). Same retrieve(query, topn, exclude) interface as BM25Retriever so
the oracle/e2e scripts are drop-in.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Sequence

import torch
import torch.nn as nn
import torch.nn.functional as F

from mini_elf_lean.v38_backbone import V38Config, V38Trunk
from mini_elf_lean.token_seq2seq_dataset import TokenVocab

ROOT = Path(__file__).resolve().parents[2]
PREM = ROOT / "data/v43/premises"


def mean_pool(h: torch.Tensor, pad_mask: torch.Tensor) -> torch.Tensor:
    # h: (B,T,D); pad_mask: (B,T) True where pad
    keep = (~pad_mask).float().unsqueeze(-1)
    s = (h * keep).sum(1)
    n = keep.sum(1).clamp_min(1.0)
    return s / n


class DualEncoder(nn.Module):
    """Two V38 trunks (query, premise) + projection; embeddings L2-normalized."""

    def __init__(self, cfg: V38Config, proj_dim: int = 256, shared: bool = False):
        super().__init__()
        self.cfg = cfg
        self.q_trunk = V38Trunk(cfg)
        self.p_trunk = self.q_trunk if shared else V38Trunk(cfg)
        self.q_proj = nn.Linear(cfg.d_model, proj_dim)
        self.p_proj = nn.Linear(cfg.d_model, proj_dim)

    def _enc(self, trunk, proj, ids):
        pad = ids == self.cfg.pad_id
        h = trunk(trunk.embed_tokens(ids), causal=False, key_padding_mask=pad)
        return F.normalize(proj(mean_pool(h, pad)), dim=-1)

    def encode_query(self, ids):
        return self._enc(self.q_trunk, self.q_proj, ids)

    def encode_premise(self, ids):
        return self._enc(self.p_trunk, self.p_proj, ids)


class DenseRetriever:
    """Inference wrapper: loads a trained DualEncoder + a precomputed premise index."""

    def __init__(self, ckpt: Path = None, index: Path = None, device: str = "cpu"):
        ckpt = Path(ckpt or ROOT / "outputs/v44/retriever/dual_encoder.pt")
        index = Path(index or ROOT / "outputs/v44/retriever/prem_index.pt")
        snap = torch.load(ckpt, map_location=device, weights_only=False)
        self.cfg = V38Config.from_dict(snap["cfg"])
        self.vocab = TokenVocab.load(Path(snap["vocab_dir"]) / "vocab.json")
        self.model = DualEncoder(self.cfg, proj_dim=snap["proj_dim"], shared=snap.get("shared", False)).to(device)
        self.model.load_state_dict(snap["state_dict"]); self.model.eval()
        idx = torch.load(index, map_location=device, weights_only=False)
        self.names = idx["names"]
        self.emb = idx["emb"].to(device)  # (N, proj) normalized
        self.device = device

    def _ids(self, text):
        c = self.vocab.encode_source(text)[:self.cfg.max_cond_len]
        return torch.tensor([c + [self.cfg.pad_id] * (self.cfg.max_cond_len - len(c))],
                            dtype=torch.long, device=self.device)

    @torch.no_grad()
    def retrieve(self, query: str, topn: int = 12, exclude: Sequence[str] = ()) -> List[str]:
        q = self.model.encode_query(self._ids(query))  # (1, proj)
        scores = (self.emb @ q.t()).squeeze(1)          # (N,)
        k = min(topn + len(exclude) + 1, scores.numel())
        top = torch.topk(scores, k).indices.tolist()
        ex = set(exclude)
        return [self.names[i] for i in top if self.names[i] not in ex][:topn]


__all__ = ["DualEncoder", "DenseRetriever", "mean_pool"]
