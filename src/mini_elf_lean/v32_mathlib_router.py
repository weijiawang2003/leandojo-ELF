"""Mini-ELF v32 — Mathlib/broad-core router (best v32 specialist; v31/v30 fallback).

Engineering switch: core-env → untouched v24; mathlib-env → the best v32 specialist
(the repaired canonical model) if it beats v31 safely, else fall back. No per-theorem
routing. Identical policy to v31; versioned for a self-contained release. The canonical
specialist generates in canonical space and concretizes with a raw fallback union
(handled by the eval pool builder, not the router).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Set

from mini_elf_lean.v26_mathlib_router import BROAD_CORE, MATHLIB_SPECIALIST, _wants_mathlib


@dataclass
class V32MathlibRouter:
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


__all__ = ["V32MathlibRouter", "BROAD_CORE", "MATHLIB_SPECIALIST"]
