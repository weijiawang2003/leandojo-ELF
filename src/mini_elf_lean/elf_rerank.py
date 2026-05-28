"""Mini-ELF v1 — verifier-aware learned reranker.

v0's headline weakness is that its correct candidate is usually *present* in the
top-5 (high ``pass@5``) but not ranked first (``pass@1`` trails AR). The flow
ranks by raw sample frequency, which has no notion of validity. This module
learns to rank instead: a small CPU classifier scores

    (condition, candidate_tactic) -> P(candidate verifies)

from *previous Lean outcomes* — Lean-verified candidates are positives, Lean-
rejected candidates are negatives. It never calls Lean (it learns from the
already-collected traces) and never reads ``state_after``.

Two signal sources are fused:

  * **Char-GRU encoders** over the condition prompt and the candidate string.
  * **Hand features** (pure-Python, :func:`extract_features`): bracket balance,
    a *known-token ratio* that catches decoder garble like
    ``constructoontroctoo``, numeric witness/goal match, tactic head, and — the
    relational sibling signal — *conjunct / disjunct consistency* derived from
    :mod:`mini_elf_lean.elf_structure` (does ``exact h.1`` project the conjunct
    the goal actually needs? does ``Or.inl`` match the disjunct the hypothesis
    proves?).

The hand features are torch-free and unit-testable on their own; the model and
trainer live in a ``torch``-guarded block.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .ar_model import Vocab, build_input_text
from .elf_structure import parse_prompt

# Tactic heads we treat as "valid Lean tactic openings". A candidate whose first
# token is not one of these is flagged as a malformed prefix.
KNOWN_TACTIC_HEADS: Tuple[str, ...] = (
    "exact", "rfl", "constructor", "cases", "rcases", "intro", "intros", "apply",
    "refine", "simp", "left", "right", "assumption", "decide", "exists", "use",
    "trivial", "rintro", "obtain", "have", "show", "by",
)
# Subset used as an explicit one-hot in the feature vector (the rest fold into
# "other"). Order is stable — it defines feature-vector indices.
HEAD_ONEHOT: Tuple[str, ...] = (
    "exact", "rfl", "constructor", "cases", "rcases", "intro", "apply", "refine",
    "simp", "left", "right",
)
_HEAD_TO_IDX = {h: i for i, h in enumerate(HEAD_ONEHOT)}

# Left/right projection markers for the conjunct-consistency feature.
_LEFT_PROJ = (".1", ".left", "And.left", ".elim_left")
_RIGHT_PROJ = (".2", ".right", "And.right", ".elim_right")

# Lean library / constructor tokens a candidate may legitimately reference
# *without* them being local hypotheses. Anything else lowercase that the
# candidate references but the context does not bind is a hallucinated
# identifier (the dominant flow-decoder failure mode, e.g. `exact ⟨hp, hq⟩`
# when only `h` is in scope).
KNOWN_LIBRARY: frozenset = frozenset({
    "Or", "And", "Iff", "Eq", "Not", "True", "False", "Nat", "Prop", "Type",
    "inl", "inr", "intro", "mk", "mp", "mpr", "symm", "trans", "refl", "elim",
    "left", "right", "id", "fun", "comm", "of",
})

_NUMERIC_RE = re.compile(r"\d+")
_IDENT_RE = re.compile(r"[^\W\d][\w']*", re.UNICODE)
# Scalar features that precede the head one-hot. Keep in sync with extract_features.
_N_SCALAR = 11
# Feature vector = scalars ⊕ head one-hot ⊕ "other" head slot.
FEATURE_DIM = _N_SCALAR + len(HEAD_ONEHOT) + 1


# ---------------- pure-Python hand features ----------------


def _tactic_head(candidate: str) -> str:
    s = candidate.strip()
    if not s:
        return ""
    return s.split()[0].split(".")[0] if s.split() else ""


def _balanced(s: str, open_ch: str, close_ch: str) -> bool:
    depth = 0
    for ch in s:
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _projection_side(candidate: str) -> int:
    """+1 if the candidate uses a left conjunct projection, -1 if right, 0 none."""
    has_left = any(m in candidate for m in _LEFT_PROJ)
    has_right = any(m in candidate for m in _RIGHT_PROJ)
    if has_left and not has_right:
        return 1
    if has_right and not has_left:
        return -1
    return 0


def _disjunct_side(candidate: str, head: str) -> int:
    """+1 if candidate introduces the left disjunct, -1 right, 0 none.
    Covers both ``Or.inl``/``Or.inr`` terms and the ``left``/``right`` tactics."""
    has_inl = "Or.inl" in candidate or head == "left"
    has_inr = "Or.inr" in candidate or head == "right"
    if has_inl and not has_inr:
        return 1
    if has_inr and not has_inl:
        return -1
    return 0


def _binding_features(state, candidate: str) -> tuple:
    """``(binding_ratio, n_unbound)``. A *referenced* identifier is a lowercase
    candidate token that is neither a tactic head nor a known library token (so
    it ought to be a local hypothesis). ``binding_ratio`` = fraction of those
    that the context actually binds; ``n_unbound`` = count that it does not."""
    bound = {n for names, _ty in state.hyp_bindings for n in names}
    referenced = [
        t for t in _IDENT_RE.findall(candidate)
        if t and t[0].islower() and t not in KNOWN_LIBRARY and t not in KNOWN_TACTIC_HEADS
    ]
    if not referenced:
        return 1.0, 0
    n_bound = sum(1 for t in referenced if t in bound)
    n_unbound = len(referenced) - n_bound
    return n_bound / len(referenced), n_unbound


@dataclass
class FeatureResult:
    vector: List[float]
    debug: Dict[str, Any]


def extract_features(
    theorem_statement: str,
    state_before: str,
    candidate: str,
    *,
    known_tokens: Optional[set] = None,
    family: Optional[str] = None,
) -> FeatureResult:
    """Dense hand-feature vector + a debug dict for one (condition, candidate).

    ``known_tokens`` is the set of identifier tokens seen in *training* tactics;
    it powers the garble-catching ``known_token_ratio``. Reads only the prompt,
    never ``state_after``."""
    known_tokens = known_tokens or set()
    state = parse_prompt(theorem_statement, state_before, pattern_family=family)
    cand = candidate or ""

    head = _tactic_head(cand)
    malformed_prefix = 0.0 if head in KNOWN_TACTIC_HEADS else 1.0

    bal_angle = _balanced(cand, "⟨", "⟩")
    bal_paren = _balanced(cand, "(", ")")

    # incomplete constructor / dangling block: unbalanced angle brackets, or a
    # trailing argument-expecting head with nothing after it.
    stripped = cand.rstrip()
    dangling = stripped.split()[-1] in ("exact", "apply", "refine", "intro") if stripped.split() else False
    incomplete = 1.0 if (not bal_angle) or dangling else 0.0

    cand_idents = _IDENT_RE.findall(cand)
    known_ratio = (
        sum(1 for t in cand_idents if t in known_tokens) / len(cand_idents)
        if cand_idents else 0.0
    )

    cand_nums = set(_NUMERIC_RE.findall(cand))
    prompt_nums = set(state.numeric_literals)
    numeric_match = 1.0 if (cand_nums and cand_nums <= prompt_nums) else 0.0

    # Relational sibling signals.
    conjunct_consistency = 0.0
    if state.conjunction_hyps:
        side = _projection_side(cand)
        if side != 0:
            for _name, lhs, rhs in state.conjunction_hyps:
                if state.goal == lhs:
                    conjunct_consistency = 1.0 if side == 1 else -1.0
                    break
                if state.goal == rhs:
                    conjunct_consistency = 1.0 if side == -1 else -1.0
                    break

    disjunct_consistency = 0.0
    if state.goal_disjuncts is not None:
        a, b = state.goal_disjuncts
        side = _disjunct_side(cand, head)
        if side != 0:
            hyp_types = {ty for _names, ty in state.hyp_bindings}
            proves_a = a in hyp_types
            proves_b = b in hyp_types
            if side == 1 and proves_a:
                disjunct_consistency = 1.0
            elif side == -1 and proves_b:
                disjunct_consistency = 1.0
            elif side == 1 and proves_b:
                disjunct_consistency = -1.0
            elif side == -1 and proves_a:
                disjunct_consistency = -1.0

    binding_ratio, n_unbound = _binding_features(state, cand)

    scalars = [
        min(len(cand), 80) / 80.0,
        malformed_prefix,
        incomplete,
        1.0 if bal_angle else 0.0,
        1.0 if bal_paren else 0.0,
        known_ratio,
        numeric_match,
        conjunct_consistency,  # +1 right projection for goal, -1 wrong, 0 n/a
        disjunct_consistency,  # +1 correct Or.inl/inr/left/right, -1 wrong, 0 n/a
        binding_ratio,         # fraction of referenced idents bound in context
        1.0 if n_unbound else 0.0,  # any hallucinated (unbound) identifier
    ]
    assert len(scalars) == _N_SCALAR

    head_vec = [0.0] * (len(HEAD_ONEHOT) + 1)
    idx = _HEAD_TO_IDX.get(head)
    if idx is None:
        head_vec[-1] = 1.0  # "other"
    else:
        head_vec[idx] = 1.0

    vector = scalars + head_vec

    debug = {
        "candidate_length": len(cand),
        "tactic_head": head,
        "malformed_prefix": bool(malformed_prefix),
        "incomplete_block": bool(incomplete),
        "balanced_angle": bal_angle,
        "balanced_paren": bal_paren,
        "known_token_ratio": round(known_ratio, 3),
        "numeric_match": bool(numeric_match),
        "conjunct_consistency": conjunct_consistency,
        "disjunct_consistency": disjunct_consistency,
        "binding_ratio": round(binding_ratio, 3),
        "n_unbound_identifiers": n_unbound,
    }
    return FeatureResult(vector=vector, debug=debug)


def build_known_tokens(tactics: Sequence[str]) -> set:
    """Identifier tokens appearing in training tactics (the 'known vocabulary'
    the garble detector scores candidates against)."""
    toks: set = set()
    for t in tactics:
        toks.update(_IDENT_RE.findall(t))
    return toks


# ---------------- training examples ----------------


@dataclass
class RerankExample:
    theorem_statement: str
    state_before: str
    candidate: str
    label: int  # 1 = Lean-verified, 0 = Lean-rejected
    theorem_name: str = ""
    family: Optional[str] = None

    @property
    def condition_text(self) -> str:
        return build_input_text(self.theorem_statement, self.state_before)


def load_split_names(splits_path: Path, split: str) -> set:
    """Theorem names assigned to ``split`` in a ``theorem_splits.json``."""
    blob = json.loads(Path(splits_path).read_text(encoding="utf-8"))
    return set(blob.get(split, []))


def rerank_examples_from_traces(
    verified_path: Path,
    failed_path: Path,
    *,
    train_names: Optional[set] = None,
    family_map: Optional[Dict[str, str]] = None,
) -> List["RerankExample"]:
    """Build labelled reranker examples from collected Lean traces.

    Verified traces (``success=True``) are positives; failed traces are
    negatives. When ``train_names`` is given, only those theorems are kept (so
    the reranker never sees val/test theorems — the no-leakage invariant). The
    label comes from a *previous* Lean run; Lean is not invoked here, and
    ``state_after`` is never read."""
    from .io_utils import read_jsonl

    family_map = family_map or {}
    out: List[RerankExample] = []
    for path, label in ((verified_path, 1), (failed_path, 0)):
        for row in read_jsonl(path):
            name = row.get("theorem_name", "")
            if train_names is not None and name not in train_names:
                continue
            tactic = row.get("tactic", "")
            if not tactic:
                continue
            out.append(
                RerankExample(
                    theorem_statement=row.get("theorem_statement", ""),
                    state_before=row.get("state_before", ""),
                    candidate=tactic,
                    label=label,
                    theorem_name=name,
                    family=family_map.get(name),
                )
            )
    return out


# ---------------- torch model + reranker ----------------

try:  # pragma: no cover - exercised by import
    import torch
    import torch.nn as nn

    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch = None  # type: ignore
    nn = None  # type: ignore
    _TORCH_AVAILABLE = False


@dataclass
class RerankConfig:
    vocab_size: int = 0
    emb: int = 32
    cond_hidden: int = 32
    cand_hidden: int = 32
    mlp_hidden: int = 64
    feature_dim: int = FEATURE_DIM
    dropout: float = 0.1
    max_cond_len: int = 160
    max_cand_len: int = 80
    pad_id: int = 0
    # training
    epochs: int = 60
    lr: float = 3e-3
    batch: int = 32
    seed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RerankConfig":
        fields = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in fields})


if _TORCH_AVAILABLE:

    class RerankerModel(nn.Module):
        """Char-GRU(condition) ⊕ Char-GRU(candidate) ⊕ hand-features → logit."""

        def __init__(self, cfg: RerankConfig) -> None:
            super().__init__()
            self.cfg = cfg
            self.embedding = nn.Embedding(cfg.vocab_size, cfg.emb, padding_idx=cfg.pad_id)
            self.cond_gru = nn.GRU(cfg.emb, cfg.cond_hidden, batch_first=True, bidirectional=True)
            self.cand_gru = nn.GRU(cfg.emb, cfg.cand_hidden, batch_first=True, bidirectional=True)
            fused = 2 * cfg.cond_hidden + 2 * cfg.cand_hidden + cfg.feature_dim
            self.mlp = nn.Sequential(
                nn.Linear(fused, cfg.mlp_hidden), nn.SiLU(),
                nn.Dropout(cfg.dropout), nn.Linear(cfg.mlp_hidden, 1),
            )
            self.dropout = nn.Dropout(cfg.dropout)

        def _enc(self, gru, src, src_len):
            emb = self.dropout(self.embedding(src))
            packed = nn.utils.rnn.pack_padded_sequence(
                emb, src_len.cpu(), batch_first=True, enforce_sorted=False
            )
            _, hidden = gru(packed)
            return torch.cat([hidden[0], hidden[1]], dim=-1)

        def forward(self, cond_src, cond_len, cand_src, cand_len, feats):
            c = self._enc(self.cond_gru, cond_src, cond_len)
            a = self._enc(self.cand_gru, cand_src, cand_len)
            h = torch.cat([c, a, feats], dim=-1)
            return self.mlp(h).squeeze(-1)  # (B,) logits

    def _pad_batch(seqs: List[List[int]], pad_id: int):
        m = max((len(s) for s in seqs), default=1)
        m = max(m, 1)
        src = torch.tensor([s + [pad_id] * (m - len(s)) if s else [pad_id] for s in seqs],
                           dtype=torch.long)
        src_len = torch.tensor([max(len(s), 1) for s in seqs], dtype=torch.long)
        return src, src_len

    class Reranker:
        """Trainable wrapper: holds the model, vocab, known-token set, and config.

        Use :meth:`fit` on :class:`RerankExample` rows (no Lean), then
        :meth:`score` / :meth:`rank` candidates. Deterministic given the seed.
        """

        def __init__(self, model: "RerankerModel", vocab: Vocab, cfg: RerankConfig,
                     known_tokens: set, *, device: str = "cpu") -> None:
            self.model = model.to(device).eval()
            self.vocab = vocab
            self.cfg = cfg
            self.known_tokens = set(known_tokens)
            self.device = device

        # ---- featurization ----
        def _feat_vec(self, ex_stmt: str, ex_state: str, candidate: str, family=None) -> List[float]:
            return extract_features(
                ex_stmt, ex_state, candidate, known_tokens=self.known_tokens, family=family
            ).vector

        def _encode(self, examples: Sequence[RerankExample]):
            cond_ids = [self.vocab.encode_source(e.condition_text)[: self.cfg.max_cond_len]
                        for e in examples]
            cand_ids = [self.vocab.encode_source(e.candidate)[: self.cfg.max_cand_len]
                        for e in examples]
            feats = [self._feat_vec(e.theorem_statement, e.state_before, e.candidate, e.family)
                     for e in examples]
            cond_src, cond_len = _pad_batch(cond_ids, self.vocab.pad_id)
            cand_src, cand_len = _pad_batch(cand_ids, self.vocab.pad_id)
            feat_t = torch.tensor(feats, dtype=torch.float32)
            return (cond_src.to(self.device), cond_len, cand_src.to(self.device),
                    cand_len, feat_t.to(self.device))

        # ---- training ----
        @classmethod
        def fit(cls, examples: Sequence[RerankExample], cfg: RerankConfig,
                *, device: str = "cpu", log: Optional[List[Dict[str, Any]]] = None) -> "Reranker":
            import copy
            import random

            torch.manual_seed(cfg.seed)
            texts: List[str] = []
            tactics: List[str] = []
            for e in examples:
                texts.append(e.condition_text)
                texts.append(e.candidate)
                tactics.append(e.candidate)
            vocab = Vocab.build(texts)
            known = build_known_tokens([e.candidate for e in examples if e.label == 1])
            cfg.vocab_size = len(vocab)
            cfg.feature_dim = FEATURE_DIM
            model = RerankerModel(cfg)
            rr = cls(model, vocab, cfg, known, device=device)

            n_pos = sum(1 for e in examples if e.label == 1)
            n_neg = len(examples) - n_pos
            pos_weight = torch.tensor([max(n_neg, 1) / max(n_pos, 1)], dtype=torch.float32)
            crit = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
            opt = torch.optim.Adam(model.parameters(), lr=cfg.lr)
            labels_all = torch.tensor([float(e.label) for e in examples], dtype=torch.float32)

            # Precompute per-example char ids + hand features ONCE (the features
            # call regex parsing — recomputing them every epoch dominated runtime).
            cond_ids_all = [vocab.encode_source(e.condition_text)[: cfg.max_cond_len] for e in examples]
            cand_ids_all = [vocab.encode_source(e.candidate)[: cfg.max_cand_len] for e in examples]
            feat_t_all = torch.tensor(
                [rr._feat_vec(e.theorem_statement, e.state_before, e.candidate, e.family)
                 for e in examples],
                dtype=torch.float32, device=device,
            )

            rng = random.Random(cfg.seed)
            idx = list(range(len(examples)))

            for epoch in range(cfg.epochs):
                model.train()
                rng.shuffle(idx)
                total = 0.0
                for s in range(0, len(idx), cfg.batch):
                    bidx = idx[s : s + cfg.batch]
                    cond_src, cond_len = _pad_batch([cond_ids_all[i] for i in bidx], vocab.pad_id)
                    cand_src, cand_len = _pad_batch([cand_ids_all[i] for i in bidx], vocab.pad_id)
                    feats = feat_t_all[bidx]
                    logits = model(cond_src.to(device), cond_len, cand_src.to(device), cand_len, feats)
                    y = labels_all[bidx].to(device)
                    loss = crit(logits, y)
                    opt.zero_grad()
                    loss.backward()
                    nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    opt.step()
                    total += float(loss.item()) * len(bidx)
                if log is not None:
                    log.append({"stage": "rerank", "epoch": epoch,
                                "loss": round(total / max(len(idx), 1), 5)})
            model.eval()
            return rr

        # ---- inference ----
        @torch.no_grad()
        def score(self, theorem_statement: str, state_before: str, candidate: str,
                  *, family: Optional[str] = None) -> float:
            self.model.eval()
            ex = RerankExample(theorem_statement, state_before, candidate, 0, family=family)
            cond_src, cond_len, cand_src, cand_len, feats = self._encode([ex])
            logit = self.model(cond_src, cond_len, cand_src, cand_len, feats)
            return float(torch.sigmoid(logit)[0].item())

        @torch.no_grad()
        def score_batch(self, theorem_statement: str, state_before: str,
                        candidates: Sequence[str], *, family: Optional[str] = None) -> List[float]:
            if not candidates:
                return []
            self.model.eval()
            exs = [RerankExample(theorem_statement, state_before, c, 0, family=family)
                   for c in candidates]
            cond_src, cond_len, cand_src, cand_len, feats = self._encode(exs)
            logits = self.model(cond_src, cond_len, cand_src, cand_len, feats)
            return torch.sigmoid(logits).tolist()

        def rank(self, theorem_statement: str, state_before: str,
                 candidates: Sequence[str], *, family: Optional[str] = None) -> List[Tuple[str, float]]:
            """Deduplicate ``candidates`` (first occurrence wins) and return them
            sorted by score desc, ties broken by candidate string for stability."""
            seen: set = set()
            uniq: List[str] = []
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    uniq.append(c)
            scores = self.score_batch(theorem_statement, state_before, uniq, family=family)
            paired = list(zip(uniq, scores))
            paired.sort(key=lambda kv: (-kv[1], kv[0]))
            return paired

        def features_debug(self, theorem_statement: str, state_before: str, candidate: str,
                           *, family: Optional[str] = None) -> Dict[str, Any]:
            return extract_features(theorem_statement, state_before, candidate,
                                    known_tokens=self.known_tokens, family=family).debug

        # ---- persistence ----
        def save(self, out_dir: Path) -> None:
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            self.vocab.save(out_dir / "rerank_vocab.json")
            torch.save(self.model.state_dict(), out_dir / "rerank_model.pt")
            (out_dir / "rerank_config.json").write_text(
                json.dumps({"config": self.cfg.to_dict(),
                            "known_tokens": sorted(self.known_tokens)},
                           indent=2, sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )

        @classmethod
        def load(cls, model_dir: Path, *, device: str = "cpu") -> "Reranker":
            model_dir = Path(model_dir)
            blob = json.loads((model_dir / "rerank_config.json").read_text(encoding="utf-8"))
            cfg = RerankConfig.from_dict(blob["config"])
            vocab = Vocab.load(model_dir / "rerank_vocab.json")
            cfg.vocab_size = len(vocab)
            model = RerankerModel(cfg)
            model.load_state_dict(torch.load(model_dir / "rerank_model.pt", map_location=device))
            return cls(model, vocab, cfg, set(blob.get("known_tokens", [])), device=device)
