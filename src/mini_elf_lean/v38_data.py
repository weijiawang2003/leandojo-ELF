"""Mini-ELF v38 — shared dataset / vocab / batching for ALL three families.

One dataset, one TokenVocab (reused from the v35 build — NOT rebuilt), one test
tier, so A/B/C are matched at the data level. Sequences are fixed-length prefix-LM
layout ``[cond: max_cond_len][tgt: max_tgt_len]`` so target positions are at
constant indices across examples (clean separation, simple positions). Padding is
right-pad within each segment; a per-position key-padding mask covers it.

Guardrails: condition is ``theorem_statement`` + ``state_before`` only
(``state_after`` never read); the test tier is the 24-theorem Mathlib split used
by v35–v37 (dedup by (theorem_name, state_before), file order, capped); the
vocabulary is the train-only TokenVocab from the v35 build.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import torch

from .baselines import Example, oracle_verified_lookup
from .token_seq2seq_dataset import TokenVocab, build_input_text

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed" / "v35_elf_flow"


def read_rows(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()] if Path(path).exists() else []


def load_dataset(data_dir: Path = DATA) -> Dict[str, Any]:
    vocab = TokenVocab.load(data_dir / "vocab.json")
    manifest = json.loads((data_dir / "manifest.json").read_text())
    train = read_rows(data_dir / "train.jsonl")
    val = read_rows(data_dir / "val.jsonl")
    test = read_rows(data_dir / "test.jsonl")
    return {"vocab": vocab, "manifest": manifest, "train": train, "val": val, "test": test}


def gold_lookup(all_rows: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], frozenset]:
    ex = [Example(r["theorem_name"], r["theorem_statement"], r["state_before"], r["tactic"], r.get("split", "train")) for r in all_rows]
    return oracle_verified_lookup(ex)


def dedup_by_state(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for r in rows:
        k = (r["theorem_name"], r["state_before"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def mathlib_test_tier(test_rows: Sequence[Dict[str, Any]], cap: int = 24) -> List[Dict[str, Any]]:
    ml = [r for r in dedup_by_state(test_rows) if r.get("tier") == "mathlib"]
    return ml[:cap] if cap else ml


def make_batch(rows: Sequence[Dict[str, Any]], vocab: TokenVocab, *,
               max_cond_len: int, max_tgt_len: int, device: str = "cpu") -> Dict[str, torch.Tensor]:
    """Fixed-length prefix-LM batch. Returns cond_ids/cond_pad (B,Sc) and
    tgt_ids/tgt_pad (B,Tt); tgt_ids = [bos … eos] right-padded with pad_id."""
    B = len(rows)
    pad = vocab.pad_id
    cond = torch.full((B, max_cond_len), pad, dtype=torch.long)
    tgt = torch.full((B, max_tgt_len), pad, dtype=torch.long)
    for i, r in enumerate(rows):
        c = (r.get("cond_ids") or vocab.encode_source(build_input_text(r["theorem_statement"], r["state_before"])))[:max_cond_len]
        cond[i, : len(c)] = torch.tensor(c, dtype=torch.long)
        t = (r.get("tgt_ids") or vocab.encode_target(r["tactic"]))[:max_tgt_len]
        if t[-1] != vocab.eos_id and len(t) == max_tgt_len:
            t = t[: max_tgt_len - 1] + [vocab.eos_id]
        tgt[i, : len(t)] = torch.tensor(t, dtype=torch.long)
    cond = cond.to(device)
    tgt = tgt.to(device)
    return {"cond_ids": cond, "cond_pad": cond == pad, "tgt_ids": tgt, "tgt_pad": tgt == pad}


def cond_ids_for(row: Dict[str, Any], vocab: TokenVocab, *, max_cond_len: int, device: str = "cpu") -> torch.Tensor:
    """Condition ids padded to ``max_cond_len`` (fixed prefix length) so target
    positions match training (where make_batch pads cond to the same length)."""
    c = (row.get("cond_ids") or vocab.encode_source(build_input_text(row["theorem_statement"], row["state_before"])))[:max_cond_len]
    ids = list(c) + [vocab.pad_id] * (max_cond_len - len(c))
    return torch.tensor([ids], dtype=torch.long, device=device)


__all__ = ["load_dataset", "gold_lookup", "dedup_by_state", "mathlib_test_tier",
           "make_batch", "cond_ids_for", "read_rows", "DATA"]
