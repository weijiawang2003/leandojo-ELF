"""Mini-ELF v19 — identifier abstraction / concretisation.

Replaces local-context identifiers with stable placeholders so the
seq2seq learns *role*-based tactics rather than name-based tactics.

The pipeline:

  1. ``abstract_state(state, tactic)`` returns
     (abstract_state, abstract_tactic, placeholder_map).
     The map records what each placeholder was bound to so the
     reverse direction can rebuild the original tactic if needed.
  2. ``concretise_tactic(abstract_tactic, state)`` reverses the
     abstraction: given a *new* state's local context, fill in the
     placeholders with the right actual names. Used at inference
     time on the v18 broad-core benchmark.
  3. ``concretise_or_fail(abstract_tactic, state)`` returns
     ``(concretised, reason)`` where ``reason`` is ``"ok"`` or one
     of the v19 brief's failure classes
     (``unresolved_placeholder``, etc.).

**Honesty contract** (v19 brief):
  * No ``state_after`` anywhere.
  * No manual oracle: placeholders are derived from
    ``state_before`` text only.
  * Concretisation can fail; we never silently substitute a wrong
    name. Unresolved placeholders produce a ``concretisation_failed``
    sentinel that the eval pipeline treats as a model failure.
  * Word-boundary aware: we never replace identifier substrings
    inside longer identifiers (``h`` inside ``hp``) or inside Lean
    keywords.

Placeholder naming:
  * Each ``TypeCategory`` gets its own counter; placeholders are
    numbered in source order within their category.
  * Example state ``p q : Prop\\nh : p → q\\nhp : p`` produces
    ``<PROP_0>=p, <PROP_1>=q, <HYP_IMP_0>=h, <HYP_PROP_0>=hp``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .local_context import (
    Hypothesis, LocalContext, TypeCategory, parse_state,
)


# Tokenizer-keyword set imported lazily — we don't want a hard
# dependency cycle and the import in v18+ token paths is heavier.
def _lean_keywords() -> frozenset:
    try:
        from .tactic_tokenizer import KEYWORDS as _KW
        return frozenset(_KW)
    except Exception:  # pragma: no cover - tokenizer unavailable
        return frozenset({
            "exact", "intro", "intros", "apply", "rw", "rcases", "cases",
            "refine", "constructor", "use", "have", "show",
            "rfl", "simp", "omega", "decide", "trivial", "absurd",
            "linarith", "norm_num", "ring", "tauto", "exfalso",
            "contradiction", "by", "with", "at", "in", "let", "fun",
            "match", "all_goals", "any_goals", "first", "try",
            "repeat", "skip",
        })


# Stable mapping from TypeCategory → placeholder prefix.
_CATEGORY_PREFIX: Dict[TypeCategory, str] = {
    TypeCategory.PROP: "PROP",
    TypeCategory.IMPLICATION: "HYP_IMP",
    TypeCategory.NEGATION: "HYP_NEG",
    TypeCategory.CONJUNCTION: "HYP_AND",
    TypeCategory.DISJUNCTION: "HYP_OR",
    TypeCategory.EQUALITY: "HYP_EQ",
    TypeCategory.FORALL: "HYP_FORALL",
    TypeCategory.EXISTS: "HYP_EXISTS",
    TypeCategory.NAT: "VAR_NAT",
    TypeCategory.BOOL: "VAR_BOOL",
    TypeCategory.LIST: "VAR_LIST",
    TypeCategory.HYP_PROP: "HYP_PROP",
    TypeCategory.TYPE: "TYPE",
    TypeCategory.UNKNOWN: "HYP_OTHER",
}


@dataclass
class AbstractionMap:
    """Two-way map between original local identifiers and v19
    placeholders. ``ctx`` is the parsed context the map was built
    against — kept for downstream audit.
    """

    name_to_ph: Dict[str, str] = field(default_factory=dict)
    ph_to_name: Dict[str, str] = field(default_factory=dict)
    ctx: Optional[LocalContext] = None
    state_signature: Tuple[str, ...] = ()

    def get_placeholder(self, name: str) -> Optional[str]:
        return self.name_to_ph.get(name)

    def get_name(self, placeholder: str) -> Optional[str]:
        return self.ph_to_name.get(placeholder)

    def __iter__(self):
        return iter(self.name_to_ph.items())


# --------------------------------------------------------------------------- #
# Building the abstraction map
# --------------------------------------------------------------------------- #


def build_abstraction_map(state: str) -> AbstractionMap:
    """Parse ``state``, then walk hypotheses in source order and
    assign each a placeholder ``<CATEGORY_INDEX>`` where INDEX is
    the per-category counter."""
    ctx = parse_state(state)
    counters: Dict[TypeCategory, int] = {}
    name_to_ph: Dict[str, str] = {}
    ph_to_name: Dict[str, str] = {}

    for h in ctx.hypotheses:
        prefix = _CATEGORY_PREFIX.get(h.category, "HYP_OTHER")
        idx = counters.get(h.category, 0)
        ph = f"<{prefix}_{idx}>"
        counters[h.category] = idx + 1
        # If the same name appears twice (shouldn't normally), the
        # second occurrence shadows the first in name_to_ph but
        # keeps both ph_to_name entries pointing back.
        name_to_ph[h.name] = ph
        ph_to_name[ph] = h.name

    return AbstractionMap(
        name_to_ph=name_to_ph,
        ph_to_name=ph_to_name,
        ctx=ctx,
        state_signature=tuple(
            f"{_CATEGORY_PREFIX[c]}_{n}"
            for c, n in counters.items()
        ),
    )


# --------------------------------------------------------------------------- #
# Word-boundary-aware substitution
# --------------------------------------------------------------------------- #


def _replace_idents(text: str, mapping: Dict[str, str],
                    *, protected: frozenset) -> str:
    """Replace each identifier in ``mapping`` with its image, but
    only at *word boundaries* (so ``h`` is not replaced inside
    ``hp``) and never if the matched word is a Lean tactic
    keyword in ``protected``.

    The function processes longest-name-first to handle cases like
    ``hp`` and ``h`` both being in scope: ``hp`` is replaced before
    ``h``.
    """
    if not mapping:
        return text
    # Sort by descending length, so multi-char names are replaced
    # before their prefixes.
    pairs = sorted(mapping.items(), key=lambda kv: -len(kv[0]))
    # We do replacements via a single regex sweep with alternation
    # so we don't double-replace. Build a regex that matches any
    # of the source names as a whole word.
    escaped = [re.escape(name) for name, _ in pairs]
    # Word boundary on either side. Unicode word chars include Greek.
    pattern = re.compile(
        r"(?<![A-Za-zα-ωΑ-Ω0-9_'])(" + "|".join(escaped) + r")(?![A-Za-zα-ωΑ-Ω0-9_'])"
    )

    name_to_ph = dict(pairs)

    def _sub(m: re.Match) -> str:
        name = m.group(1)
        if name in protected:
            return name
        return name_to_ph.get(name, name)

    return pattern.sub(_sub, text)


# --------------------------------------------------------------------------- #
# Public abstraction / concretisation API
# --------------------------------------------------------------------------- #


def abstract_state(state: str, tactic: str
                   ) -> Tuple[str, str, AbstractionMap]:
    """Replace local-context identifiers in *both* ``state`` and
    ``tactic`` with their placeholders. Returns
    (abstract_state, abstract_tactic, map).

    Tactic keywords are never substituted. Placeholder text is
    word-boundary protected.
    """
    am = build_abstraction_map(state)
    kw = _lean_keywords()
    abs_state = _replace_idents(state, am.name_to_ph, protected=kw)
    abs_tactic = _replace_idents(tactic, am.name_to_ph, protected=kw)
    return abs_state, abs_tactic, am


def abstract_tactic_only(state: str, tactic: str) -> Tuple[str, AbstractionMap]:
    """Same as ``abstract_state`` but returns only the abstract
    tactic + map (state is parsed but not transformed)."""
    am = build_abstraction_map(state)
    kw = _lean_keywords()
    abs_tactic = _replace_idents(tactic, am.name_to_ph, protected=kw)
    return abs_tactic, am


def concretise_or_fail(abstract_tactic: str, state: str
                       ) -> Tuple[Optional[str], str]:
    """Return (concretised_tactic, reason). ``reason`` is one of:
       * ``"ok"`` — every placeholder resolved
       * ``"unresolved_placeholder"`` — at least one placeholder has
         no binding in the new state's context
       * ``"no_placeholders"`` — input contains no placeholder; the
         tactic is returned unchanged (still ``"ok"``-ish but
         labelled for audit).

    Resolution: given the new state, build its abstraction map;
    use ``ph_to_name`` to substitute.
    """
    if "<" not in abstract_tactic or ">" not in abstract_tactic:
        return abstract_tactic, "no_placeholders"

    am = build_abstraction_map(state)
    # Find every placeholder token. Placeholders look like <X_N>.
    placeholders = set(re.findall(r"<[A-Z_]+_\d+>", abstract_tactic))
    unresolved = [p for p in placeholders if p not in am.ph_to_name]
    if unresolved:
        return None, "unresolved_placeholder"

    # Substitute longest-placeholder first to be safe (though all
    # placeholders are guaranteed to be word-token-shaped).
    out = abstract_tactic
    for ph in sorted(placeholders, key=lambda s: -len(s)):
        name = am.ph_to_name[ph]
        out = out.replace(ph, name)
    return out, "ok"


def concretise_tactic(abstract_tactic: str, state: str) -> Optional[str]:
    """Lighter helper that returns just the concretised string or
    None on failure."""
    out, reason = concretise_or_fail(abstract_tactic, state)
    return out if reason in ("ok", "no_placeholders") else None


def remap_tactic_across_states(tactic: str, old_state: str,
                               new_state: str) -> Optional[str]:
    """Convenience: abstract a tactic against ``old_state``, then
    concretise it against ``new_state``. Returns None on
    abstraction-empty or resolution failure."""
    abs_tactic, _ = abstract_tactic_only(old_state, tactic)
    return concretise_tactic(abs_tactic, new_state)


__all__ = [
    "AbstractionMap",
    "abstract_state",
    "abstract_tactic_only",
    "build_abstraction_map",
    "concretise_or_fail",
    "concretise_tactic",
    "remap_tactic_across_states",
]
