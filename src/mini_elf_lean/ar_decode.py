"""Decoding for the AR seq2seq tactic model: greedy + beam search, plus a
:class:`~mini_elf_lean.baselines.Baseline` adapter so the trained model plugs
straight into the existing lean-cli ``pass@k`` evaluation harness.

Beam search returns **deduplicated** decoded strings ranked by
length-normalized log-probability, which is what feeds ``predict(example, k)``
during evaluation. Both decoders call ``model.decode_step`` — the exact same
step used by teacher forcing — so there is no train/inference skew.

Greedy and beam search are deterministic: ``argmax``/``topk`` on CPU break ties
by index, Python's sort is stable, and we put the model in ``eval()`` mode so
dropout is off.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from .ar_model import Seq2Seq, Seq2SeqConfig, Vocab, build_input_text
from .baselines import Baseline, Example

try:  # pragma: no cover - import guard
    import torch

    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch = None  # type: ignore
    _TORCH_AVAILABLE = False


# ---------------- low-level decoders ----------------


def greedy_decode(model: "Seq2Seq", src_ids: Sequence[int], vocab: Vocab, *, max_len: int) -> str:
    """Argmax decoding. Returns the decoded tactic string (specials stripped,
    truncated at ``<eos>``)."""
    model.eval()
    device = next(model.parameters()).device
    src = torch.tensor([list(src_ids)], dtype=torch.long, device=device)
    src_len = torch.tensor([len(src_ids)], dtype=torch.long)
    out_ids: List[int] = []
    with torch.no_grad():
        enc_outputs, hidden, src_mask = model.encode(src, src_len)
        prev = torch.tensor([vocab.bos_id], dtype=torch.long, device=device)
        for _ in range(max_len):
            logits, hidden, _ = model.decode_step(prev, hidden, enc_outputs, src_mask)
            nxt = int(logits.argmax(dim=-1).item())
            if nxt == vocab.eos_id:
                break
            out_ids.append(nxt)
            prev = torch.tensor([nxt], dtype=torch.long, device=device)
    return vocab.decode_target(out_ids)


@dataclass
class _Beam:
    tokens: List[int]
    logprob: float
    hidden: "torch.Tensor"  # (num_layers, 1, H)


def _norm_score(beam: _Beam, length_penalty: float) -> float:
    # Exclude the leading <bos> from the length used for normalization.
    length = max(len(beam.tokens) - 1, 1)
    return beam.logprob / (length ** length_penalty)


def beam_search(
    model: "Seq2Seq",
    src_ids: Sequence[int],
    vocab: Vocab,
    *,
    beam_width: int = 5,
    max_len: int = 80,
    num_return: int = 5,
    length_penalty: float = 0.7,
) -> List[Tuple[str, float]]:
    """Return up to ``num_return`` ``(tactic_string, normalized_logprob)`` pairs,
    ranked best-first and **deduplicated by decoded string** (different token
    paths that render to the same tactic collapse to one)."""
    model.eval()
    device = next(model.parameters()).device
    src = torch.tensor([list(src_ids)], dtype=torch.long, device=device)
    src_len = torch.tensor([len(src_ids)], dtype=torch.long)
    with torch.no_grad():
        enc_outputs, dec_hidden, src_mask = model.encode(src, src_len)

    beams: List[_Beam] = [_Beam(tokens=[vocab.bos_id], logprob=0.0, hidden=dec_hidden)]
    completed: List[_Beam] = []

    for _ in range(max_len):
        active = [b for b in beams if b.tokens[-1] != vocab.eos_id]
        if not active:
            break
        prev = torch.tensor([b.tokens[-1] for b in active], dtype=torch.long, device=device)
        hid = torch.cat([b.hidden for b in active], dim=1)  # (L, A, H)
        a = len(active)
        enc_rep = enc_outputs.expand(a, -1, -1).contiguous()
        mask_rep = src_mask.expand(a, -1).contiguous()
        with torch.no_grad():
            logits, new_hidden, _ = model.decode_step(prev, hid, enc_rep, mask_rep)
            logprobs = torch.log_softmax(logits, dim=-1)  # (A, V)
            topv, topi = logprobs.topk(min(beam_width, logprobs.size(-1)), dim=-1)

        candidates: List[_Beam] = []
        for ai, b in enumerate(active):
            h_i = new_hidden[:, ai : ai + 1, :].contiguous()
            for j in range(topi.size(1)):
                tok = int(topi[ai, j].item())
                lp = float(topv[ai, j].item())
                candidates.append(_Beam(b.tokens + [tok], b.logprob + lp, h_i))

        candidates.sort(key=lambda bm: _norm_score(bm, length_penalty), reverse=True)
        beams = []
        for c in candidates:
            if c.tokens[-1] == vocab.eos_id:
                completed.append(c)
            else:
                beams.append(c)
            if len(beams) >= beam_width:
                break
        # Stop early once we have plenty of finished hypotheses and the best
        # remaining active beam cannot beat the best finished one.
        if completed and beams:
            best_done = max(_norm_score(c, length_penalty) for c in completed)
            best_active = max(_norm_score(c, length_penalty) for c in beams)
            if len(completed) >= num_return and best_active <= best_done:
                break

    # Anything still active at max_len counts as a (truncated) hypothesis.
    completed.extend(beams)
    completed.sort(key=lambda bm: _norm_score(bm, length_penalty), reverse=True)

    out: List[Tuple[str, float]] = []
    seen = set()
    for c in completed:
        s = vocab.decode_target(c.tokens[1:])  # drop <bos>
        if s in seen:
            continue
        seen.add(s)
        out.append((s, _norm_score(c, length_penalty)))
        if len(out) >= num_return:
            break
    return out


# ---------------- baseline adapter (plugs into baseline_eval.evaluate) ----------------


class ARGenerativeBaseline(Baseline):
    """Wraps a trained :class:`Seq2Seq` as a :class:`Baseline`.

    ``predict`` runs beam search and returns the top-k deduplicated generated
    tactic strings — including, potentially, strings that were never a training
    label (the open-vocabulary capability). ``fit`` is a no-op because the model
    is trained offline by :mod:`mini_elf_lean.ar_train`; use :meth:`load` to
    construct one from a model directory.
    """

    name = "ar_seq2seq"

    def __init__(
        self,
        model: "Seq2Seq",
        vocab: Vocab,
        config: Seq2SeqConfig,
        *,
        beam_width: int = 5,
        length_penalty: float = 0.7,
    ) -> None:
        self.model = model
        self.vocab = vocab
        self.config = config
        self.beam_width = beam_width
        self.length_penalty = length_penalty
        self.model.eval()

    @property
    def mode(self) -> str:
        return f"beam(width={self.beam_width},lp={self.length_penalty})"

    def fit(self, train) -> "ARGenerativeBaseline":  # noqa: ARG002 - model is pre-trained
        return self

    def _encode(self, example: Example) -> List[int]:
        text = build_input_text(example.theorem_statement, example.state_before)
        ids = self.vocab.encode_source(text)
        return ids[: self.config.max_input_len]

    def predict(self, example: Example, *, k: int) -> List[str]:
        src_ids = self._encode(example)
        beam = max(self.beam_width, k)
        results = beam_search(
            self.model, src_ids, self.vocab,
            beam_width=beam, max_len=self.config.max_output_len,
            num_return=k, length_penalty=self.length_penalty,
        )
        return [s for s, _ in results]

    def predict_with_scores(self, example: Example, *, k: int) -> List[Tuple[str, float]]:
        src_ids = self._encode(example)
        beam = max(self.beam_width, k)
        return beam_search(
            self.model, src_ids, self.vocab,
            beam_width=beam, max_len=self.config.max_output_len,
            num_return=k, length_penalty=self.length_penalty,
        )

    @classmethod
    def load(
        cls,
        model_dir: Path,
        *,
        beam_width: int = 5,
        length_penalty: float = 0.7,
        device: str = "cpu",
    ) -> "ARGenerativeBaseline":
        if not _TORCH_AVAILABLE:  # pragma: no cover - env guard
            raise RuntimeError("PyTorch is required to load the AR model.")
        model_dir = Path(model_dir)
        config = Seq2SeqConfig.load(model_dir / "config.json")
        vocab = Vocab.load(model_dir / "vocab.json")
        model = Seq2Seq(config)
        state = torch.load(model_dir / "model.pt", map_location=device)
        model.load_state_dict(state)
        model.to(device)
        model.eval()
        return cls(model, vocab, config, beam_width=beam_width, length_penalty=length_penalty)
