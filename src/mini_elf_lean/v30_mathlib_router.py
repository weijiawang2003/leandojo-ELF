"""Mini-ELF v30 — Mathlib/broad-core model router (best v30 specialist for Mathlib).

An **engineering switch**, not theorem reasoning: core-env → the **untouched v24
broad-core** model; mathlib-env → the best v30 specialist. No per-theorem and no
per-category routing (v29 showed one density-scaled general model dominates; v30 only
density-repairs it). Identical policy to `V29MathlibRouter`; the class is versioned so
each release has a self-contained, inspectable router. Never injects templates, reads
`state_after`, or uses manual-oracle outputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Set

from mini_elf_lean.v26_mathlib_router import BROAD_CORE, MATHLIB_SPECIALIST, _wants_mathlib


@dataclass
class V30MathlibRouter:
    """Route a theorem's environment → model key: broad_core | mathlib_specialist."""

    available: Set[str] = field(default_factory=lambda: {BROAD_CORE, MATHLIB_SPECIALIST})
    fallback: str = BROAD_CORE
    specialist_key: str = MATHLIB_SPECIALIST
    broad_key: str = BROAD_CORE

    def route_seed(self, seed: Dict[str, Any]) -> str:
        wants = _wants_mathlib(imports=seed.get("imports"),
                               mathlib_flag=seed.get("mathlib") or seed.get("uses_mathlib"),
                               source=seed.get("source") or seed.get("corpus_source")
                               or seed.get("benchmark_source"))
        if not wants:
            return self.broad_key if self.broad_key in self.available else self.fallback
        if self.specialist_key in self.available:
            return self.specialist_key
        return self.fallback if self.fallback in self.available else self.broad_key

    def explain(self, seed: Dict[str, Any]) -> Dict[str, Any]:
        chosen = self.route_seed(seed)
        wants = _wants_mathlib(imports=seed.get("imports"), mathlib_flag=seed.get("mathlib"),
                               source=seed.get("source") or seed.get("corpus_source"))
        reason = ("core-env -> broad_core" if not wants else
                  "mathlib-env -> mathlib_specialist" if chosen == self.specialist_key else
                  "mathlib-env -> fallback(specialist unavailable)")
        return {"theorem_name": seed.get("theorem_name", ""), "chosen_model": chosen,
                "wants_mathlib": wants,
                "category": (seed.get("category") or "").strip().lower(), "reason": reason}


__all__ = ["V30MathlibRouter", "BROAD_CORE", "MATHLIB_SPECIALIST"]
