"""Mini-ELF v29 — Mathlib/broad-core model router (v28 router + best v29 specialist).

An **engineering switch**, not theorem reasoning: given a theorem's environment
(imports / mathlib flag / corpus source), decide which trained generator to use. It
preserves the v26/v27/v28 invariant: every broad-core theorem keeps using the
**untouched v24 broad-core model**, so broad-core cannot be cannibalized.

Routing policy (deterministic, inspectable, no theorem-specific cheating):

    not mathlib-env                 -> broad_core (v24, untouched)
    mathlib-env                     -> mathlib_specialist (best v29)

There is **no per-theorem / per-family routing** in v29: the v28 Finset sub-route
was a category switch that only helped when a separate Finset specialist beat the
general model on the Finset holdout. v29's whole thesis is that one density-scaled
*general* model dominates, so the default is a single Mathlib specialist. An optional
category sub-route (`enable_category_route` + a `category_specialist`) is kept for
parity but is **off by default** and only used if Part-7 validation shows a category
specialist strictly beating the general model without regressing the rest.

The router never injects templates, reads `state_after`, or uses manual-oracle
outputs — it only picks a generator and the matching verifier backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

from mini_elf_lean.v26_mathlib_router import (
    BROAD_CORE, MATHLIB_SPECIALIST, _wants_mathlib,
)

CATEGORY_SPECIALIST = "category_specialist"


@dataclass
class V29MathlibRouter:
    """Route a theorem's environment → model key: broad_core | mathlib_specialist
    | (optional, off by default) category_specialist."""

    available: Set[str] = field(default_factory=lambda: {BROAD_CORE, MATHLIB_SPECIALIST})
    fallback: str = BROAD_CORE
    specialist_key: str = MATHLIB_SPECIALIST
    broad_key: str = BROAD_CORE
    category_key: str = CATEGORY_SPECIALIST
    enable_category_route: bool = False  # only true after Part-7 validation
    route_categories: Set[str] = field(default_factory=set)  # e.g. {"finset"} if enabled

    def _category(self, seed: Dict[str, Any]) -> str:
        return (seed.get("category") or seed.get("expected_skill") or "").strip().lower()

    def route_seed(self, seed: Dict[str, Any]) -> str:
        wants = _wants_mathlib(imports=seed.get("imports"),
                               mathlib_flag=seed.get("mathlib") or seed.get("uses_mathlib"),
                               source=seed.get("source") or seed.get("corpus_source")
                               or seed.get("benchmark_source"))
        if not wants:
            return self.broad_key if self.broad_key in self.available else self.fallback
        if (self.enable_category_route and self._category(seed) in self.route_categories
                and self.category_key in self.available):
            return self.category_key
        if self.specialist_key in self.available:
            return self.specialist_key
        return self.fallback if self.fallback in self.available else self.broad_key

    def explain(self, seed: Dict[str, Any]) -> Dict[str, Any]:
        chosen = self.route_seed(seed)
        wants = _wants_mathlib(imports=seed.get("imports"), mathlib_flag=seed.get("mathlib"),
                               source=seed.get("source") or seed.get("corpus_source"))
        if not wants:
            reason = "core-env -> broad_core"
        elif chosen == self.category_key:
            reason = f"mathlib-env + {self._category(seed)} -> category_specialist"
        elif chosen == self.specialist_key:
            reason = "mathlib-env -> mathlib_specialist"
        else:
            reason = "mathlib-env -> fallback(specialist unavailable)"
        return {"theorem_name": seed.get("theorem_name", ""), "chosen_model": chosen,
                "wants_mathlib": wants, "category": self._category(seed), "reason": reason}


__all__ = ["V29MathlibRouter", "BROAD_CORE", "MATHLIB_SPECIALIST", "CATEGORY_SPECIALIST"]
