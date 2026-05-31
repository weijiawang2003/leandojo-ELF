"""Mini-ELF v8 — generative proof-block proposer.

Wraps the existing AR encoder-decoder (:mod:`.ar_model`, :mod:`.ar_train`,
:mod:`.ar_decode`) into a :class:`ProofBlockSeq2SeqProposer` that fits the
unified :class:`~mini_elf_lean.proposer.CandidateProposer` interface so v8's
fusion eval can mix it with v7 retrieval, the symbolic planner, witness-copy,
and (key-permitting) the LLM proposer.

What is genuinely new vs the v0/v1 AR baseline:

  * The dataset is the **proof-block** set (the v2 dataset_builder's
    ``next_tactic.jsonl`` schema, but pooled across basic / hard /
    planner_blind) — see :mod:`.proof_block_dataset`. The same model can be
    trained under ``interpolation``, ``family_holdout/<fam>``,
    ``operation_holdout/<op>``, and ``donorless_eval`` without changing code.
  * Inference returns the **top-k beam list** wrapped as
    :class:`ProposedCandidate` so the fusion ranker can read it uniformly.
  * Source label is ``proof_block_seq2seq``; outputs carry beam_score in
    metadata so the v8 fusion can preserve the model's own ranking.

Honest scope (unchanged):

  * Inputs are ``theorem_statement + "\\n" + state_before`` only — the same
    text the v0 AR model used.  ``state_after`` is never read.
  * The model is small (default emb=64 / hidden=128 / 1 layer) and CPU-only.
  * It can in principle generate strings outside the training label set
    (open vocabulary at the character level), but whether it does is an
    empirical question; v8 reports the answer rather than claiming it.

The module is import-safe without torch (the wrapper has a ``torch_available()``
class method); training and inference paths gate on torch the same way
:mod:`.ar_model` does.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .proposer import CandidateProposer, ProposedCandidate
from .proof_block_dataset import ProofBlockRow

logger = logging.getLogger(__name__)

PROOF_BLOCK_SEQ2SEQ_SOURCE = "proof_block_seq2seq"


# --------------------------------------------------------------------------- #
# Row → Example shim
# --------------------------------------------------------------------------- #

def proof_blocks_to_examples(rows: Sequence[Dict[str, Any]]):
    """Convert proof-block dict rows to :class:`baselines.Example` records.
    Kept thin so this module can be imported without torch — the import of
    Example is done lazily."""
    from .baselines import Example  # noqa: WPS433 - lazy: avoid hard torch dep
    out = []
    for r in rows:
        out.append(Example(
            theorem_name=r["theorem_name"],
            theorem_statement=r["theorem_statement"],
            state_before=r["state_before"],
            tactic=r["tactic"],
            split=r.get("split", "train"),
        ))
    return out


def load_proof_block_regime(regime_dir: Path):
    """Load ``train.jsonl`` (+ optional ``val.jsonl`` / ``test.jsonl``) from a
    proof_blocks regime directory; returns ``(train, val, test)`` Example
    lists. Missing files yield empty lists (operation_holdout has no ``val``,
    that is expected)."""
    def _load(p: Path):
        if not p.exists():
            return []
        rows = []
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                rows.append(json.loads(s))
        return proof_blocks_to_examples(rows)
    return _load(regime_dir / "train.jsonl"), \
           _load(regime_dir / "val.jsonl"), \
           _load(regime_dir / "test.jsonl")


# --------------------------------------------------------------------------- #
# Proposer wrapper (CandidateProposer-compatible)
# --------------------------------------------------------------------------- #

@dataclass
class ProofBlockSeq2SeqArtifacts:
    """Filenames inside a saved model dir (matches what
    :func:`ar_train.save_artifacts` writes)."""
    model_pt: str = "model.pt"
    vocab_json: str = "vocab.json"
    config_json: str = "config.json"
    train_log_jsonl: str = "train_log.jsonl"


def torch_available() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except Exception:
        return False


class ProofBlockSeq2SeqProposer(CandidateProposer):
    """The v8 generative proposer.

    Usage:

        prop = ProofBlockSeq2SeqProposer.from_saved(model_dir)
        cands = prop.propose(theorem_statement, state_before, top_k=10)

    The model is loaded lazily on the first call so importing this class is
    cheap (no torch required at import).
    """

    SOURCE = PROOF_BLOCK_SEQ2SEQ_SOURCE

    def __init__(self,
                 model_dir: Path,
                 *,
                 beam_width: int = 10,
                 length_penalty: float = 0.7,
                 max_output_len: int = 80) -> None:
        self.model_dir = Path(model_dir)
        self.beam_width = beam_width
        self.length_penalty = length_penalty
        self.max_output_len = max_output_len
        self._model = None  # lazy
        self._vocab = None
        self._cfg = None

    @classmethod
    def from_saved(cls, model_dir: Path, **kw) -> "ProofBlockSeq2SeqProposer":
        return cls(Path(model_dir), **kw)

    def available(self) -> bool:
        if not torch_available():
            return False
        return (self.model_dir / "model.pt").exists() and \
               (self.model_dir / "vocab.json").exists()

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        if not torch_available():
            raise RuntimeError("torch not available; cannot load seq2seq model")
        import torch
        from .ar_model import Seq2Seq, Seq2SeqConfig, Vocab
        vocab_path = self.model_dir / "vocab.json"
        config_path = self.model_dir / "config.json"
        model_path = self.model_dir / "model.pt"
        vocab_data = json.loads(vocab_path.read_text(encoding="utf-8"))
        if isinstance(vocab_data, dict) and "itos" in vocab_data:
            vocab = Vocab(itos=vocab_data["itos"])
        else:
            vocab = Vocab(itos=vocab_data)
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        # Accept either a flat dict or {"model": ..., "train": ...}
        if "model" in cfg:
            model_cfg = cfg["model"]
        else:
            model_cfg = {k: v for k, v in cfg.items()
                         if k in {"vocab_size", "embedding_dim", "hidden_dim",
                                  "num_layers", "bidirectional_encoder",
                                  "attention_dim", "dropout"}}
        # vocab_size must match the saved vocab regardless of what's in config
        model_cfg["vocab_size"] = len(vocab.itos)
        model = Seq2Seq(Seq2SeqConfig(**model_cfg))
        state = torch.load(model_path, map_location="cpu")
        model.load_state_dict(state)
        model.eval()
        self._model = model
        self._vocab = vocab
        self._cfg = cfg

    def propose(self,
                theorem_statement: str,
                state_before: str,
                *,
                theorem_name: Optional[str] = None,
                top_k: int = 10,
                **kwargs: Any) -> List[ProposedCandidate]:
        if not self.available():
            return []
        self._ensure_loaded()
        from .ar_decode import beam_search
        from .ar_model import build_input_text
        model = self._model
        vocab = self._vocab
        text = build_input_text(theorem_statement, state_before)
        # encode_source returns ints; the model handles its own truncation in
        # the encoder forward pass.
        src_ids = vocab.encode_source(text)
        beams = beam_search(
            model, src_ids, vocab,
            beam_width=max(self.beam_width, top_k),
            max_len=self.max_output_len,
            num_return=top_k,
            length_penalty=self.length_penalty,
        )
        # `beam_search` returns a ranked list of (tactic_str, score) tuples or
        # similar; normalise:
        results: List[ProposedCandidate] = []
        for i, beam in enumerate(beams):
            if isinstance(beam, tuple) and len(beam) == 2:
                tac, score = beam
            else:
                tac = beam
                score = -float(i)
            tac = (tac or "").strip()
            if not tac:
                continue
            results.append(ProposedCandidate(
                tactic=tac,
                source=self.SOURCE,
                metadata={
                    "beam_rank": i,
                    "beam_score": float(score),
                    "model_dir": str(self.model_dir),
                },
            ))
            if len(results) >= top_k:
                break
        return results


__all__ = [
    "PROOF_BLOCK_SEQ2SEQ_SOURCE",
    "ProofBlockSeq2SeqProposer",
    "proof_blocks_to_examples",
    "load_proof_block_regime",
    "torch_available",
]
