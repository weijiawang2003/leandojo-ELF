"""Candidate-source clients: Mock, ManualFile, Anthropic, OpenAI + a factory.

A *candidate source* proposes tactics; it never decides correctness. Every
client returns a :class:`CandidateBatch` so the collector can record provenance
(``source`` / ``model`` / ``prompt_style``) uniformly and then hand the raw
candidates to Lean for verification.

Design constraints:
- ``mock`` and ``manual-file`` require no network and no API key.
- Real clients (anthropic / openai) lazily import their SDK and read the key
  from the environment; importing this module never requires those SDKs.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Protocol

from .config import Settings
from .io_utils import JsonCache, hash_key, read_jsonl
from .prompt_templates import DEFAULT_PROMPT_STYLE, SYSTEM_PROMPT, build_user_prompt
from .schemas import ManualCandidateRecord, TheoremSeed
from .tactic_sanitizer import split_raw_output

logger = logging.getLogger(__name__)


@dataclass
class CandidateBatch:
    """Proposed candidates for one (seed, state) pair, plus provenance.

    ``candidates`` are discrete (already split) but NOT yet sanitized — the
    collector owns dedupe / forbidden-filtering so its summary counters stay
    authoritative.
    """

    candidates: List[str]
    source: str = "llm"
    prompt_style: Optional[str] = None
    model: str = "unknown"
    raw_output: Optional[str] = None


class LLMClient(Protocol):
    name: str
    model: str

    def propose_tactics(
        self,
        *,
        seed: TheoremSeed,
        state_before: str,
        num_candidates: int,
        prompt_style: Optional[str],
        temperature: Optional[float],
    ) -> CandidateBatch:
        """Propose candidate tactics for ``state_before``. Never verifies them."""
        ...


# ---------------- Mock ----------------


class MockLLMClient:
    """Deterministic candidate source used by tests and dry-runs.

    It ignores the network entirely and returns plausible toy tactics. The
    selection is lightly shaped by ``prompt_style`` so style plumbing is
    exercised end-to-end, and it deliberately emits one ``sorry`` so the
    forbidden-filter path is also tested.
    """

    name = "mock"

    _BANK: tuple[str, ...] = (
        "rfl",
        "exact h",
        "assumption",
        "trivial",
        "constructor",
        "intro h",
        "intros",
        "simp",
        "decide",
        "omega",
        "apply h",
        "rw [h]",
        "rcases h with ⟨a, b⟩",
    )
    _AUTOMATION = {"simp", "decide", "omega", "aesop", "linarith", "norm_num"}

    def __init__(self, model: str = "mock", seed: int = 0) -> None:
        self.model = model
        self._seed = seed

    def propose_tactics(
        self,
        *,
        seed: TheoremSeed,
        state_before: str,
        num_candidates: int,
        prompt_style: Optional[str],
        temperature: Optional[float] = None,
    ) -> CandidateBatch:
        import random

        bank = list(self._BANK)
        if prompt_style == "no_automation":
            bank = [t for t in bank if t.split()[0] not in self._AUTOMATION]
        rng = random.Random(hash((seed.theorem_name, state_before, temperature, self._seed)))
        k = min(num_candidates, len(bank))
        picks = rng.sample(bank, k=k)
        # Append a duplicate and a forbidden token so the sanitizer has work.
        raw_lines = list(picks) + [picks[0], "sorry"]
        raw = "\n".join(raw_lines)
        return CandidateBatch(
            candidates=split_raw_output(raw, prompt_style),
            source="llm",
            prompt_style=prompt_style or DEFAULT_PROMPT_STYLE,
            model=self.model,
            raw_output=raw,
        )


# ---------------- Manual file ----------------


class ManualFileLLMClient:
    """Serve candidates from a hand-written / agent-authored JSONL file.

    This is the bridge for "use Claude (or any tool) as the proposer": drop
    candidates into a JSONL file and let the collector verify them with Lean.

    Matching rule for a given ``(theorem_name, state_before)``:
      1. Exact match on both -> use it.
      2. Else, if exactly one record shares the ``theorem_name`` -> use it.
      3. Else -> return an empty batch and log a warning (never crash).
    """

    name = "manual-file"
    model = "manual-file"

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        # Index records by theorem_name, preserving file order.
        self._by_name: Dict[str, List[ManualCandidateRecord]] = defaultdict(list)
        self._loaded = 0
        if not self._path.exists():
            logger.warning("manual-file: candidates file not found: %s", self._path)
            return
        for row in read_jsonl(self._path):
            try:
                rec = ManualCandidateRecord.model_validate(row)
            except Exception as exc:  # noqa: BLE001 - tolerate bad rows, keep going
                logger.warning("manual-file: skipping invalid record (%s): %r", exc, row)
                continue
            self._by_name[rec.theorem_name].append(rec)
            self._loaded += 1
        logger.info(
            "manual-file: loaded %d candidate record(s) for %d theorem(s) from %s",
            self._loaded,
            len(self._by_name),
            self._path,
        )

    def _match(self, theorem_name: str, state_before: str) -> Optional[ManualCandidateRecord]:
        recs = self._by_name.get(theorem_name, [])
        if not recs:
            return None
        # 1. exact match on (name, state_before)
        for rec in recs:
            if rec.state_before is not None and rec.state_before == state_before:
                return rec
        # 2. theorem-name-only, only if unambiguous
        if len(recs) == 1:
            return recs[0]
        logger.warning(
            "manual-file: %d records for theorem %r but none match the current "
            "state_before; refusing to guess.",
            len(recs),
            theorem_name,
        )
        return None

    def propose_tactics(
        self,
        *,
        seed: TheoremSeed,
        state_before: str,
        num_candidates: int,
        prompt_style: Optional[str],
        temperature: Optional[float] = None,
    ) -> CandidateBatch:
        rec = self._match(seed.theorem_name, state_before)
        if rec is None:
            logger.warning(
                "manual-file: no candidates for theorem=%r state=%r",
                seed.theorem_name,
                state_before[:60],
            )
            return CandidateBatch(
                candidates=[],
                source="manual-file",
                prompt_style=prompt_style,
                model=self.model,
            )
        candidates = list(rec.candidates)[: num_candidates] if num_candidates else list(rec.candidates)
        return CandidateBatch(
            candidates=candidates,
            source=rec.source or "manual-file",
            prompt_style=rec.prompt_style or prompt_style,
            model=self.model,
            raw_output=None,
        )


# ---------------- Real API clients ----------------


class _CachedChatClient:
    """Shared raw-text proposal + on-disk cache logic for API clients."""

    name = "api"

    def __init__(self, *, model: str, cache: Optional[JsonCache]) -> None:
        self.model = model
        self._cache = cache

    def _complete(self, *, system: str, user: str, temperature: float) -> str:  # pragma: no cover
        raise NotImplementedError

    def propose_tactics(
        self,
        *,
        seed: TheoremSeed,
        state_before: str,
        num_candidates: int,
        prompt_style: Optional[str],
        temperature: Optional[float],
    ) -> CandidateBatch:
        temp = 0.7 if temperature is None else temperature
        user_prompt = build_user_prompt(
            theorem_name=seed.theorem_name,
            theorem_statement=seed.theorem_statement,
            state_before=state_before,
            num_candidates=num_candidates,
            prompt_style=prompt_style,
        )

        cache_key: Optional[str] = None
        text_out: Optional[str] = None
        if self._cache is not None:
            cache_key = hash_key(
                self.name, self.model, str(temp), str(num_candidates),
                prompt_style or "", SYSTEM_PROMPT, user_prompt,
            )
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug("%s cache hit for %s", self.name, seed.theorem_name)
                text_out = cached["text"]

        if text_out is None:
            logger.debug("Calling %s model=%s temp=%.2f", self.name, self.model, temp)
            text_out = self._complete(system=SYSTEM_PROMPT, user=user_prompt, temperature=temp)
            if self._cache is not None and cache_key is not None:
                self._cache.put(cache_key, {"text": text_out})

        return CandidateBatch(
            candidates=split_raw_output(text_out, prompt_style),
            source="llm",
            prompt_style=prompt_style or DEFAULT_PROMPT_STYLE,
            model=self.model,
            raw_output=text_out,
        )


class AnthropicLLMClient(_CachedChatClient):
    """Anthropic Claude client. Lazily imports `anthropic`."""

    name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        api_key: Optional[str],
        cache: Optional[JsonCache] = None,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "AnthropicLLMClient requires an API key. Set ANTHROPIC_API_KEY "
                "or switch MINI_ELF_LLM_BACKEND=mock."
            )
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError(
                "The 'anthropic' package is not installed. `pip install anthropic`."
            ) from exc
        super().__init__(model=model, cache=cache)
        self._client = Anthropic(api_key=api_key)

    def _complete(self, *, system: str, user: str, temperature: float) -> str:  # pragma: no cover
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=512,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts: List[str] = []
        for block in msg.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()


class OpenAILLMClient(_CachedChatClient):
    """OpenAI-compatible chat client. Lazily imports `openai`.

    Works against any OpenAI-compatible endpoint via ``OPENAI_BASE_URL``.
    """

    name = "openai"

    def __init__(
        self,
        *,
        model: str,
        api_key: Optional[str],
        base_url: Optional[str] = None,
        cache: Optional[JsonCache] = None,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "OpenAILLMClient requires an API key. Set OPENAI_API_KEY (or "
                "MINI_ELF_OPENAI_API_KEY) or switch MINI_ELF_LLM_BACKEND=mock."
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The 'openai' package is not installed. `pip install openai`."
            ) from exc
        super().__init__(model=model, cache=cache)
        self._client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

    def _complete(self, *, system: str, user: str, temperature: float) -> str:  # pragma: no cover
        resp = self._client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            max_tokens=512,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()


# ---------------- Factory ----------------


def get_llm_client(
    settings: Settings,
    *,
    cache: Optional[JsonCache] = None,
    manual_candidates_path: Optional[str | os.PathLike[str]] = None,
) -> LLMClient:
    """Construct the candidate-source client named by ``settings.llm_backend``.

    Backends: ``mock`` | ``manual-file`` | ``anthropic`` | ``openai``.
    """

    backend = settings.llm_backend.lower().strip().replace("_", "-")
    if backend == "mock":
        return MockLLMClient(model="mock")
    if backend == "manual-file":
        if not manual_candidates_path:
            raise ValueError(
                "manual-file backend requires --manual-candidates PATH "
                "(path to a candidate JSONL file)."
            )
        return ManualFileLLMClient(manual_candidates_path)
    if backend == "anthropic":
        return AnthropicLLMClient(
            model=settings.llm_model,
            api_key=settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"),
            cache=cache,
        )
    if backend == "openai":
        return OpenAILLMClient(
            model=settings.llm_model,
            api_key=settings.openai_api_key or os.environ.get("OPENAI_API_KEY"),
            base_url=settings.openai_base_url,
            cache=cache,
        )
    raise ValueError(
        f"Unknown LLM backend: {settings.llm_backend!r}. "
        "Expected one of: mock, manual-file, anthropic, openai."
    )


# Backwards-compatible alias.
build_llm_client = get_llm_client
