"""Mini-ELF v5 — an optional, API-key-gated LLM proof-block proposer.

The one candidate source that could solve a planner-blind family with **no**
same-shape donor: ask an LLM for short core-Lean tactic blocks. It is wrapped in
the same :class:`~mini_elf_lean.proposer.CandidateProposer` interface as every
other source so the unified eval treats it uniformly, and it **skips cleanly**
(``available()`` is ``False``, ``propose`` returns ``[]``) when no API key is
configured — the pilot is never faked.

Prompt contract (Part 3): given the theorem statement + tactic state, return a
**JSON list of tactic-block strings**, core Lean only (no Mathlib), short proofs,
no prose. Optional few-shot examples may be passed in, but the caller must
exclude the test theorem itself.

Honest scope: theorem-level only; the LLM's outputs are verified by the same
lean-cli verifier as every other source; ``state_after`` is never read.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import Settings, load_settings
from .proposer import CandidateProposer, ProposedCandidate
from .tactic_sanitizer import split_raw_output

logger = logging.getLogger(__name__)

LLM_PROPOSER_SOURCE = "llm_proposer"

SYSTEM_PROMPT = (
    "You are a Lean 4 tactic generator. Given a theorem and its tactic state, "
    "propose candidate proofs. Rules: output ONLY a JSON list of strings; each "
    "string is a Lean tactic or short multi-line tactic block that closes the "
    "goal; use core Lean 4 only (NO Mathlib, no `import`); prefer short proofs; "
    "no explanations, no markdown, no comments."
)


def _detect_backend(settings: Settings, backend: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(backend, api_key)`` for the first usable backend, or
    ``(None, None)`` when no key is configured."""
    if backend in (None, "auto"):
        if settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic", settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        if settings.openai_api_key or os.environ.get("OPENAI_API_KEY"):
            return "openai", settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
        return None, None
    if backend == "anthropic":
        return "anthropic", settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
    if backend == "openai":
        return "openai", settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
    return None, None


def parse_tactic_list(text: str) -> List[str]:
    """Best-effort parse of an LLM response into a list of tactic strings.

    Accepts a bare JSON list, a ```json fenced block, or — as a fallback —
    newline/blank-line split via the shared sanitizer. Tolerant of garbage."""
    if not text:
        return []
    stripped = text.strip()
    # Strip a leading ```json / ``` fence if present.
    fence = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    # 1. Try to locate and parse a JSON array.
    start, end = stripped.find("["), stripped.rfind("]")
    if 0 <= start < end:
        try:
            arr = json.loads(stripped[start : end + 1])
            if isinstance(arr, list):
                out = [str(x).strip() for x in arr if str(x).strip()]
                if out:
                    return out
        except (json.JSONDecodeError, ValueError):
            pass
    # 2. Fallback: treat as raw text and split.
    return [c for c in split_raw_output(stripped, None) if c.strip()]


class LLMProposer(CandidateProposer):
    """API-key-gated LLM candidate source. Lazily imports the SDK only when it
    actually issues a call, so importing this module never needs a key or SDK."""

    name = "llm_proposer"

    def __init__(
        self,
        *,
        settings: Optional[Settings] = None,
        backend: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        num_request: int = 8,
        examples: Optional[Sequence[Tuple[str, str]]] = None,
    ) -> None:
        self._settings = settings or load_settings()
        self.backend, self._api_key = _detect_backend(self._settings, backend)
        self.model = model or self._settings.llm_model
        self.temperature = temperature
        self.num_request = num_request
        # Optional few-shot (state_before, tactic) pairs; caller excludes the test theorem.
        self.examples = list(examples or [])
        self._client = None  # lazily constructed

    def available(self) -> bool:
        return bool(self.backend and self._api_key)

    def status(self) -> Dict[str, Any]:
        return {
            "available": self.available(),
            "backend": self.backend,
            "model": self.model if self.available() else None,
            "reason": None if self.available() else "no API key (ANTHROPIC_API_KEY / OPENAI_API_KEY unset)",
        }

    # ---- prompt + call ----

    def _build_user_prompt(self, theorem_statement: str, state_before: str, n: int) -> str:
        parts: List[str] = []
        if self.examples:
            parts.append("Examples of correct (state -> tactic) proofs from other theorems:")
            for st, tac in self.examples[:6]:
                parts.append(f"State:\n{st}\nProof:\n{tac}\n")
        parts.append(
            f"Now propose up to {n} distinct candidate proofs as a JSON list of strings "
            f"for this goal.\n\nTheorem: {theorem_statement}\n\nTactic state:\n{state_before}\n"
        )
        return "\n".join(parts)

    def _complete(self, system: str, user: str) -> str:  # pragma: no cover - needs network/key
        if self.backend == "anthropic":
            if self._client is None:
                from anthropic import Anthropic
                self._client = Anthropic(api_key=self._api_key)
            msg = self._client.messages.create(
                model=self.model, max_tokens=700, temperature=self.temperature,
                system=system, messages=[{"role": "user", "content": user}],
            )
            return "\n".join(getattr(b, "text", "") or "" for b in msg.content).strip()
        if self.backend == "openai":
            if self._client is None:
                from openai import OpenAI
                base = self._settings.openai_base_url
                self._client = OpenAI(api_key=self._api_key, base_url=base) if base else OpenAI(api_key=self._api_key)
            resp = self._client.chat.completions.create(
                model=self.model, max_tokens=700, temperature=self.temperature,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            return (resp.choices[0].message.content or "").strip()
        return ""

    def propose(
        self,
        theorem_statement: str,
        state_before: str,
        *,
        theorem_name: Optional[str] = None,
        pattern_family: Optional[str] = None,
        max_candidates: int = 10,
    ) -> List[ProposedCandidate]:
        if not self.available():
            return []  # skip cleanly — never faked
        user = self._build_user_prompt(theorem_statement, state_before, max(self.num_request, max_candidates))
        try:
            raw = self._complete(SYSTEM_PROMPT, user)
        except Exception as exc:  # noqa: BLE001 - network/SDK errors must not crash the eval
            logger.warning("LLMProposer call failed for %s: %s", theorem_name, exc)
            return []
        tactics = parse_tactic_list(raw)
        out: List[ProposedCandidate] = []
        seen: set = set()
        for rank, tac in enumerate(tactics):
            if tac in seen:
                continue
            seen.add(tac)
            out.append(ProposedCandidate(
                tactic=tac, source=LLM_PROPOSER_SOURCE, score=float(len(tactics) - rank),
                metadata={"model": self.model, "backend": self.backend, "rank": rank},
            ))
            if len(out) >= max_candidates:
                break
        return out
