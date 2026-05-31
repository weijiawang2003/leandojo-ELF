"""Mini-ELF v21 — category-based model router.

An **engineering** layer, not theorem reasoning: given a theorem's
category (or required_operation), decide *which trained model's beam*
to use. This recovers the v20 forall regression by routing forall
goals to a model that still emits the `exact h <arg>` instantiation
schema, while keeping implication/bool on the v20 broad-plus model.

The router is deterministic and inspectable — a switch, nothing
learned. It does **not** inject proof templates, read `state_after`,
or use manual oracle outputs; it only chooses a generator.

Routing policy (default):

    forall / instantiate_forall        -> "forall_specialist"
    implication / bool / conjunction   -> "broad_plus"
    everything else                    -> "broad_plus"  (the validated
                                          general default)

A fallback model key is returned when the requested specialist is
unavailable, so a missing specialist degrades to the broad model
rather than crashing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set

# Default model keys.
BROAD_PLUS = "broad_plus"
FORALL_SPECIALIST = "forall_specialist"


#: Categories (v18 broad-core taxonomy) routed to the forall
#: specialist. Kept as a set so it is trivially auditable/extensible.
FORALL_CATEGORIES: Set[str] = {"forall"}

#: required_operation tags routed to the forall specialist.
FORALL_OPERATIONS: Set[str] = {"instantiate_forall"}


@dataclass
class ModelRouter:
    """Route (category, operation) → model key.

    ``available`` is the set of model keys that actually loaded; a
    route to an unavailable key falls back to ``fallback`` (default
    ``broad_plus``).
    """

    available: Set[str] = field(default_factory=lambda: {BROAD_PLUS})
    fallback: str = BROAD_PLUS
    forall_key: str = FORALL_SPECIALIST
    broad_key: str = BROAD_PLUS

    def route(self, *, category: Optional[str] = None,
              required_operation: Optional[str] = None) -> str:
        """Return the model key to use for this theorem."""
        cat = (category or "").strip().lower()
        op = (required_operation or "").strip().lower()
        wants_forall = cat in FORALL_CATEGORIES or op in FORALL_OPERATIONS
        if wants_forall:
            if self.forall_key in self.available:
                return self.forall_key
            return self.fallback if self.fallback in self.available \
                else self.broad_key
        # impl/bool/everything else -> broad model
        if self.broad_key in self.available:
            return self.broad_key
        return self.fallback

    def explain(self, *, category: Optional[str] = None,
                required_operation: Optional[str] = None) -> Dict[str, str]:
        """Return a small dict explaining the routing decision (for
        audit / predictions provenance)."""
        chosen = self.route(category=category,
                            required_operation=required_operation)
        cat = (category or "").strip().lower()
        op = (required_operation or "").strip().lower()
        wants_forall = cat in FORALL_CATEGORIES or op in FORALL_OPERATIONS
        reason = ("forall->specialist" if wants_forall
                  and chosen == self.forall_key
                  else "forall->fallback(specialist unavailable)"
                  if wants_forall else "default->broad_plus")
        return {"category": category or "", "operation": required_operation or "",
                "chosen_model": chosen, "reason": reason}


__all__ = [
    "ModelRouter", "BROAD_PLUS", "FORALL_SPECIALIST",
    "FORALL_CATEGORIES", "FORALL_OPERATIONS",
]
