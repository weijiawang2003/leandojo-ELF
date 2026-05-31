"""Mini-ELF v26 — Mathlib/broad-core model router.

An **engineering switch**, not theorem reasoning: given a theorem's environment
(its imports / benchmark source / mathlib flag), decide which trained generator
to use — the v24 broad-core model or the v26 Mathlib specialist. It exists so
the Mathlib tier can improve **without** touching broad-core performance: every
broad-core theorem keeps using the untouched v24 model, so it cannot be
cannibalized the way v25's single co-trained model was.

Routing policy (deterministic, inspectable, no theorem-specific cheating):

    imports contain "import Mathlib"            -> mathlib_specialist
    OR seed.mathlib == True                      -> mathlib_specialist
    OR source/benchmark mentions mathlib/tierc   -> mathlib_specialist
    else                                         -> broad_core

A fallback key is returned when the requested model is unavailable, so a missing
specialist degrades to broad-core rather than crashing. The router does not
inject proof templates, read `state_after`, or use manual-oracle outputs; it
only picks a generator (and the matching verifier backend).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Set

BROAD_CORE = "broad_core"
MATHLIB_SPECIALIST = "mathlib_specialist"

_MATHLIB_IMPORT_TOKENS = ("import mathlib",)
_MATHLIB_SOURCE_TOKENS = ("mathlib", "tierc", "tier_c", "tier-c")


def _wants_mathlib(*, imports: Optional[Sequence[str]] = None,
                   mathlib_flag: Optional[bool] = None,
                   source: Optional[str] = None) -> bool:
    if mathlib_flag:
        return True
    for imp in (imports or []):
        low = (imp or "").strip().lower()
        if any(tok in low for tok in _MATHLIB_IMPORT_TOKENS):
            return True
    src = (source or "").strip().lower()
    if src and any(tok in src for tok in _MATHLIB_SOURCE_TOKENS):
        return True
    return False


@dataclass
class MathlibRouter:
    """Route a theorem's environment → model key (broad_core | mathlib_specialist)."""

    available: Set[str] = field(default_factory=lambda: {BROAD_CORE})
    fallback: str = BROAD_CORE
    specialist_key: str = MATHLIB_SPECIALIST
    broad_key: str = BROAD_CORE

    def route(self, *, imports: Optional[Sequence[str]] = None,
              mathlib_flag: Optional[bool] = None,
              source: Optional[str] = None) -> str:
        if _wants_mathlib(imports=imports, mathlib_flag=mathlib_flag, source=source):
            if self.specialist_key in self.available:
                return self.specialist_key
            return self.fallback if self.fallback in self.available else self.broad_key
        if self.broad_key in self.available:
            return self.broad_key
        return self.fallback

    def route_seed(self, seed: Dict[str, Any]) -> str:
        """Convenience: route directly from a seed/row dict."""
        return self.route(imports=seed.get("imports"),
                          mathlib_flag=seed.get("mathlib") or seed.get("uses_mathlib"),
                          source=seed.get("source") or seed.get("corpus_source")
                          or seed.get("benchmark_source"))

    def explain(self, seed: Dict[str, Any]) -> Dict[str, Any]:
        chosen = self.route_seed(seed)
        wants = _wants_mathlib(imports=seed.get("imports"), mathlib_flag=seed.get("mathlib"),
                               source=seed.get("source") or seed.get("corpus_source"))
        reason = ("mathlib-env -> specialist" if wants and chosen == self.specialist_key
                  else "mathlib-env -> fallback(specialist unavailable)" if wants
                  else "core-env -> broad_core")
        return {"theorem_name": seed.get("theorem_name", ""), "chosen_model": chosen,
                "wants_mathlib": wants, "reason": reason}


__all__ = ["MathlibRouter", "BROAD_CORE", "MATHLIB_SPECIALIST"]
