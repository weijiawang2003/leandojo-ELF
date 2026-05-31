"""Mini-ELF v23 — refreshed reranker features (scoring-only).

Extends the v15 :func:`mini_elf_lean.rerank_dataset.extract_features`
with the signals the v22 broad-core analysis showed were missing — most
importantly an **unbound-identifier penalty** (the v22 generator's
rank-0 misses are dominated by candidates that name a hypothesis not in
the local context, e.g. ``rw [x]`` / ``exact False.elim (h hp)``) and
**category-specific** structural cues for the categories the abstract
reranker mis-ranked (negation, disjunction, nat_succ).

The abstraction machinery from v19/v20 is reused **only to score**: it
abstracts a candidate to a pattern to look up its training frequency and
to count identifiers that don't bind to the current local context. This
module **never emits a placeholder candidate** — it returns a feature
dict; the reranker reorders the *original raw-name* candidates. (RQ3:
ranker-time abstraction is a feature, not the sole ranker.)

Honesty: no state_after (input is theorem_statement + state_before +
candidate), no manual oracle, no Mathlib, no generation change.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Mapping, Optional

from .abstract_pattern_reranker import (
    PatternBag, _BUILTIN_TOKENS, _candidate_identifiers, _is_numeric,
)
from .identifier_abstraction import abstract_tactic_only, build_abstraction_map
from .rerank_dataset import CandidateRow, extract_features

# v18 broad-core categories — one-hot'd so the LR can learn a
# per-category bias / interact category with the structural cues.
CATEGORIES = ("implication", "conjunction", "disjunction", "negation",
              "equality_rewrite", "exists", "forall", "nat_succ", "bool",
              "list")


def row_to_candidate_row(d: Mapping[str, Any]) -> CandidateRow:
    """Build a v15 CandidateRow from a v23 pooled-dataset dict. The v18
    broad-core `category` is carried in ``family`` (broad-core has no
    separate proof-family), so the v15 features see it too."""
    return CandidateRow(
        theorem_name=d.get("theorem_name", ""),
        family=d.get("category", "unknown"),
        required_operation=d.get("required_operation"),
        theorem_statement=d.get("theorem_statement", ""),
        state_before=d.get("state_before", ""),
        candidate=d.get("candidate", ""),
        candidate_source=d.get("candidate_source", "unknown"),
        beam_rank=int(d.get("beam_rank", 0)),
        verified=bool(d.get("verified", False)),
        error_class=d.get("error_class", "ok"),
        source_run=d.get("source_model", d.get("source_run", "unknown")),
    )


def _local_names(state_before: str):
    try:
        am = build_abstraction_map(state_before or "")
        return set(am.name_to_ph.keys())
    except Exception:  # pragma: no cover - defensive
        return set()


_IDENT = re.compile(r"[A-Za-zα-ωΑ-Ω_][A-Za-zα-ωΑ-Ω0-9_']*")


def _locally_bound_names(candidate: str) -> set:
    """Names *introduced within the candidate itself* — by ``intro``,
    anonymous constructors ``⟨a, b⟩``, ``fun x =>``, or ``| ctor a b =>``
    case arms. These must NOT be counted as unbound (the v22 verified
    negation candidate ``intro hp\\n exact absurd hp h`` binds ``hp``)."""
    names: set = set()
    c = candidate or ""

    def _add(seg: str) -> None:
        for tok in _IDENT.findall(seg):
            if not _is_numeric(tok) and tok not in _BUILTIN_TOKENS:
                names.add(tok)

    for seg in re.findall(r"⟨([^⟨⟩]*)⟩", c):           # ⟨n, hn⟩
        _add(seg)
    for m in re.finditer(r"\b(?:intro|intros|rintro)\b([^\n;]*)", c):
        _add(m.group(1))
    for m in re.finditer(r"\bfun\b(.*?)=>", c):          # fun hp =>
        _add(m.group(1))
    for m in re.finditer(r"\|\s*[A-Za-z_][\w.]*([^=>]*)=>", c):  # | intro n hn =>
        _add(m.group(1))
    return names


def unbound_identifier_count(candidate: str, state_before: str) -> int:
    """Count identifiers in the candidate that are neither Lean builtins,
    in the local context, locally bound by the candidate, nor numerals —
    i.e. names that will not resolve. The single highest-value v23 signal."""
    local = _local_names(state_before) | _locally_bound_names(candidate)
    n = 0
    for ident in _candidate_identifiers(candidate or ""):
        if ident in _BUILTIN_TOKENS or ident in local or _is_numeric(ident):
            continue
        n += 1
    return n


def _abstract_pattern(state_before: str, candidate: str) -> str:
    try:
        pat, _ = abstract_tactic_only(state_before or "", candidate or "")
        return pat
    except Exception:  # pragma: no cover
        return candidate or ""


def extract_v23_features(d: Mapping[str, Any], *,
                         pattern_bag: Optional[PatternBag] = None,
                         category_features: bool = True,
                         hashed_dim: int = 256) -> Dict[str, float]:
    """v15 features + v23 additions. ``pattern_bag`` (verified training
    patterns) enables the seen-in-train / category-match features; when
    absent those features are simply 0.

    ``category_features`` toggles the category one-hot + category-specific
    structural cues + category×cue interactions. The plain config (B)
    sets it False (grounding + abstract-pattern only); the category-aware
    config (C) sets it True. The grounding signals (unbound idents,
    abstract pattern) are always on."""
    row = row_to_candidate_row(d)
    feats: Dict[str, float] = dict(extract_features(row, hashed_dim=hashed_dim))

    t = d.get("candidate", "") or ""
    state = d.get("state_before", "") or ""
    category = d.get("category", "") or ""

    # ---- grounding: unbound identifiers (THE key v23 signal) ----
    n_unbound = unbound_identifier_count(t, state)
    feats["v23_unbound_ident_count"] = float(n_unbound)
    feats["v23_has_unbound_ident"] = 1.0 if n_unbound > 0 else 0.0
    feats["v23_binds_cleanly"] = 1.0 if n_unbound == 0 else 0.0  # placeholder-compat

    idents = [i for i in _candidate_identifiers(t)
              if not _is_numeric(i) and i not in _BUILTIN_TOKENS]
    local = _local_names(state) | _locally_bound_names(t)
    in_scope = sum(1 for i in idents if i in local)
    feats["v23_local_name_in_scope_ratio"] = (
        in_scope / len(idents) if idents else 1.0)

    # ---- abstract pattern (scoring feature, never an output) ----
    pat = _abstract_pattern(state, t)
    if pattern_bag is not None:
        cnt = pattern_bag.lookup(pat, category)
        cat_cnt = pattern_bag.by_category.get(category, {}).get(pat, 0)
        feats["v23_abstract_pattern_logcount"] = math.log1p(cnt)
        feats["v23_abstract_pattern_seen"] = 1.0 if cnt > 0 else 0.0
        feats["v23_abstract_pattern_cat_match"] = 1.0 if cat_cnt > 0 else 0.0
    else:
        feats["v23_abstract_pattern_logcount"] = 0.0
        feats["v23_abstract_pattern_seen"] = 0.0
        feats["v23_abstract_pattern_cat_match"] = 0.0

    if not category_features:
        return feats

    # ---- category one-hot ----
    if category in CATEGORIES:
        feats[f"v23_cat_{category}"] = 1.0

    # ---- category-specific structural cues ----
    # negation: the v22 rank-bound miss is `intro hp\n exact absurd hp h`.
    feats["v23_neg_false_elim"] = 1.0 if "False.elim" in t else 0.0
    feats["v23_neg_absurd"] = 1.0 if "absurd" in t else 0.0
    feats["v23_neg_dot_elim"] = 1.0 if ".elim" in t else 0.0
    feats["v23_neg_intro_absurd_combo"] = (
        1.0 if (("intro" in t) and ("absurd" in t)) else 0.0)
    # disjunction
    feats["v23_disj_inl"] = 1.0 if "Or.inl" in t or "inl" in t else 0.0
    feats["v23_disj_inr"] = 1.0 if "Or.inr" in t or "inr" in t else 0.0
    feats["v23_disj_cases"] = 1.0 if "cases" in t else 0.0
    # nat_succ
    feats["v23_nat_rfl"] = 1.0 if "rfl" in t else 0.0
    feats["v23_nat_rw"] = 1.0 if re.search(r"\brw\b", t) else 0.0
    feats["v23_nat_congr_succ"] = 1.0 if "congrArg" in t and "succ" in t else 0.0

    # interaction: category × structural cue (lets the LR learn that
    # absurd is good *for negation* without globally boosting it).
    if category == "negation":
        feats["v23_negXabsurd"] = feats["v23_neg_absurd"]
        feats["v23_negXintro_absurd"] = feats["v23_neg_intro_absurd_combo"]
    if category == "disjunction":
        feats["v23_disjXinl_inr"] = max(feats["v23_disj_inl"],
                                        feats["v23_disj_inr"])
    if category in ("nat_succ", "equality_rewrite", "list"):
        feats["v23_eqXrfl"] = feats["v23_nat_rfl"]

    return feats


__all__ = [
    "CATEGORIES", "extract_v23_features", "row_to_candidate_row",
    "unbound_identifier_count",
]
