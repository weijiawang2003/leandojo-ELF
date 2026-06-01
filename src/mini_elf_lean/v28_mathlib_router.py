"""Mini-ELF v28 — Mathlib/broad-core model router (v27 router + optional Finset route).

An **engineering switch**, not theorem reasoning: given a theorem's environment
(imports / mathlib flag / corpus source, and — for the optional Finset route only —
its category family), decide which trained generator to use. It preserves the v26/v27
invariant: every broad-core theorem keeps using the **untouched v24 broad-core
model**, so broad-core cannot be cannibalized.

Routing policy (deterministic, inspectable, no theorem-specific cheating):

    not mathlib-env                              -> broad_core (v24, untouched)
    mathlib-env AND category == finset
        AND finset route enabled & available     -> finset_specialist   (optional)
    mathlib-env (otherwise)                       -> mathlib_specialist  (best v28)

The Finset sub-route is **off by default** and only switched on when a separate
Finset specialist has been trained AND validated to not regress the general Mathlib
tier (V28 Part 7). Category is an environment/family tag (which corpus family a
theorem belongs to), not a per-theorem proof decision; the route is enabled for
Finset only, per the v28 plan. The router never injects templates, reads
`state_after`, or uses manual-oracle outputs — it only picks a generator and the
matching verifier backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Set

from mini_elf_lean.v26_mathlib_router import (
    BROAD_CORE, MATHLIB_SPECIALIST, _wants_mathlib,
)

FINSET_SPECIALIST = "finset_specialist"


@dataclass
class V28MathlibRouter:
    """Route a theorem's environment → model key.

    broad_core | mathlib_specialist | (optional) finset_specialist.
    """

    available: Set[str] = field(default_factory=lambda: {BROAD_CORE, MATHLIB_SPECIALIST})
    fallback: str = BROAD_CORE
    specialist_key: str = MATHLIB_SPECIALIST
    broad_key: str = BROAD_CORE
    finset_key: str = FINSET_SPECIALIST
    enable_finset_route: bool = False  # only true after Part-7 validation

    def _category(self, seed: Dict[str, Any]) -> str:
        return (seed.get("category") or seed.get("expected_skill") or "").strip().lower()

    def route_seed(self, seed: Dict[str, Any]) -> str:
        wants = _wants_mathlib(imports=seed.get("imports"),
                               mathlib_flag=seed.get("mathlib") or seed.get("uses_mathlib"),
                               source=seed.get("source") or seed.get("corpus_source")
                               or seed.get("benchmark_source"))
        if not wants:
            return self.broad_key if self.broad_key in self.available else self.fallback
        if (self.enable_finset_route and self._category(seed) == "finset"
                and self.finset_key in self.available):
            return self.finset_key
        if self.specialist_key in self.available:
            return self.specialist_key
        return self.fallback if self.fallback in self.available else self.broad_key

    def explain(self, seed: Dict[str, Any]) -> Dict[str, Any]:
        chosen = self.route_seed(seed)
        wants = _wants_mathlib(imports=seed.get("imports"), mathlib_flag=seed.get("mathlib"),
                               source=seed.get("source") or seed.get("corpus_source"))
        if not wants:
            reason = "core-env -> broad_core"
        elif chosen == self.finset_key:
            reason = "mathlib-env + finset -> finset_specialist"
        elif chosen == self.specialist_key:
            reason = "mathlib-env -> mathlib_specialist"
        else:
            reason = "mathlib-env -> fallback(specialist unavailable)"
        return {"theorem_name": seed.get("theorem_name", ""), "chosen_model": chosen,
                "wants_mathlib": wants, "category": self._category(seed), "reason": reason}


__all__ = ["V28MathlibRouter", "BROAD_CORE", "MATHLIB_SPECIALIST", "FINSET_SPECIALIST"]
