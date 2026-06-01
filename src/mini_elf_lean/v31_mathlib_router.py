"""Mini-ELF v31 — Mathlib/broad-core router (best v31 specialist, with v30 fallback).

Engineering switch: core-env → untouched v24; mathlib-env → the best v31 specialist
**if it beats v30 safely**, else fall back to the v30 specialist. No per-theorem /
per-category routing. The `specialist_key` is chosen by the adoption rule in Part 7
(token-diversity improves AND broad-core / standard held-outs not regressed AND
unresolved/concretization failures controlled); otherwise it stays `v30`.

The canonical specialist (Approach A) generates in canonical space and concretizes with
a raw v30 fallback union — handled by the eval's pool builder, not the router. The
router only selects which generator a theorem's environment uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Set

from mini_elf_lean.v26_mathlib_router import BROAD_CORE, MATHLIB_SPECIALIST, _wants_mathlib


@dataclass
class V31MathlibRouter:
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
                  "mathlib-env -> fallback")
        return {"theorem_name": seed.get("theorem_name", ""), "chosen_model": chosen,
                "wants_mathlib": wants, "category": (seed.get("category") or "").strip().lower(),
                "reason": reason}


__all__ = ["V31MathlibRouter", "BROAD_CORE", "MATHLIB_SPECIALIST"]
